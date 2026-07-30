"""Standalone image-model experiments, independent of project artifacts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from novel_to_comic.labs import fixtures
from novel_to_comic.labs import storage as labs_storage
from novel_to_comic.labs.registry import get_entry, load_registry
from novel_to_comic.labs.runner import LabsPanelSpec, LabsRunSpec, LabsRunState, start_run

from ..auth import get_current_user
from ..deps import get_projects_dir

router = APIRouter()
MAX_IMAGES = 16
MAX_MODELS = 12


def _user_root(request: Request, user_id: str) -> Path:
    return get_projects_dir(request) / user_id


def _runs_state(request: Request) -> dict[str, LabsRunState]:
    state = getattr(request.app.state, "labs_runs", None)
    if state is None:
        state = {}
        request.app.state.labs_runs = state
    return state


@router.get("/models")
def list_models(user_id: str = Depends(get_current_user)) -> dict[str, Any]:  # noqa: ARG001
    return {"models": [model.to_public_dict() for model in load_registry() if model.enabled]}


@router.get("/fixtures/default")
def get_default_fixture(user_id: str = Depends(get_current_user)) -> dict[str, Any]:  # noqa: ARG001
    fixture = dict(fixtures.default_scene())
    fixture["reference_images"] = [
        {
            **reference,
            "url": f"/api/labs/fixtures/default/refs/{reference['filename']}",
        }
        for reference in fixture.get("reference_images", ())
        if isinstance(reference, dict) and reference.get("filename")
    ]
    return fixture


@router.get("/fixtures/default/refs/{filename}")
def get_default_fixture_ref(
    filename: str,
    user_id: str = Depends(get_current_user),  # noqa: ARG001
) -> FileResponse:
    if filename != Path(filename).name:
        raise HTTPException(400, "Invalid filename")
    path = fixtures.REFERENCE_IMAGES_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Reference image not found")
    return FileResponse(path, media_type="image/png")


def _parse_run(body: dict[str, Any]) -> LabsRunSpec:
    if body.get("production_equivalent"):
        raise HTTPException(
            400,
            "Project-pipeline replay was removed with the full-page backend cutover.",
        )
    model_ids = [str(value) for value in body.get("model_ids", ())]
    if not model_ids or len(model_ids) > MAX_MODELS:
        raise HTTPException(400, f"Choose between 1 and {MAX_MODELS} models")
    for model_id in model_ids:
        try:
            get_entry(model_id)
        except KeyError as exc:
            raise HTTPException(400, f"Unknown model id: {model_id}") from exc
    raw_images = body.get("panels") or body.get("images") or ()
    if not isinstance(raw_images, list) or not raw_images or len(raw_images) > MAX_IMAGES:
        raise HTTPException(400, f"Provide between 1 and {MAX_IMAGES} images")
    compare = bool(body.get("prompt_compare_mode"))
    if compare and len(model_ids) != 1:
        raise HTTPException(400, "Prompt comparison requires exactly one model")
    images: list[LabsPanelSpec] = []
    for index, raw in enumerate(raw_images, start=1):
        prompt = str(raw.get("prompt") or "").strip()
        alternate = str(raw.get("prompt_variant_b") or "").strip() or None
        if not prompt or (compare and alternate is None):
            raise HTTPException(400, f"Image {index} has an empty prompt")
        images.append(
            LabsPanelSpec(
                idx=int(raw.get("idx") or index),
                label=str(raw.get("label") or f"Image {index}")[:200],
                prompt=prompt[:4000],
                prompt_variant_b=alternate[:4000] if alternate else None,
                width=int(raw.get("width") or 1024),
                height=int(raw.get("height") or 1024),
            )
        )
    reference_source = str(body.get("reference_source") or "fixture")
    references = fixtures.reference_image_paths() if reference_source == "fixture" else []
    return LabsRunSpec(
        label=str(body.get("label") or "Untitled run")[:200],
        model_ids=model_ids,
        panels=images,
        style_template=str(body.get("style_template") or "")[:2000],
        prompt_compare_mode=compare,
        reference_image_paths=references,
    )


@router.post("/runs")
async def create_run(
    request: Request,
    body: dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    root = _user_root(request, user_id)
    root.mkdir(parents=True, exist_ok=True)
    state = start_run(
        projects_dir=root,
        spec=_parse_run(body),
        runs_state=_runs_state(request),
    )
    return state.to_public_dict()


@router.get("/runs")
def list_runs(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    return {"runs": labs_storage.list_runs(_user_root(request, user_id))}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> JSONResponse:
    root = _user_root(request, user_id)
    manifest = labs_storage.read_manifest(root, run_id)
    if manifest is None:
        raise HTTPException(404, "Run not found")
    state = _runs_state(request).get(run_id)
    manifest["status"] = state.status if state else manifest.get("status")
    manifest["cells_done"] = state.cells_done if state else manifest.get("cells_done")
    manifest["total_cost_usd"] = labs_storage.sum_run_cost(root, run_id)
    return JSONResponse(manifest)


@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    if run_id != Path(run_id).name:
        raise HTTPException(400, "Invalid run id")
    state = _runs_state(request).pop(run_id, None)
    if state and state.task and not state.task.done():
        state.task.cancel()
        await asyncio.gather(state.task, return_exceptions=True)
    if not labs_storage.delete_run(_user_root(request, user_id), run_id):
        raise HTTPException(404, "Run not found")
    return {"status": "deleted", "run_id": run_id}


@router.get("/runs/{run_id}/cells/{image_idx}/{variant}/{model_id}/image")
def get_cell_image(
    run_id: str,
    image_idx: int,
    variant: str,
    model_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> FileResponse:
    if run_id != Path(run_id).name or model_id != Path(model_id).name or variant not in {"A", "B"}:
        raise HTTPException(400, "Invalid path component")
    path = labs_storage.cell_image_path(
        _user_root(request, user_id),
        run_id,
        image_idx,
        model_id,
        variant,
    )
    if not path.exists():
        raise HTTPException(404, "Cell image not found")
    return FileResponse(path, media_type="image/png")
