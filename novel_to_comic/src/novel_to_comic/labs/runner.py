"""Async runner: executes every (panel × model) cell concurrently."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .costs import settle_labs_result_cost
from . import storage
from .providers.base import LabsImageInput, LabsProvider, ProviderError
from .providers.litellm import LitellmProvider
from .registry import LabsModelEntry, get_entry

log = logging.getLogger(__name__)

# Bound local comparison concurrency.
_PER_PROVIDER_CONCURRENCY = 3


def _build_provider(name: str) -> LabsProvider:
    if name == "litellm":
        return LitellmProvider()
    raise ValueError(f"Unknown provider: {name}")


@dataclass
class LabsPanelSpec:
    """One panel in a labs run."""

    idx: int
    label: str
    prompt: str
    prompt_variant_b: str | None = None
    width: int = 1024
    height: int = 1024
    production_wire_json: str | None = None
    experiment_inputs: dict[str, Any] = field(default_factory=dict)
    production_source: dict[str, str] | None = None


@dataclass
class LabsRunSpec:
    """All inputs needed to execute one labs run."""

    label: str
    model_ids: list[str]
    panels: list[LabsPanelSpec]
    style_template: str = ""
    prompt_compare_mode: bool = False
    reference_image_paths: list[Path] = field(default_factory=list)
    production_equivalent: bool = False


@dataclass
class LabsRunState:
    run_id: str
    spec: LabsRunSpec
    started_at: datetime
    status: str = "running"  # running | complete | failed | cancelled
    cells_done: int = 0
    cells_total: int = 0
    finished_at: datetime | None = None
    error: str | None = None
    task: asyncio.Task[None] | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "label": self.spec.label,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "cells_done": self.cells_done,
            "cells_total": self.cells_total,
            "model_ids": list(self.spec.model_ids),
            "panel_count": len(self.spec.panels),
            "production_equivalent": self.spec.production_equivalent,
            "error": self.error,
        }


async def _run_cell(
    projects_dir: Path,
    state: LabsRunState,
    entry: LabsModelEntry,
    panel: LabsPanelSpec,
    variant: str,
    prompt: str,
    semaphore: asyncio.Semaphore,
) -> None:
    provider = _build_provider(entry.provider)
    refs = list(state.spec.reference_image_paths)
    if entry.max_refs and entry.max_refs > 0:
        refs = refs[: entry.max_refs]
    elif not entry.multi_ref and refs:
        refs = refs[:1] if entry.multi_ref or entry.style_refs else []

    inp = LabsImageInput(
        prompt=prompt,
        style_template=state.spec.style_template,
        width=panel.width,
        height=panel.height,
        reference_image_paths=refs,
    )

    experimental_wire = None
    experimental_plan = None
    if entry.provider == "litellm":
        from novel_to_comic.generation_input import GenerationPromptInput
        from novel_to_comic.image_references import AuthorityScope, ReferenceAsset
        from novel_to_comic.asset_generation import (
            AssetGenerationInput,
            compile_non_panel_request,
            reference_plan_for_assets,
        )
        from novel_to_comic.image_geometry import generation_shape_for_aspect
        from .providers.litellm import _config_for_model

        reference_roles = list(inp.extra.get("reference_roles") or [])
        assets = []
        for index, path in enumerate(refs):
            role = reference_roles[index] if index < len(reference_roles) else "subject"
            content_sha256 = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            assets.append(ReferenceAsset(
                path=path, role=role, entity_id=None, appearance_state_id=None,
                authority_scope=AuthorityScope.CONTEXTUAL,
                preserve_facets=(), ignore_facets=(), pose=None,
                content_sha256=content_sha256, lineage_parent_sha256=None,
                label=f"reference {index}",
            ))
        wire_alias = entry.endpoint
        wire_config = _config_for_model(wire_alias)
        experimental_input = AssetGenerationInput(
            asset_kind="labs_image",
            asset_identity=f"labs:{state.run_id}:image:{panel.idx}:{variant}",
            prompt=GenerationPromptInput(
                visual_brief=inp.prompt,
                width=inp.width,
                height=inp.height,
                generation_width=inp.width,
                generation_height=inp.height,
                generation_shape=generation_shape_for_aspect(inp.width / inp.height),
            ),
            selected_style_text=inp.style_template,
        )
        experimental_plan = reference_plan_for_assets(wire_config, assets)
        experimental_request = compile_non_panel_request(
            wire_config, experimental_input, reference_plan=experimental_plan,
        )
        experimental_wire = experimental_request.wire
        inp.extra["provider_wire_json"] = experimental_wire.to_json()

    started = datetime.now(UTC)
    try:
        async with semaphore:
            result = await provider.generate(
                endpoint=entry.endpoint, inp=inp, params=entry.params
            )
        cost = settle_labs_result_cost(entry, inp, result)
        provenance = None
        if experimental_wire is not None:
            from novel_to_comic.image_provenance import common_image_provenance

            provenance = common_image_provenance(
                asset_kind="labs_image",
                asset_identity=f"labs:{state.run_id}:image:{panel.idx}:{variant}",
                compiled_sha256=experimental_wire.compiled_request_sha256,
                prompt_source_sha256=None,
                wire=experimental_wire,
                reference_plan=experimental_plan,
                request_id=None,
                actual_provider_model=result.provider_model,
                provider_request_id=result.provider_request_id,
                latency_ms=result.latency_ms,
                cost_usd=cost.cost_usd,
                project_dir=projects_dir,
            )
        storage.write_cell(
            projects_dir,
            state.run_id,
            panel.idx,
            entry.id,
            variant=variant,
            image_bytes=result.image_bytes,
            meta={
                "model_id": entry.id,
                "panel_idx": panel.idx,
                "variant": variant,
                "prompt": prompt,
                "status": "ok",
                "latency_ms": result.latency_ms,
                "cost_usd": cost.cost_usd,
                "cost_source": cost.source,
                "provider_model": cost.provider_model,
                "pricing_snapshot": cost.pricing_snapshot,
                "mime": result.mime,
                "provider_request_id": result.provider_request_id,
                "started_at": started.isoformat(),
                "production_equivalent": False,
                "execution_fingerprint": (
                    experimental_wire.execution_fingerprint if experimental_wire else None
                ),
                "provenance": provenance,
            },
        )
    except (ProviderError, Exception) as exc:
        log.warning("labs cell failed: model=%s panel=%s err=%s", entry.id, panel.idx, exc)
        failure_provenance = None
        if experimental_wire is not None:
            from novel_to_comic.image_provenance import common_image_provenance

            failure_provenance = common_image_provenance(
                asset_kind="labs_image",
                asset_identity=f"labs:{state.run_id}:image:{panel.idx}:{variant}",
                compiled_sha256=experimental_wire.compiled_request_sha256,
                prompt_source_sha256=None,
                wire=experimental_wire,
                reference_plan=experimental_plan,
                request_id=None,
                failure={"type": type(exc).__name__, "message": str(exc)},
                project_dir=projects_dir,
            )
        storage.write_cell(
            projects_dir,
            state.run_id,
            panel.idx,
            entry.id,
            variant=variant,
            image_bytes=None,
            meta={
                "model_id": entry.id,
                "panel_idx": panel.idx,
                "variant": variant,
                "prompt": prompt,
                "status": "failed",
                "error": str(exc),
                "started_at": started.isoformat(),
                "production_equivalent": False,
                "execution_fingerprint": (
                    experimental_wire.execution_fingerprint if experimental_wire else None
                ),
                "provenance": failure_provenance,
            },
        )
    finally:
        state.cells_done += 1


async def _run_all(projects_dir: Path, state: LabsRunState) -> None:
    """Execute all (model × panel) cells. Per-provider semaphores cap parallelism."""
    semaphores: dict[str, asyncio.Semaphore] = {}
    tasks: list[asyncio.Task[None]] = []
    try:
        for model_id in state.spec.model_ids:
            try:
                entry = get_entry(model_id)
            except KeyError as exc:
                log.warning("labs: skipping unknown model id %s (%s)", model_id, exc)
                continue
            sem = semaphores.setdefault(entry.provider, asyncio.Semaphore(_PER_PROVIDER_CONCURRENCY))
            for panel in state.spec.panels:
                for variant, prompt in _panel_variants(state.spec, panel):
                    tasks.append(asyncio.create_task(_run_cell(projects_dir, state, entry, panel, variant, prompt, sem)))
        if not tasks:
            state.status = "failed"
            state.error = "No valid models in run spec"
            return
        await asyncio.gather(*tasks, return_exceptions=False)
        state.status = "complete"
    except asyncio.CancelledError:
        state.status = "cancelled"
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    except Exception as exc:
        log.exception("labs run %s crashed", state.run_id)
        state.status = "failed"
        state.error = str(exc)
    finally:
        state.finished_at = datetime.now(UTC)
        manifest = storage.read_manifest(projects_dir, state.run_id) or {}
        manifest["status"] = state.status
        manifest["cells_done"] = state.cells_done
        manifest["finished_at"] = state.finished_at.isoformat()
        manifest["total_cost_usd"] = storage.sum_run_cost(projects_dir, state.run_id)
        if state.error:
            manifest["error"] = state.error
        storage.write_manifest(projects_dir, state.run_id, manifest)


def start_run(
    *,
    projects_dir: Path,
    spec: LabsRunSpec,
    runs_state: dict[str, LabsRunState],
) -> LabsRunState:
    """Spin up an async run. Returns the registered state immediately."""
    run_id = uuid.uuid4().hex[:12]
    staged_refs = storage.stage_reference_images(projects_dir, run_id, spec.reference_image_paths)
    spec = LabsRunSpec(
        label=spec.label,
        model_ids=spec.model_ids,
        panels=spec.panels,
        style_template=spec.style_template,
        prompt_compare_mode=spec.prompt_compare_mode,
        reference_image_paths=staged_refs,
        production_equivalent=spec.production_equivalent,
    )
    cells_total = len(spec.model_ids) * sum(len(_panel_variants(spec, p)) for p in spec.panels)
    started_at = datetime.now(UTC)
    state = LabsRunState(
        run_id=run_id,
        spec=spec,
        started_at=started_at,
        cells_total=cells_total,
    )
    manifest = {
        "run_id": run_id,
        "label": spec.label,
        "created_at": started_at.isoformat(),
        "model_ids": list(spec.model_ids),
        "style_template": spec.style_template,
        "prompt_compare_mode": spec.prompt_compare_mode,
        "production_equivalent": spec.production_equivalent,
        "reference_image_names": [p.name for p in staged_refs],
        "panels": [
            {
                "idx": p.idx,
                "label": p.label,
                "prompt": p.prompt,
                "prompt_variant_b": p.prompt_variant_b,
                "width": p.width,
                "height": p.height,
                "production_wire": p.production_wire_json,
                "experiment_inputs": p.experiment_inputs,
            }
            for p in spec.panels
        ],
        "status": "running",
        "cells_total": cells_total,
        "cells_done": 0,
    }
    storage.write_manifest(projects_dir, run_id, manifest)
    runs_state[run_id] = state
    state.task = asyncio.create_task(_run_all(projects_dir, state))
    return state


def _panel_variants(spec: LabsRunSpec, panel: LabsPanelSpec) -> list[tuple[str, str]]:
    if spec.prompt_compare_mode and panel.prompt_variant_b:
        return [("A", panel.prompt), ("B", panel.prompt_variant_b)]
    return [("A", panel.prompt)]
