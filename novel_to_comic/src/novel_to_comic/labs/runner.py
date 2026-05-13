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
from .providers.fal import FalProvider
from .providers.litellm import LitellmProvider
from .providers.together import TogetherProvider
from .registry import LabsModelEntry, get_entry

log = logging.getLogger(__name__)

# Limit per-provider concurrency so we don't hammer fal/together with a wall
# of requests when running 8 panels × 6 models.
_PER_PROVIDER_CONCURRENCY = 3


def _build_provider(name: str) -> LabsProvider:
    if name == "fal":
        return FalProvider()
    if name == "together":
        return TogetherProvider()
    if name == "litellm":
        return LitellmProvider()
    raise ValueError(f"Unknown provider: {name}")


@dataclass
class LabsPanelSpec:
    """One panel in a labs run."""

    idx: int
    label: str
    prompt: str
    width: int = 1024
    height: int = 1024


@dataclass
class LabsRunSpec:
    """All inputs needed to execute one labs run."""

    label: str
    model_ids: list[str]
    panels: list[LabsPanelSpec]
    style_template: str = ""
    reference_image_paths: list[Path] = field(default_factory=list)


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
            "error": self.error,
        }


async def _run_cell(
    projects_dir: Path,
    state: LabsRunState,
    entry: LabsModelEntry,
    panel: LabsPanelSpec,
    semaphore: asyncio.Semaphore,
) -> None:
    provider = _build_provider(entry.provider)
    refs = list(state.spec.reference_image_paths)
    if entry.max_refs and entry.max_refs > 0:
        refs = refs[: entry.max_refs]
    elif not entry.multi_ref and refs:
        refs = refs[:1] if entry.multi_ref or entry.style_refs else []

    inp = LabsImageInput(
        prompt=panel.prompt,
        style_template=state.spec.style_template,
        width=panel.width,
        height=panel.height,
        reference_image_paths=refs,
    )

    started = datetime.now(UTC)
    try:
        async with semaphore:
            result = await provider.generate(endpoint=entry.endpoint, inp=inp, params=entry.params)
        cost = settle_labs_result_cost(entry, inp, result)
        storage.write_cell(
            projects_dir,
            state.run_id,
            panel.idx,
            entry.id,
            image_bytes=result.image_bytes,
            meta={
                "model_id": entry.id,
                "panel_idx": panel.idx,
                "status": "ok",
                "latency_ms": result.latency_ms,
                "cost_usd": cost.cost_usd,
                "cost_source": cost.source,
                "provider_model": cost.provider_model,
                "pricing_snapshot": cost.pricing_snapshot,
                "mime": result.mime,
                "provider_request_id": result.provider_request_id,
                "started_at": started.isoformat(),
            },
        )
    except (ProviderError, Exception) as exc:
        log.warning("labs cell failed: model=%s panel=%s err=%s", entry.id, panel.idx, exc)
        storage.write_cell(
            projects_dir,
            state.run_id,
            panel.idx,
            entry.id,
            image_bytes=None,
            meta={
                "model_id": entry.id,
                "panel_idx": panel.idx,
                "status": "failed",
                "error": str(exc),
                "started_at": started.isoformat(),
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
                tasks.append(asyncio.create_task(_run_cell(projects_dir, state, entry, panel, sem)))
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
        reference_image_paths=staged_refs,
    )
    cells_total = len(spec.model_ids) * len(spec.panels)
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
        "reference_image_names": [p.name for p in staged_refs],
        "panels": [
            {
                "idx": p.idx,
                "label": p.label,
                "prompt": p.prompt,
                "width": p.width,
                "height": p.height,
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
