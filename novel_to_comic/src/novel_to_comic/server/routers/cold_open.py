"""The Cold Open: the author's first pages, drawn while Extract reads on.

No route here spends credits: the job is admitted by orchestration when Extract
publishes the opening, and Canary pays for it. Costs are never shown.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from novel_to_comic import cold_open
from novel_to_comic.lettering.proof import LABEL_COPY, ProofCopy, render_style_proof
from novel_to_comic.lettering.service import project_lettering_mode, style_from_template
from novel_to_comic.stages.s2_style import proof_copy_for_sample
from novel_to_comic.style_contract import style_template_for_suggestion
from novel_to_comic.target_artifacts import TargetArtifacts
from ..auth import get_current_user
from ..deps import get_project, project_key
from ..file_cache import file_etag, not_modified, versioned_cache_control
from ..generation_jobs import find_active_generation_job
from ..product_events import capture_server_event

router = APIRouter()


@router.get("/cold-open")
def get_cold_open(project_id: str, request: Request, project=Depends(get_project),
                  user_id: str = Depends(get_current_user)):
    project_dir = project[0]
    record = cold_open.read_record(project_dir)
    if record is None:
        return {"cold_open": None}
    job = find_active_generation_job(request.app, project_key(user_id, project_id), "cold_open")
    # A stopped server never reruns paid work; it reports what was printed.
    interrupted = record.status == "printing" and job is None
    looks = []
    for entry in record.looks:
        status = "failed" if interrupted and entry.status in {"queued", "printing"} else entry.status
        path = cold_open.proof_path(project_dir, entry.id)
        looks.append({
            "id": entry.id, "label": entry.label, "medium": entry.medium, "status": status,
            "error": entry.error, "adopted": entry.id in record.adopted_look_ids,
            "image_url": (f"/api/projects/{project_id}/cold-open/proof/{entry.id}?v={file_etag(path).strip(chr(34))}"
                          if status == "ready" and path.exists() else None),
            # Series-relative, as image previews name their targets.
            "preview_target": f"cold_open/{path.name}",
        })
    return {"cold_open": {
        "status": "interrupted" if interrupted else record.status,
        "phase": job.payload.get("phase") if job is not None else None,
        "scene_title": record.scene_title, "scene_summary": record.scene_summary, "chapter": record.chapter,
        "story_copy": record.proof_copy is not None, "looks": looks,
        "favorite_look_id": record.favorite_look_id,
    }}


@router.get("/cold-open/proof/{look_id}")
def get_cold_open_proof(project_id: str, look_id: str, request: Request, project=Depends(get_project)):
    project_dir, config, _state = project
    record = cold_open.read_record(project_dir)
    look = cold_open.house_look(look_id)
    if record is None or look is None or not any(e.id == look_id and e.status == "ready" for e in record.looks):
        raise HTTPException(404, "This page isn't printed.")
    source = cold_open.proof_path(project_dir, look_id)
    if project_lettering_mode(TargetArtifacts(project_dir), config) == "integrated":
        # Integrated proofs draw their lettering into the image.
        etag = file_etag(source)
        cache = versioned_cache_control(request, etag.strip('"'))
        return not_modified(request, etag, cache) or Response(
            source.read_bytes(), media_type="image/png", headers={"Cache-Control": cache, "ETag": etag})
    copy = ProofCopy.model_validate(record.proof_copy) if record.proof_copy else LABEL_COPY
    style = style_from_template(style_template_for_suggestion(look.suggestion))
    data, identity = render_style_proof(TargetArtifacts(project_dir), style, source.read_bytes(),
                                        proof_copy_for_sample(copy, source))
    cache = versioned_cache_control(request, identity)
    return not_modified(request, f'"{identity}"', cache) or Response(
        data, media_type="image/png", headers={"Cache-Control": cache, "ETag": f'"{identity}"'})


@router.post("/cold-open/adopt", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def adopt_cold_open(project_id: str, project=Depends(get_project), user_id: str = Depends(get_current_user)):
    """Bring the first pages into an empty Look as its proofs. Free; selects nothing."""
    from ..cold_open_jobs import adopt_first_pages

    project_dir, config, _state = project
    if cold_open.read_record(project_dir) is None:
        raise HTTPException(404, "This project has no Cold Open.")
    adopted = adopt_first_pages(project_dir, config)
    if adopted:
        capture_server_event("cold_open_adopted", user_id=user_id, project_id=project_id,
                             properties={"pages": len(adopted)})
    return {"adopted": adopted}


class FavoriteBody(BaseModel):
    look_id: str | None


@router.post("/cold-open/favorite", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def set_cold_open_favorite(project_id: str, body: FavoriteBody, project=Depends(get_project),
                           user_id: str = Depends(get_current_user)):
    """Remember the look the author liked. A preference for Style, never a selection."""
    from ..cold_open_jobs import _mutate

    project_dir = project[0]
    record = cold_open.read_record(project_dir)
    if record is None:
        raise HTTPException(404, "This project has no Cold Open.")
    if body.look_id is not None and not any(e.id == body.look_id and e.status == "ready" for e in record.looks):
        raise HTTPException(400, "Choose a printed page.")

    def change(current):
        current.favorite_look_id = body.look_id
    _mutate(project_dir, change)
    capture_server_event("cold_open_favorite", user_id=user_id, project_id=project_id,
                         properties={"look_id": body.look_id})
    return {"favorite_look_id": body.look_id}
