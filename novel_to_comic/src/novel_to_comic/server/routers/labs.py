"""Labs — image-model experimentation endpoints.

Top-level (`/api/labs/...`) rather than project-scoped because the labs page is
a standalone tool. Runs are stored per-user under `{projects_dir}/{user_id}/_labs/`.
"""

from __future__ import annotations

import logging
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
        scenes.append({
            "scene_id": scene_dir.name,
            "panel_count": len(prompts),
            "first_prompt_preview": (prompts[0].full_prompt or "")[:200],
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

    # Resolve absolute paths to any reference images already attached to the prompts.
    seen_refs: list[Path] = []
    for p in prompts[:panel_limit]:
        for rel in p.reference_image_paths or []:
            abs_path = (d / rel).resolve() if not Path(rel).is_absolute() else Path(rel)
            if abs_path.exists() and abs_path not in seen_refs:
                seen_refs.append(abs_path)
            if len(seen_refs) >= 8:
                break

    panels = []
    for i, p in enumerate(prompts[:panel_limit], start=1):
        panels.append({
            "idx": i,
            "label": f"Panel {p.panel_number}" + (f" — {p.scene_id}" if p.scene_id else ""),
            "prompt": p.full_prompt or "",
            "width": p.width or 1024,
            "height": p.height or 1024,
        })

    return {
        "label": f"Project {d.name} · scene {scene_id}",
        "style_template": style_template,
        "panels": panels,
        "imported_reference_paths": [str(p) for p in seen_refs],
    }


# ── Runs ───────────────────────────────────────────────────────────────────────


def _parse_run_body(body: dict) -> tuple[LabsRunSpec, list[str]]:
    """Validate & coerce a POST /runs body. Returns (spec, extra_ref_path_hints)."""
    label = (body.get("label") or "Untitled run").strip()[:MAX_LABEL_LEN]

    model_ids = body.get("model_ids") or []
    if not isinstance(model_ids, list) or not model_ids:
        raise HTTPException(400, "model_ids must be a non-empty list")
    if len(model_ids) > MAX_MODELS:
        raise HTTPException(400, f"At most {MAX_MODELS} models per run")
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
        panels.append(LabsPanelSpec(
            idx=idx,
            label=str(raw.get("label") or f"Panel {idx}")[:MAX_LABEL_LEN],
            prompt=prompt,
            width=int(raw.get("width") or 1024),
            height=int(raw.get("height") or 1024),
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


@router.post("/runs")
async def create_run(
    request: Request,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    spec, ref_hints = _parse_run_body(body)
    projects_dir = get_projects_dir(request)
    spec.reference_image_paths = _resolve_references(user_id, projects_dir, ref_hints)

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
    panels_out: list[dict[str, Any]] = []
    total_cost_usd = 0.0
    for panel in panels_meta:
        idx = int(panel.get("idx") or 0)
        cells: dict[str, Any] = {}
        for mid in model_ids:
            meta = labs_storage.read_cell_meta(user_root, run_id, idx, mid)
            if meta:
                if meta.get("cost_usd") is not None:
                    try:
                        total_cost_usd += float(meta["cost_usd"])
                    except (TypeError, ValueError):
                        pass
                if meta.get("status") == "ok":
                    meta = {
                        **meta,
                        "image_url": f"/api/labs/runs/{run_id}/cells/{idx}/{mid}/image",
                    }
                cells[mid] = meta
            else:
                cells[mid] = {"status": "pending"}
        panels_out.append({
            "idx": idx,
            "label": panel.get("label"),
            "prompt": panel.get("prompt"),
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
        "reference_image_names": manifest.get("reference_image_names", []),
        "error": (in_memory.error if in_memory else manifest.get("error")),
        "panels": panels_out,
    }
    return JSONResponse(payload)


@router.get("/runs/{run_id}/cells/{panel_idx}/{model_id}/image")
def get_cell_image(
    run_id: str,
    panel_idx: int,
    model_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> FileResponse:
    if "/" in run_id or ".." in run_id or "/" in model_id:
        raise HTTPException(400, "Invalid path component")
    projects_dir = get_projects_dir(request)
    user_root = _user_labs_dir(projects_dir, user_id)
    path = labs_storage.cell_image_path(user_root, run_id, panel_idx, model_id)
    if not path.exists():
        raise HTTPException(404, "Cell image not found")
    return FileResponse(path, media_type="image/png")
