"""Labs — image-model experimentation endpoints.

Top-level (`/api/labs/...`) rather than project-scoped because the labs page is
a standalone tool. Runs are stored per-user under `{projects_dir}/{user_id}/_labs/`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from novel_to_comic import artifacts
from novel_to_comic.labs import fixtures
from novel_to_comic.labs import storage as labs_storage
from novel_to_comic.labs.registry import get_entry, load_registry
from novel_to_comic.labs.runner import (
    LabsPanelSpec,
    LabsRunSpec,
    LabsRunState,
    start_run,
)
from novel_to_comic.models.prompt import ImagePrompt

from ..auth import get_current_user
from ..db import get_db, reset_db
from ..deps import get_projects_dir

log = logging.getLogger(__name__)
router = APIRouter()

MAX_PANELS = 16
MAX_MODELS = 12
MAX_LABEL_LEN = 200
MAX_STYLE_LEN = 2000
MAX_PROMPT_LEN = 4000


def _user_labs_dir(projects_dir: Path, user_id: str) -> Path:
    return projects_dir / user_id


def _runs_state(request: Request) -> dict[str, LabsRunState]:
    state: dict[str, LabsRunState] | None = getattr(request.app.state, "labs_runs", None)
    if state is None:
        state = {}
        request.app.state.labs_runs = state
    return state


@router.get("/models")
def list_models(user_id: str = Depends(get_current_user)) -> dict[str, Any]:  # noqa: ARG001
    return {"models": [m.to_public_dict() for m in load_registry() if m.enabled]}


@router.get("/fixtures/default")
def get_default_fixture(user_id: str = Depends(get_current_user)) -> dict[str, Any]:  # noqa: ARG001
    scene = dict(fixtures.default_scene())
    # Expose ref image URLs the frontend can render. The actual files are
    # served by `/fixtures/default/refs/{filename}`.
    refs = []
    for ref in scene.get("reference_images") or []:
        if not isinstance(ref, dict):
            continue
        name = ref.get("filename")
        if not name:
            continue
        refs.append({
            **ref,
            "url": f"/api/labs/fixtures/default/refs/{name}",
        })
    scene["reference_images"] = refs
    return scene


@router.get("/fixtures/default/refs/{filename}")
def get_default_fixture_ref(
    filename: str,
    user_id: str = Depends(get_current_user),  # noqa: ARG001
) -> FileResponse:
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = fixtures.REFERENCE_IMAGES_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"Reference image not found: {filename}")
    return FileResponse(path, media_type="image/png")


# ── Project scene import ──────────────────────────────────────────────────────


def _user_project_dirs(projects_dir: Path, user_id: str) -> dict[str, Path]:
    """Map project UUID → directory by joining DB ownership with on-disk slugs."""
    try:
        result = (
            get_db()
            .table("projects")
            .select("id,name")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception:
        reset_db()
        result = (
            get_db()
            .table("projects")
            .select("id,name")
            .eq("user_id", user_id)
            .execute()
        )
    out: dict[str, Path] = {}
    for row in result.data or []:
        slug = row.get("name")
        pid = row.get("id")
        if not slug or not pid:
            continue
        d = projects_dir / user_id / slug
        if d.is_dir():
            out[pid] = d
    return out


@router.get("/projects")
def list_importable_projects(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Projects whose `direct` stage has prompts we can import."""
    projects_dir = get_projects_dir(request)
    out: list[dict[str, Any]] = []
    for pid, d in _user_project_dirs(projects_dir, user_id).items():
        direct = d / "direct"
        if not direct.is_dir():
            continue
        scene_dirs = [s for s in direct.iterdir() if s.is_dir()]
        if not scene_dirs:
            continue
        out.append({
            "id": pid,
            "name": d.name,
            "scene_count": len(scene_dirs),
        })
    return {"projects": out}


@router.get("/projects/{project_id}/scenes")
def list_project_scenes(
    project_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    projects_dir = get_projects_dir(request)
    proj_map = _user_project_dirs(projects_dir, user_id)
    d = proj_map.get(project_id)
    if d is None:
        raise HTTPException(404, "Project not found")

    direct = d / "direct"
    if not direct.is_dir():
        return {"scenes": []}

    scenes: list[dict[str, Any]] = []
    for scene_dir in sorted(direct.iterdir()):
        if not scene_dir.is_dir():
            continue
        prompts = artifacts.list_panel_prompts(d, scene_dir.name)
        if not prompts:
            continue
        from novel_to_comic.prompting import generate_distilled_prompt

        preview = prompts[0].distilled_prompt or generate_distilled_prompt(prompts[0])
        scenes.append({
            "scene_id": scene_dir.name,
            "panel_count": len(prompts),
            "first_prompt_preview": preview[:200],
        })
    return {"scenes": scenes}


@router.post("/projects/{project_id}/import-scene")
def import_project_scene(
    project_id: str,
    request: Request,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return up to 8 panels from a project scene as a labs-compatible payload."""
    projects_dir = get_projects_dir(request)
    proj_map = _user_project_dirs(projects_dir, user_id)
    d = proj_map.get(project_id)
    if d is None:
        raise HTTPException(404, "Project not found")

    scene_id = (body or {}).get("scene_id")
    if not scene_id:
        raise HTTPException(400, "scene_id required")

    panel_limit = int((body or {}).get("panel_limit", 8))
    panel_limit = max(1, min(MAX_PANELS, panel_limit))

    prompts = artifacts.list_panel_prompts(d, scene_id)
    if not prompts:
        raise HTTPException(404, f"No prompts found for scene {scene_id}")

    # Style template — pull from the project's config so the import is consistent
    # with how the project would render the panels.
    from novel_to_comic.config import load_config

    project_config, _ = load_config(d)
    style_template = project_config.style_template or prompts[0].style or ""

    selected_prompts = prompts[:panel_limit]
    refs_per_panel = _resolve_scene_panel_refs(d, project_config, selected_prompts)
    imported_references = _project_scene_reference_payload(
        project_id,
        d,
        refs_per_panel,
    )

    panels = []
    from novel_to_comic.prompting import generate_distilled_prompt, render_generation_prompt
    production_equivalent = bool((body or {}).get("production_equivalent"))
    production_requests: list[dict[str, Any] | None] = [None] * len(selected_prompts)
    if production_equivalent:
        from novel_to_comic.panel_generation import compile_panel_request
        from novel_to_comic.stages.s7_draw import _find_style_sample, build_panel_reference_plan

        for index, (p, panel_refs) in enumerate(zip(selected_prompts, refs_per_panel)):
            prompt_path = artifacts.panel_prompt_path(d, p.scene_id, p.panel_number)
            plan = build_panel_reference_plan(
                project_config,
                d,
                p,
                prompt_path=prompt_path if prompt_path.exists() else None,
                style_sample=_find_style_sample(d, project_config.style_template),
                scene_to_location={p.scene_id: next((s.location_id for s in artifacts.read_story_bible(d).scenes if s.id == p.scene_id), "")},
            )
            compiled = compile_panel_request(
                project_config,
                d,
                p,
                reference_plan=plan,
                prompt_path=prompt_path if prompt_path.exists() else None,
            )
            user_root = _user_labs_dir(projects_dir, user_id).resolve()
            portable_refs = tuple(
                replace(
                    reference,
                    source_path=str(Path(reference.source_path).resolve().relative_to(user_root)),
                )
                for reference in compiled.wire.references
            )
            portable_wire = replace(compiled.wire, references=portable_refs)
            production_requests[index] = {
                "execution_fingerprint": portable_wire.execution_fingerprint,
                "wire": portable_wire.to_json(),
            }

    image_model = project_config.effective_image_model()
    for i, (p, panel_refs) in enumerate(zip(selected_prompts, refs_per_panel), start=1):
        distilled_prompt = p.distilled_prompt or generate_distilled_prompt(p)
        production_prompt = render_generation_prompt(
            p, style_template, image_model, refs=panel_refs
        )
        if production_requests[i - 1] is not None:
            from novel_to_comic.provider_wire import ProviderWireRequest

            production_prompt = ProviderWireRequest.from_json(
                production_requests[i - 1]["wire"]
            ).prompt_parts[0]
        panels.append({
            "idx": i,
            "label": f"Panel {p.panel_number}" + (f" — {p.scene_id}" if p.scene_id else ""),
            "prompt": getattr(p, "visual_brief", None) or distilled_prompt,
            "prompt_variant_b": "",
            # Exact replay of what S7 sends for this panel (style + brief +
            # refs + constraints). Run it with an EMPTY experiment style
            # template — the style section is already embedded.
            "production_prompt": production_prompt,
            "width": p.width or 1024,
            "height": p.height or 1024,
            "production_equivalent": production_equivalent,
            "production_request": production_requests[i - 1],
            "production_source": {
                "project_id": project_id,
                "scene_id": p.scene_id,
                "panel_number": str(p.panel_number),
            } if production_equivalent else None,
        })

    return {
        "label": f"Project {d.name} · scene {scene_id}",
        "style_template": style_template,
        "panels": panels,
        "imported_references": imported_references,
        "imported_reference_paths": [str(ref["path"]) for ref in imported_references],
    }


def _resolve_scene_panel_refs(
    project_dir: Path,
    config,
    prompts: list[Any],
) -> list[list[Any]]:
    """Resolve draw-stage-equivalent refs per panel (parallel to prompts)."""
    from novel_to_comic.panel_generation import resolve_panel_references
    from novel_to_comic.stages.s7_draw import _find_style_sample

    scene_to_location: dict[str, str] = {}
    location_labels: dict[str, str] = {}
    if artifacts.story_bible_path(project_dir).exists():
        try:
            story_bible = artifacts.read_story_bible(project_dir)
            scene_to_location = {scene.id: scene.location_id for scene in story_bible.scenes}
            location_labels = {loc.id: loc.name for loc in story_bible.locations}
        except Exception:
            scene_to_location = {}

    style_sample = _find_style_sample(project_dir, config.style_template)
    refs_per_panel: list[list[Any]] = []
    for prompt in prompts:
        prompt_path = artifacts.panel_prompt_path(project_dir, prompt.scene_id, prompt.panel_number)
        output_dir = project_dir / "draw" / prompt.scene_id
        plan = resolve_panel_references(
            config,
            project_dir,
            prompt,
            prompt_path=prompt_path if prompt_path.exists() else None,
            style_sample=style_sample,
            scene_to_location=scene_to_location,
            location_labels=location_labels,
            output_dir=output_dir,
        )
        refs_per_panel.append(plan.to_ref_images())
    return refs_per_panel


def _project_scene_reference_payload(
    project_id: str,
    project_dir: Path,
    refs_per_panel: list[list[Any]],
) -> list[dict[str, str]]:
    """Return deduplicated reference-image payload entries for imported Labs scenes."""
    seen: set[Path] = set()
    refs: list[dict[str, str]] = []
    for panel_refs in refs_per_panel:
        for ref in panel_refs:
            path = ref.path.resolve()
            if path in seen or not path.is_file():
                continue
            try:
                rel = path.relative_to(project_dir.resolve())
            except ValueError:
                continue
            seen.add(path)
            refs.append({
                "path": str(path),
                "relative_path": rel.as_posix(),
                "label": (
                    f"{ref.role.replace('_', ' ')} · {ref.label}"
                    if ref.label
                    else f"{ref.role.replace('_', ' ')} · {rel.as_posix()}"
                ),
                "role": ref.role,
                "url": f"/api/projects/{project_id}/files/{rel.as_posix()}",
            })
    return refs


# ── Runs ───────────────────────────────────────────────────────────────────────


def _parse_run_body(body: dict) -> tuple[LabsRunSpec, list[str]]:
    """Validate & coerce a POST /runs body. Returns (spec, extra_ref_path_hints)."""
    label = (body.get("label") or "Untitled run").strip()[:MAX_LABEL_LEN]
    prompt_compare_mode = bool(body.get("prompt_compare_mode"))
    production_equivalent = bool(body.get("production_equivalent"))

    model_ids = body.get("model_ids") or []
    if not isinstance(model_ids, list) or not model_ids:
        raise HTTPException(400, "model_ids must be a non-empty list")
    if len(model_ids) > MAX_MODELS:
        raise HTTPException(400, f"At most {MAX_MODELS} models per run")
    if prompt_compare_mode and len(model_ids) != 1:
        raise HTTPException(400, "Prompt comparison mode requires exactly one model")
    for mid in model_ids:
        try:
            get_entry(str(mid))
        except KeyError:
            raise HTTPException(400, f"Unknown model id: {mid}")

    style_template = (body.get("style_template") or "").strip()[:MAX_STYLE_LEN]

    raw_panels = body.get("panels") or []
    if not isinstance(raw_panels, list) or not raw_panels:
        raise HTTPException(400, "panels must be a non-empty list")
    if len(raw_panels) > MAX_PANELS:
        raise HTTPException(400, f"At most {MAX_PANELS} panels per run")
    panels: list[LabsPanelSpec] = []
    for raw in raw_panels:
        if not isinstance(raw, dict):
            raise HTTPException(400, "Each panel must be an object")
        idx = int(raw.get("idx") or len(panels) + 1)
        prompt = (raw.get("prompt") or "").strip()[:MAX_PROMPT_LEN]
        if not prompt:
            raise HTTPException(400, f"Panel {idx} has empty prompt")
        prompt_variant_b = None
        if prompt_compare_mode:
            prompt_variant_b = (raw.get("prompt_variant_b") or "").strip()[:MAX_PROMPT_LEN]
            if not prompt_variant_b:
                raise HTTPException(400, f"Panel {idx} has empty prompt variant B")
        panels.append(LabsPanelSpec(
            idx=idx,
            label=str(raw.get("label") or f"Panel {idx}")[:MAX_LABEL_LEN],
            prompt=prompt,
            prompt_variant_b=prompt_variant_b,
            width=int(raw.get("width") or 1024),
            height=int(raw.get("height") or 1024),
            production_wire_json=(
                (raw.get("production_request") or {}).get("wire")
                if production_equivalent and isinstance(raw.get("production_request"), dict)
                else None
            ),
            experiment_inputs=dict(raw.get("experiment_inputs") or {}),
            production_source=(
                dict(raw.get("production_source") or {})
                if production_equivalent and isinstance(raw.get("production_source"), dict)
                else None
            ),
        ))

    ref_source = (body.get("reference_source") or "fixture").lower()
    extra_refs = body.get("reference_image_paths") or []
    if ref_source not in ("fixture", "imported", "none"):
        raise HTTPException(400, "reference_source must be 'fixture', 'imported', or 'none'")

    spec = LabsRunSpec(
        label=label,
        model_ids=[str(m) for m in model_ids],
        panels=panels,
        style_template=style_template,
        prompt_compare_mode=prompt_compare_mode,
        production_equivalent=production_equivalent,
    )
    return spec, [str(p) for p in extra_refs] if ref_source == "imported" else (
        [] if ref_source == "none" else ["__fixture__"]
    )


def _resolve_references(
    user_id: str,
    projects_dir: Path,
    hints: list[str],
) -> list[Path]:
    if not hints:
        return []
    if hints == ["__fixture__"]:
        return fixtures.reference_image_paths()
    out: list[Path] = []
    base = (projects_dir / user_id).resolve()
    for raw in hints:
        try:
            p = Path(raw).resolve()
        except (OSError, ValueError):
            continue
        # Confine imported references to the user's own project tree.
        try:
            p.relative_to(base)
        except ValueError:
            continue
        if p.is_file():
            out.append(p)
    return out


def _validated_production_panel_wire(
    *, user_id: str, projects_dir: Path, panel: LabsPanelSpec,
) -> str:
    """Recompile a server-owned source panel and reject client wire edits."""
    source = panel.production_source or {}
    project_id = source.get("project_id")
    scene_id = source.get("scene_id")
    panel_number = source.get("panel_number")
    project_dir = _user_project_dirs(projects_dir, user_id).get(project_id or "")
    if project_dir is None or not scene_id or not panel_number:
        raise HTTPException(400, "production-equivalent panel source is invalid")
    if scene_id != Path(scene_id).name or scene_id in {".", ".."}:
        raise HTTPException(400, "production-equivalent scene id is invalid")
    try:
        number = int(panel_number)
    except ValueError as exc:
        raise HTTPException(400, "production-equivalent panel number is invalid") from exc
    prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, number)
    if not prompt_path.is_file():
        raise HTTPException(400, "production-equivalent source panel is unavailable")
    from novel_to_comic.config import load_config
    from novel_to_comic.panel_generation import compile_panel_request
    from novel_to_comic.provider_wire import ProviderWireRequest
    from novel_to_comic.stages.s7_draw import _find_style_sample

    project_config, _ = load_config(project_dir)
    prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
    compiled = compile_panel_request(
        project_config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=_find_style_sample(project_dir, project_config.style_template),
    )
    received = ProviderWireRequest.from_json(panel.production_wire_json or "")
    if received.execution_fingerprint != compiled.wire.execution_fingerprint:
        raise HTTPException(400, "production-equivalent request no longer matches the project panel")
    user_root = _user_labs_dir(projects_dir, user_id).resolve()
    portable_refs = tuple(
        replace(
            reference,
            source_path=str(Path(reference.source_path).resolve().relative_to(user_root)),
        )
        for reference in compiled.wire.references
    )
    return replace(compiled.wire, references=portable_refs).to_json()


@router.post("/runs")
async def create_run(
    request: Request,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    spec, ref_hints = _parse_run_body(body)
    projects_dir = get_projects_dir(request)
    spec.reference_image_paths = _resolve_references(user_id, projects_dir, ref_hints)
    if spec.production_equivalent:
        for panel in spec.panels:
            panel.production_wire_json = _validated_production_panel_wire(
                user_id=user_id,
                projects_dir=projects_dir,
                panel=panel,
            )

    runs_state = _runs_state(request)
    user_root = _user_labs_dir(projects_dir, user_id)
    user_root.mkdir(parents=True, exist_ok=True)
    state = start_run(projects_dir=user_root, spec=spec, runs_state=runs_state)
    return state.to_public_dict()


@router.get("/runs")
def list_runs_endpoint(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    projects_dir = get_projects_dir(request)
    user_root = _user_labs_dir(projects_dir, user_id)
    return {"runs": labs_storage.list_runs(user_root)}


@router.get("/runs/{run_id}")
def get_run_endpoint(
    run_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> JSONResponse:
    projects_dir = get_projects_dir(request)
    user_root = _user_labs_dir(projects_dir, user_id)

    manifest = labs_storage.read_manifest(user_root, run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")

    in_memory = _runs_state(request).get(run_id)

    # Stitch per-cell results into a panels × models matrix.
    model_ids: list[str] = list(manifest.get("model_ids") or [])
    panels_meta = manifest.get("panels") or []
    prompt_compare_mode = bool(manifest.get("prompt_compare_mode"))
    panels_out: list[dict[str, Any]] = []
    total_cost_usd = 0.0
    for panel in panels_meta:
        idx = int(panel.get("idx") or 0)
        for variant in labs_storage.panel_variants(panel, prompt_compare_mode):
            prompt = panel.get("prompt_variant_b") if variant == "B" else panel.get("prompt")
            cells: dict[str, Any] = {}
            for mid in model_ids:
                meta = labs_storage.read_cell_meta(user_root, run_id, idx, mid, variant)
                if meta:
                    if meta.get("cost_usd") is not None:
                        try:
                            total_cost_usd += float(meta["cost_usd"])
                        except (TypeError, ValueError):
                            pass
                    if meta.get("status") == "ok":
                        meta = {
                            **meta,
                            "image_url": f"/api/labs/runs/{run_id}/cells/{idx}/{variant}/{mid}/image",
                        }
                    cells[mid] = meta
                else:
                    cells[mid] = {"status": "pending", "variant": variant}
            panels_out.append({
                "idx": idx,
                "variant": variant,
                "label": panel.get("label"),
                "prompt": prompt,
                "cells": cells,
            })

    payload = {
        "run_id": run_id,
        "label": manifest.get("label"),
        "status": (in_memory.status if in_memory else manifest.get("status")),
        "created_at": manifest.get("created_at"),
        "finished_at": manifest.get("finished_at"),
        "cells_total": manifest.get("cells_total"),
        "cells_done": in_memory.cells_done if in_memory else manifest.get("cells_done"),
        "total_cost_usd": total_cost_usd,
        "model_ids": model_ids,
        "style_template": manifest.get("style_template"),
        "prompt_compare_mode": prompt_compare_mode,
        "production_equivalent": bool(manifest.get("production_equivalent")),
        "reference_image_names": manifest.get("reference_image_names", []),
        "error": (in_memory.error if in_memory else manifest.get("error")),
        "panels": panels_out,
    }
    return JSONResponse(payload)


@router.delete("/runs/{run_id}")
async def delete_run_endpoint(
    run_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    if "/" in run_id or ".." in run_id:
        raise HTTPException(400, "Invalid run id")
    projects_dir = get_projects_dir(request)
    user_root = _user_labs_dir(projects_dir, user_id)

    in_memory = _runs_state(request).pop(run_id, None)
    task = in_memory.task if in_memory else None
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    if not labs_storage.delete_run(user_root, run_id):
        raise HTTPException(404, "Run not found")
    return {"status": "deleted", "run_id": run_id}


@router.get("/runs/{run_id}/cells/{panel_idx}/{variant}/{model_id}/image")
def get_cell_image(
    run_id: str,
    panel_idx: int,
    variant: str,
    model_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> FileResponse:
    if "/" in run_id or ".." in run_id or "/" in model_id or variant not in {"A", "B"}:
        raise HTTPException(400, "Invalid path component")
    projects_dir = get_projects_dir(request)
    user_root = _user_labs_dir(projects_dir, user_id)
    path = labs_storage.cell_image_path(user_root, run_id, panel_idx, model_id, variant)
    if not path.exists():
        raise HTTPException(404, "Cell image not found")
    return FileResponse(path, media_type="image/png")
