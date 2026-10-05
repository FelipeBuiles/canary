"""Style suggestion, sample generation, and active style selection."""

import asyncio
import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Literal
from fastapi.responses import Response
from novel_to_comic.lettering.proof import render_style_proof

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from novel_to_comic import artifacts
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.uploaded_images import (
    IMAGE_SUFFIXES, MAX_IMAGE_BYTES, UploadedImageError, decode_uploaded_image, image_suffix,
)
from novel_to_comic.target_artifacts import TargetArtifacts, ArtifactMissing
from novel_to_comic.lettering.service import style_from_template, project_lettering_mode
from novel_to_comic.ai import ai_request_context
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.config import Config, mock_mode_active, save_config
from novel_to_comic.codex_dev import CodexRoutingError, classify_operations, is_subscription
from ..codex_admission import image_operations, prompt_image_operations, style_sample_operations
from novel_to_comic.image_models import image_model_profile_for_config
from novel_to_comic.image_geometry import style_proof_dimensions
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.asset_generation import asset_matches_request
from novel_to_comic.style_contract import (
    page_style_template,
    style_template_for_suggestion,
)
from novel_to_comic.state import (
    StageState, StageStatus, begin_stage, complete_stage, fail_stage, record_item_done, save_state, load_state,
)
from novel_to_comic.stages import REGISTRY
from novel_to_comic.stages.s2_style import (
    SAMPLE_COUNT,
    NEIGHBOR_COUNT,
    STYLE_VALIDATION_ACTION,
    STYLE_VALIDATION_COMPOSITION,
    ensure_style_sample_brief,
    generate_sample_image,
    generate_samples_for_indices,
    generate_suggestions,
    proof_copy_for_sample,
    style_proof_copy,
    custom_direction_candidate,
    describe_custom_direction,
    estimate_custom_direction_naming_cost_usd,
    update_suggestion_fields,
    DISPLAY_LABEL_MAX_CHARS,
    build_style_sample_request,
    load_style_direction,
    load_suggestions,
    missing_sample_indices,
    sample_takes_software_lettering,
    save_suggestions,
    style_direction_image,
    estimate_style_proof_cost_usd,
    style_validation_brief,
    estimate_style_batch_cost_usd,
    suggestion_index_by_id,
)
from novel_to_comic.usage import estimate_image_cost

from ..auth import get_current_user
from ..credits import (
    assert_sufficient_credits,
    credit_estimate_for_provider_cost,
    release_reservation,
    reserve_credits,
)
from ..credited_job import enqueue_reserved_generation_job
from ..event_channel import EventChannel
from ..db import get_db
from ..deps import get_project, project_key
from ..job_commands import command
from ..generation_jobs import (
    find_active_generation_job,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
)
from ..product_events import capture_server_event

router = APIRouter()
logger = logging.getLogger("canary.styles")
_STYLE_IMAGE_TYPES = IMAGE_SUFFIXES
_MAX_STYLE_REFERENCE_BYTES = MAX_IMAGE_BYTES
_MAX_STYLE_MULTIPART_BYTES = _MAX_STYLE_REFERENCE_BYTES + 1024 * 1024


def is_style_selected(project_dir, config) -> bool:
    """Check whether an active style has been selected for this project."""
    active = page_style_template(config.style_template)
    return any(
        style_template_for_suggestion(s) == active
        for s in load_suggestions(project_dir)
    )


def _active_suggestion(suggestions: list[dict], config: Config) -> tuple[int | None, str | None]:
    active = page_style_template(config.style_template)
    for index, suggestion in enumerate(suggestions, 1):
        if style_template_for_suggestion(suggestion) == active:
            return index, suggestion.get("id")
    return None, None


def _proof_style(project_dir: Path, suggestion: dict, *, active: bool):
    if active:
        try:
            return TargetArtifacts(project_dir).read_lettering_style()
        except ArtifactMissing:
            pass
    return style_from_template(style_template_for_suggestion(suggestion))


def clear_style_failures_after_selection(state) -> bool:
    """Finalize Style when the user has explicitly selected a usable sample.

    A batch can fail after producing a sample the user can select (for example
    if earlier requests used an unavailable provider route). Selection is the
    Style checkpoint approval, so that selected, usable sample must unblock
    Cast even when the batch's last terminal status was ``failed``.
    """
    style_state = state.stages["style"]
    if style_state.status not in (
        StageStatus.COMPLETE,
        StageStatus.AWAITING_REVIEW,
        StageStatus.FAILED,
    ):
        return False
    changed = False
    if style_state.items_failed:
        style_state.items_failed = []
        changed = True
    if style_state.status != StageStatus.COMPLETE:
        # Style selection is the explicit checkpoint approval; do not leave
        # its lifecycle in awaiting_review or failed after it is approved.
        style_state.status = StageStatus.COMPLETE
        changed = True
    if style_state.error is not None:
        style_state.error = None
        changed = True
    if style_state.error_detail is not None:
        style_state.error_detail = None
        changed = True
    if style_state.error_code is not None:
        style_state.error_code = None
        changed = True
    if style_state.balance_credits is not None:
        style_state.balance_credits = None
        changed = True
    if style_state.required_credits is not None:
        style_state.required_credits = None
        changed = True
    if style_state.shortfall_credits is not None:
        style_state.shortfall_credits = None
        changed = True
    return changed


def _get_bible(project_dir):
    path = artifacts.story_bible_path(project_dir)
    if not path.exists():
        return None
    return StoryBible.model_validate_json(path.read_text())


def _suggest_batch_credit_estimate(
    config: Config,
    project_dir,
    sample_count: int = SAMPLE_COUNT,
    *,
    has_style_reference: bool = False,
    reference_size: tuple[int, int] | None = None,
) -> dict:
    funding = classify_operations(prompt_image_operations(config))
    if is_subscription(funding):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=True, funding=funding))
    if mock_mode_active(config):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=True))
    cost_usd = estimate_style_batch_cost_usd(
        config, project_dir, sample_count,
        has_style_reference=has_style_reference,
        reference_size=reference_size,
    )
    return dict(credit_estimate_for_provider_cost(cost_usd, "style", reserve=True))


def _style_sample_credit_estimate(
    config: Config,
    *,
    reserve: bool = False,
    has_style_reference: bool = False,
    exact_cost_usd: float | None = None,
    validation: bool = False,
) -> dict:
    """Keep one-sample preflight and generation credit checks in lockstep."""
    funding = classify_operations(style_sample_operations(config, validation=validation))
    if is_subscription(funding):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=reserve, funding=funding))
    if mock_mode_active(config):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=reserve))
    if exact_cost_usd is None:
        width, height = style_proof_dimensions()
        cost_kwargs = {
            "quality": getattr(config, "image_quality", None),
            "width": width, "height": height,
        }
        if has_style_reference and _supports_style_reference(config):
            cost_kwargs["ref_count"] = 1
        exact_cost_usd = estimate_image_cost(
            config.effective_image_model(), 1,
            **cost_kwargs,
        )
    return dict(credit_estimate_for_provider_cost(
        exact_cost_usd, "style", reserve=reserve, zero_cost_estimate=1,
    ))


def _direction_operations(config: Config, *, with_neighbors: bool = False):
    """A faithful direction proof is followed by one vision call that names it."""
    base = prompt_image_operations(config) if with_neighbors else style_sample_operations(config)
    return (*base, ("text", config.effective_visual_review_model()))


def _direction_credit_estimates(
    config: Config,
    project_dir,
    *,
    has_style_reference: bool = False,
    template: str | None = None,
    candidate_id: str = "direction_estimate",
    reference_size: tuple[int, int] | None = None,
) -> dict:
    def quote(operations, cost, *, zero_cost_estimate=1):
        try:
            funding = classify_operations(operations)
        except CodexRoutingError as exc:
            return {"supported": False, "error": str(exc)}
        return dict(credit_estimate_for_provider_cost(
            0.0 if is_subscription(funding) or mock_mode_active(config) else cost(),
            "style", reserve=True,
            zero_cost_estimate=0 if mock_mode_active(config) else zero_cost_estimate,
            funding=funding,
        ))

    reference_count = 1 if has_style_reference and _supports_style_reference(config) else 0
    bible = _get_bible(project_dir)

    def faithful_cost():
        width, height = style_proof_dimensions()
        naming = estimate_custom_direction_naming_cost_usd(
            config, bible.title if bible is not None else "", template or "",
        )
        return naming + (
            estimate_style_proof_cost_usd(
                config, project_dir, bible, template or config.style_template, candidate_id,
                reference_size=(reference_size or (1024, 1024)) if reference_count else None,
            )
            if bible is not None
            else estimate_image_cost(
                config.effective_image_model(), 1,
                quality=getattr(config, "image_quality", None),
                width=width, height=height,
                ref_count=reference_count,
                ref_image_sizes=[reference_size or (1024, 1024)] if reference_count else None,
            )
        )

    def neighbor_cost():
        return estimate_style_batch_cost_usd(
            config, project_dir, NEIGHBOR_COUNT, has_style_reference=bool(reference_count),
            reference_size=reference_size,
        )

    return {
        "faithful": quote(_direction_operations(config), faithful_cost),
        "neighbors": quote(prompt_image_operations(config), neighbor_cost, zero_cost_estimate=0),
        "faithful_with_neighbors": quote(
            _direction_operations(config, with_neighbors=True), lambda: faithful_cost() + neighbor_cost(),
        ),
    }


def _supports_style_reference(config: Config) -> bool:
    return "style" in image_model_profile_for_config(config).supported_roles


def _reference_image_size(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError):
        return None


def _assert_usable_style_direction(config: Config, text: str, has_image: bool) -> None:
    if has_image and not text and not _supports_style_reference(config):
        raise HTTPException(
            400,
            "This image model cannot use a style reference. Add a text direction or choose "
            "an image model that supports style references.",
        )


def _assert_no_pipeline_task(request: Request, pkey: str) -> None:
    existing = request.app.state.running_tasks.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A stage is already running for this project")


def _assert_no_style_task(request: Request, pkey: str) -> None:
    existing = request.app.state.style_tasks.get(pkey)
    if existing and not existing.done():
        raise HTTPException(409, "A style operation is already running for this project")


@router.get("/styles")
def get_styles(project_id: str, project=Depends(get_project), request: Request = None, user_id: str = Depends(get_current_user)):
    project_dir, config, _state = project
    suggestions = load_suggestions(project_dir)
    bible = _get_bible(project_dir)
    stale_indices = set(missing_sample_indices(
        project_dir, suggestions, config=config, bible=bible,
    )) if bible else set()

    active_index, active_id = _active_suggestion(suggestions, config)
    editable = project_lettering_mode(TargetArtifacts(project_dir), config) == "editable"
    proof_states = {}
    active_style_jobs = []
    batch_jobs = []
    if request is not None:
        from ..generation_jobs import recovered_generation_jobs
        pkey = project_key(user_id, project_id)
        jobs = recovered_generation_jobs(request.app, pkey) + [
            generation_job_payload(request.app, job) for job in request.app.state.generation_jobs.values()
            if job.project_name == pkey and job.kind in {"style_sample", "style_suggest"}]
        for job in sorted(jobs, key=lambda item: item.get("queued_at") or ""):
            if job["kind"] not in {"style_sample", "style_suggest"}:
                continue
            if job["status"] in {"queued", "running"}:
                active_style_jobs.append(job)
                if job["kind"] == "style_suggest" or job.get("payload", {}).get("with_neighbors"):
                    batch_jobs.append(job)
            payload = job.get("payload", {})
            proofs = payload.get("proofs", {})
            if payload.get("index") is not None and not proofs:
                proofs = {str(payload["index"]): {"status": job["status"]}}
            for index, proof in proofs.items():
                status = proof["status"]
                if status in {"queued", "running"} and job["status"] == "failed":
                    status = "failed"
                proof_states[int(index)] = status

    result = []
    for i, s in enumerate(suggestions, 1):
        sample_path = artifacts.style_sample_path(project_dir, i)
        sample_exists = sample_path.exists()
        validation_path = artifacts.style_validation_path(project_dir, s["id"])
        direction = (
            load_style_direction(project_dir, s.get("direction_id"))
            if s.get("direction_id") else None
        )
        style_reference = style_direction_image(project_dir, direction)
        validation_fresh = False
        if validation_path.exists() and bible:
            validation_config = config.model_copy(
                update={"style_template": style_template_for_suggestion(s)}
            )
            validation_request = build_style_sample_request(
                validation_config, bible, style_validation_brief(bible),
                candidate_id=f"{s['id']}:validation",
                project_dir=project_dir,
                style_reference=style_reference,
                style_reference_mode=s["style_reference_mode"],
                subject_action=STYLE_VALIDATION_ACTION,
                composition=STYLE_VALIDATION_COMPOSITION,
            )
            validation_fresh = asset_matches_request(validation_path, validation_request)
        lettering_style = _proof_style(project_dir, s, active=i == active_index)
        proof_base = f"/api/projects/{project_id}/styles/{s['id']}/proof"
        proof_revision = lettering_style.content_sha256
        result.append({
            **s,
            # A stale art-only sample still takes today's software lettering:
            # the overlay is free and lands in the spaces that art reserved.
            "sample_preview_url": (
                f"{proof_base}/sample?style={proof_revision}"
                if sample_exists and bible is not None and (
                    i not in stale_indices
                    or (editable and sample_takes_software_lettering(sample_path))
                ) else None
            ),
            "lettering_source": "generated" if s.get("lettering_design") else "preset",
            "index": i,
            # Existence and freshness are separate UI concerns.  A proof made
            # under an older prompt contract is still valuable project work:
            # keep it visible and let the author decide when to replace it.
            "has_sample": sample_exists,
            "generation_status": proof_states.get(i, "complete" if sample_exists else "not_requested"),
            "sample_stale": sample_exists and i in stale_indices,
            "has_validation": validation_fresh,
            "has_style_reference": bool(
                style_reference is not None and _supports_style_reference(config)
            ),
            "validation_url": (
                f"{proof_base}/validation?style={proof_revision}"
                if validation_fresh else None
            ),
            "is_active": i == active_index,
        })

    return {
        "suggestions": result, "active_index": active_index, "active_id": active_id,
        # Any proof in flight (polling) versus a batch that owns the portfolio (gating).
        "is_generating": bool(active_style_jobs), "is_suggesting": bool(batch_jobs),
    }


@router.get("/styles/{suggestion_id}/proof/{kind}")
def get_style_lettering_proof(
    project_id: str, suggestion_id: str, kind: Literal["sample", "validation"],
    project=Depends(get_project),
):
    # Freshness is checked against the canonical mode-specific request under the
    # artifact lock. An old baked proof never gets an accidental second overlay.
    with production_lock(project[0]):
        entries = get_styles(project_id, project)["suggestions"]
        suggestion = next((entry for entry in entries if entry["id"] == suggestion_id), None)
        if suggestion is None:
            raise HTTPException(404, "Style direction not found.")
        fresh = (bool(suggestion["sample_preview_url"]) if kind == "sample"
                 else suggestion["has_validation"])
        if not fresh:
            raise HTTPException(409, "This proof uses earlier rendering rules. Explicitly refresh it to preview the current lettering mode.")
        source = (artifacts.style_sample_path(project[0], suggestion["index"]) if kind == "sample"
                  else artifacts.style_validation_path(project[0], suggestion_id))
        if project_lettering_mode(TargetArtifacts(project[0]), project[1]) == "integrated":
            # Integrated proof requests already draw their lettering into the image.
            return Response(source.read_bytes(), media_type="image/png", headers={"Cache-Control": "private, no-cache"})
        style = _proof_style(project[0], suggestion, active=suggestion["is_active"])
        art = source.read_bytes()
        copy = proof_copy_for_sample(style_proof_copy(project[1], _get_bible(project[0]), project[0]), source)
    # The overlay is a content-addressed derivative: render it outside the lock
    # so a cold proof never stalls the rest of the project (or the other proofs).
    try:
        data, identity = render_style_proof(TargetArtifacts(project[0]), style, art, copy)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(data, media_type="image/png", headers={
        "Cache-Control": "private, no-cache", "ETag": f'"{identity}"',
    })


@router.get("/styles/suggest-estimate")
def suggest_estimate(
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the credit cost for one 'Suggest More Styles' batch (text + samples)."""
    project_dir, config, _state = project
    return _suggest_batch_credit_estimate(config, project_dir)


@router.get("/styles/sample-estimate")
def style_sample_estimate(
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the credit cost to regenerate one style sample image."""
    _project_dir, config, _state = project
    return _style_sample_credit_estimate(config)


@router.get("/styles/direction-estimate")
def style_direction_estimate(
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001
):
    """Estimate one faithful custom-direction proof."""
    _project_dir, config, _state = project
    estimates_without_reference = _direction_credit_estimates(config, _project_dir)
    estimates_with_reference = _direction_credit_estimates(
        config, _project_dir, has_style_reference=True,
    )
    return {
        **_style_sample_credit_estimate(config),
        # `estimates` remains the text-only alias for existing clients.
        "estimates": estimates_without_reference,
        "estimates_without_reference": estimates_without_reference,
        "estimates_with_reference": estimates_with_reference,
        "image_reference_supported": _supports_style_reference(config),
        "max_upload_bytes": _MAX_STYLE_REFERENCE_BYTES,
        "accepted_image_types": sorted(_STYLE_IMAGE_TYPES),
    }


async def _prepare_style_direction(
    *, project_dir: Path, config: Config, bible: StoryBible,
    text: str, label: str | None, image: UploadFile | None, persist: bool = True,
) -> dict:
    """Validate, charge-check, and persist one direction before its job is queued."""
    image_bytes = b""
    suffix = ""
    reference_size = None
    if image is not None:
        try:
            suffix = image_suffix(image.content_type)
        except UploadedImageError:
            raise HTTPException(400, "Style reference must be PNG, JPEG, or WebP") from None
        image_bytes = await image.read(_MAX_STYLE_REFERENCE_BYTES + 1)
        if len(image_bytes) > _MAX_STYLE_REFERENCE_BYTES:
            raise HTTPException(413, "Style reference exceeds the 10 MiB limit")
        try:
            reference_size = decode_uploaded_image(image_bytes, suffix)
        except UploadedImageError:
            raise HTTPException(400, "Uploaded style reference is not a valid image") from None

    image_reference_supported = _supports_style_reference(config)
    _assert_usable_style_direction(config, text, bool(image_bytes))
    identity_material = text.encode() + b"\0" + image_bytes
    direction_id = f"direction_{hashlib.sha256(identity_material).hexdigest()[:16]}"
    image_path = (
        artifacts.style_direction_image_path(project_dir, direction_id, suffix)
        if image_bytes else None
    )
    direction = {
        "version": 1, "id": direction_id,
        "label": (label or "").strip() or "Your direction", "text": text,
        "image_path": str(image_path.relative_to(project_dir)) if image_path else None,
        "image_sha256": hashlib.sha256(image_bytes).hexdigest() if image_bytes else None,
        "original_filename": Path(image.filename or "").name if image else None,
        "content_type": image.content_type if image else None,
        "origin": "user_text_image" if image and text else "user_image" if image else "user_text",
    }
    candidate = custom_direction_candidate(direction)
    prepared = {
        "direction": direction, "candidate": candidate, "image_path": image_path,
        "reference_supported": bool(image_path and image_reference_supported),
        "image_bytes": image_bytes, "reference_size": reference_size,
    }
    if persist:
        _persist_style_direction(project_dir, bible, prepared)
    return prepared


def _persist_style_direction(project_dir: Path, bible: StoryBible, prepared: dict) -> None:
    direction = prepared["direction"]
    candidate = prepared["candidate"]
    image_path = prepared["image_path"]
    direction_path = artifacts.style_direction_path(project_dir, direction["id"])
    direction_path.parent.mkdir(parents=True, exist_ok=True)
    if image_path:
        image_path.write_bytes(prepared["image_bytes"])
    direction_path.write_text(json.dumps(direction, indent=2, sort_keys=True))
    # Directions can be admitted while other proofs run; appends are
    # serialized so every queued proof keeps the index it was given.
    with production_lock(project_dir):
        suggestions = load_suggestions(project_dir)
        existing_index = suggestion_index_by_id(suggestions, candidate["id"])
        if existing_index is None:
            suggestions.append(candidate)
            save_suggestions(project_dir, suggestions, bible.title)
            index = len(suggestions)
        else:
            index = existing_index
    prepared["index"] = index


@router.post("/styles/direction")
async def create_style_direction(
    request: Request,
    project_id: str,
    direction_text: str | None = Form(None),
    label: str | None = Form(None),
    with_neighbors: bool = Form(False),
    image: UploadFile | None = File(None),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Persist an author direction and queue one faithful story-specific proof."""
    project_dir, config, state = project
    operations = _direction_operations(config, with_neighbors=with_neighbors)
    classify_operations(operations)
    pkey = project_key(user_id, project_id)
    _assert_no_pipeline_task(request, pkey)
    _assert_no_style_task(request, pkey)
    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")
    text = (direction_text or "").strip()
    if len(text) > 4000:
        raise HTTPException(400, "Style direction text must be 4,000 characters or fewer")
    if not text and image is None:
        raise HTTPException(400, "Provide direction_text, image, or both")
    if with_neighbors and not text:
        raise HTTPException(400, "Text direction is required when generating neighboring styles")
    _assert_usable_style_direction(config, text, image is not None)
    # Starlette has already spooled multipart parts before route dispatch; the
    # earliest route-local body guard available is Content-Length plus the
    # streamed UploadFile byte cap enforced in _prepare_style_direction.
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_STYLE_MULTIPART_BYTES:
                raise HTTPException(413, "Style direction request exceeds the upload limit")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length header") from None
    style_guard = asyncio.get_running_loop().create_future()
    request.app.state.style_tasks[pkey] = style_guard
    reservation_id = None
    db = None
    try:
        prepared = await _prepare_style_direction(
            project_dir=project_dir, config=config, bible=bible,
            text=text, label=label, image=image, persist=False,
        )
        estimates = _direction_credit_estimates(
            config,
            project_dir,
            has_style_reference=prepared["reference_supported"],
            template=style_template_for_suggestion(prepared["candidate"]),
            candidate_id=prepared["candidate"]["id"],
            reference_size=prepared["reference_size"],
        )
        operation_estimate = estimates[
            "faithful_with_neighbors" if with_neighbors else "faithful"
        ]
        required = operation_estimate["reserved_credits"] or operation_estimate["estimate_credits"]
        db = get_db()
        assert_sufficient_credits(db, user_id, required, action="style_direction")
        reservation_id, job_id = reserve_credits(
            db, user_id, project_id, "style", required,
        )
        _persist_style_direction(project_dir, bible, prepared)
    except BaseException:
        if reservation_id and db is not None:
            release_reservation(db, reservation_id)
        if request.app.state.style_tasks.get(pkey) is style_guard:
            request.app.state.style_tasks.pop(pkey, None)
        if not style_guard.done():
            style_guard.set_result(None)
        raise
    direction = prepared["direction"]
    candidate = prepared["candidate"]
    index = prepared["index"]
    image_path = prepared["image_path"]
    reference_supported = prepared["reference_supported"]
    sample_path = artifacts.style_sample_path(project_dir, index)

    try:
        lifecycle_owned = state.stages["style"].status not in (
            StageStatus.RUNNING, StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE,
        )
        if lifecycle_owned:
            begin_stage(state, "style", SAMPLE_COUNT if with_neighbors else 1)
            save_state(state, project_dir)
    except BaseException:
        if reservation_id:
            release_reservation(db, reservation_id)
        if request.app.state.style_tasks.get(pkey) is style_guard:
            request.app.state.style_tasks.pop(pkey, None)
        if not style_guard.done():
            style_guard.set_result(None)
        raise

    def _terminal() -> None:
        try:
            if lifecycle_owned and state.stages["style"].status == StageStatus.RUNNING:
                fail_stage(state, "style", "Style generation did not complete")
                save_state(state, project_dir)
        finally:
            if not style_guard.done():
                style_guard.set_result(None)
            if request.app.state.style_tasks.get(pkey) is style_guard:
                request.app.state.style_tasks.pop(pkey, None)

    async def _runner() -> None:
        try:
            with ai_request_context(
                user_id=user_id, project_id=project_id, project_name=project_dir.name,
                workspace_id=str(project_dir.parent), stage="style", job_id=job_id,
            ):
                brief = await ensure_style_sample_brief(config, bible, project_dir)
                await generate_sample_image(
                    config.model_copy(
                        update={"style_template": style_template_for_suggestion(candidate)}
                    ),
                    bible, sample_path, brief=brief, candidate_id=candidate["id"],
                    style_reference=image_path,
                )
                await describe_custom_direction(config, project_dir, candidate, sample_path, bible.title)
                if with_neighbors:
                    current = load_suggestions(project_dir)
                    neighbors, _usage = await generate_suggestions(
                        config, bible, existing_suggestions=current,
                        custom_direction=direction,
                    )
                    merged = current + neighbors
                    start = len(current) + 1
                    await generate_samples_for_indices(
                        config, bible, project_dir, merged,
                        list(range(start, len(merged) + 1)),
                    )
                    # Commit the neighbors only after every proof succeeds.
                    # A failed attempt may leave replaceable image files, but a
                    # retry cannot append duplicate suggestion records. Re-read
                    # so renames and hides made meanwhile are not reverted.
                    with production_lock(project_dir):
                        save_suggestions(project_dir, load_suggestions(project_dir) + neighbors, bible.title)
            if lifecycle_owned:
                for _ in range(SAMPLE_COUNT if with_neighbors else 1):
                    record_item_done(state, "style")
                complete_stage(state, "style")
                save_state(state, project_dir)
        except BaseException as exc:
            if lifecycle_owned:
                fail_stage(state, "style", str(exc) or type(exc).__name__)
                save_state(state, project_dir)
            raise

    try:
        prune_finished_generation_jobs(request.app)
        job, _created = enqueue_reserved_generation_job(
            request.app, project_name=pkey, kind="style_sample",
            label=candidate["label"], payload={"id": candidate["id"], "index": index, "with_neighbors": with_neighbors},
            work=_runner, user_id=user_id, project_id=project_id,
            project_dir=project_dir, stage="style",
            debit_description="Style direction", reservation_credits=required,
            operations=operations,
            command=command("style_direction", project_dir, config,
                bible=bible.model_dump(mode="json"), candidate=candidate, index=index,
                direction=direction, with_neighbors=with_neighbors, lifecycle_owned=lifecycle_owned),
            existing_hold=(reservation_id, job_id), on_terminal=_terminal,
            semaphore=generation_semaphore_for_config(request.app, config),
        )
    except BaseException:
        if lifecycle_owned:
            fail_stage(state, "style", "Failed to enqueue style generation")
            save_state(state, project_dir)
        if reservation_id and not style_guard.done():
            release_reservation(db, reservation_id)
        if request.app.state.style_tasks.get(pkey) is style_guard:
            request.app.state.style_tasks.pop(pkey, None)
        if not style_guard.done():
            style_guard.set_result(None)
        raise
    if getattr(request.app.state, "durable_queue_required", False) is True:
        if not style_guard.done():
            style_guard.set_result(None)
        request.app.state.style_tasks.pop(pkey, None)
    return {
        "status": "queued",
        "with_neighbors": with_neighbors,
        "estimate": operation_estimate,
        "direction": {
            "id": direction["id"], "text": text, "has_image": bool(image_path),
            "image_supported": reference_supported,
        },
        "suggestion": {**candidate, "index": index, "has_sample": sample_path.exists()},
        "job": generation_job_payload(request.app, job),
    }


@router.post("/styles/suggest")
async def suggest_styles(
    request: Request,
    project_id: str,
    body: dict | None = None,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    operations = prompt_image_operations(config)
    classify_operations(operations)
    pkey = project_key(user_id, project_id)

    _assert_no_pipeline_task(request, pkey)
    _assert_no_style_task(request, pkey)
    style_running = request.app.state.style_tasks

    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")
    direction = None
    direction_id = (body or {}).get("direction_id")
    if direction_id:
        direction = load_style_direction(project_dir, str(direction_id))
        if direction is None:
            raise HTTPException(404, "Style direction not found")

    style_reference = style_direction_image(project_dir, direction) if direction else None
    estimate = _suggest_batch_credit_estimate(
        config, project_dir, NEIGHBOR_COUNT if direction else SAMPLE_COUNT,
        has_style_reference=style_reference is not None,
        reference_size=_reference_image_size(style_reference),
    )
    required = estimate["reserved_credits"] or estimate["estimate_credits"]
    db = get_db()
    assert_sufficient_credits(db, user_id, required, action="style_suggest")
    # Share one job_id across reservation + every per-call debit so the credit
    # ledger collapses the batch into a single grouped row.
    reservation_id, job_id = reserve_credits(db, user_id, project_id, "style", required)
    queue: EventChannel | None = None
    lifecycle_owned = False
    lifecycle_started = False
    style_guard = asyncio.get_running_loop().create_future()

    def _terminal() -> None:
        try:
            if not any(
                event["type"] in ("stage_complete", "stage_fail")
                for event in queue.history
            ):
                message = "Style suggestion job did not complete"
                queue.put_nowait({"type": "stage_fail", "stage": "style_suggest", "message": message})
                if lifecycle_owned:
                    fail_stage(state, "style", message)
                    save_state(state, project_dir)
        finally:
            if not style_guard.done():
                style_guard.set_result(None)
            if style_running.get(pkey) is style_guard:
                style_running.pop(pkey, None)

    async def _job():
        operation_feature = "style.suggestions"
        operation_model = config.effective_prompt_model()
        queue.put_nowait({"type": "stage_begin", "stage": "style_suggest", "total": 1})
        try:
            queue.put_nowait({
                "type": "log", "stage": "style_suggest", "level": "info",
                "message": "Generating style suggestions...",
            })
            existing_suggestions = load_suggestions(project_dir)
            existing_count = len(existing_suggestions)
            with ai_request_context(
                user_id=user_id,
                project_id=project_id,
                project_name=project_dir.name,
                workspace_id=str(project_dir.parent),
                stage="style",
                job_id=job_id,
            ):
                new_suggestions, _usage = await generate_suggestions(
                    config, bible, existing_suggestions=existing_suggestions,
                    custom_direction=direction,
                )
                with production_lock(project_dir):
                    # Re-read so directions, names and hides saved meanwhile survive.
                    existing_suggestions = load_suggestions(project_dir)
                    existing_count = len(existing_suggestions)
                    merged = existing_suggestions + new_suggestions
                    save_suggestions(project_dir, merged, bible.title)
                
                total_samples = len(new_suggestions)
                queue.put_nowait({
                    "type": "stage_progress", "stage": "style_suggest",
                    "done": 0, "total": total_samples,
                })
                
                queue.put_nowait({
                    "type": "log", "stage": "style_suggest", "level": "info",
                    "message": f"Generating {total_samples} sample images...",
                })
                operation_feature = "style.sample"
                operation_model = config.effective_image_model()
                
                done_count = 0

                async def _on_sample_done(_idx: int, result) -> None:
                    nonlocal done_count
                    done_count += 1
                    queue.put_nowait({
                        "type": "stage_progress", "stage": "style_suggest",
                        "done": done_count, "total": total_samples,
                    })

                new_indices = list(range(existing_count + 1, len(merged) + 1))
                await generate_samples_for_indices(
                    config, bible, project_dir, merged, new_indices,
                    on_sample_done=_on_sample_done,
                )
            queue.put_nowait({"type": "stage_progress", "stage": "style_suggest", "done": total_samples, "total": total_samples})
            queue.put_nowait({"type": "stage_complete", "stage": "style_suggest", "done": total_samples, "total": total_samples})
            if lifecycle_owned:
                for _ in range(total_samples):
                    record_item_done(state, "style")
                complete_stage(state, "style")
                save_state(state, project_dir)
        except BaseException as exc:
            from novel_to_comic.text_utils import clean_exception_message

            cancelled = isinstance(exc, asyncio.CancelledError)
            message = (
                "Style suggestion job cancelled"
                if cancelled else clean_exception_message(exc)
            )
            queue.put_nowait({
                "type": "stage_fail", "stage": "style_suggest",
                "message": message,
            })
            if lifecycle_owned:
                fail_stage(state, "style", message)
                save_state(state, project_dir)
            if cancelled:
                raise
            log_args = (
                project_dir.name,
                project_id,
                operation_feature,
                operation_model,
                message,
            )
            if isinstance(exc, AITransportError):
                logger.warning(
                    "Style suggestion failed (handled AI transport error) "
                    "project=%s project_id=%s stage=style_suggest "
                    "feature=%s model=%s error=%s",
                    *log_args,
                )
            else:
                logger.exception(
                    "Style suggestion failed project=%s project_id=%s "
                    "stage=style_suggest feature=%s model=%s error=%s",
                    *log_args,
                )
            raise

    try:
        queue = EventChannel()
        request.app.state.event_queues[pkey] = queue
        lifecycle_owned = state.stages["style"].status not in (
            StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE,
        )
        if lifecycle_owned:
            begin_stage(state, "style", NEIGHBOR_COUNT if direction else SAMPLE_COUNT)
            lifecycle_started = True
            save_state(state, project_dir)
        style_running[pkey] = style_guard
        queued_job, _created = enqueue_reserved_generation_job(
            request.app, project_name=pkey, user_id=user_id,
            project_id=project_id, project_dir=project_dir, stage="style",
            kind="style_suggest", label="Style suggestions",
            payload={"direction_id": direction_id}, work=_job,
            debit_description="Style suggestions", reservation_credits=required,
            operations=operations,
            command=command("style_suggest", project_dir, config,
                bible=bible.model_dump(mode="json"), direction=direction, lifecycle_owned=lifecycle_owned),
            existing_hold=(reservation_id, job_id), on_terminal=_terminal,
            semaphore=generation_semaphore_for_config(request.app, config),
        )
    except BaseException as exc:
        if lifecycle_started:
            fail_stage(state, "style", str(exc) or type(exc).__name__)
            try:
                save_state(state, project_dir)
            except BaseException:
                pass
        if request.app.state.event_queues.get(pkey) is queue:
            request.app.state.event_queues.pop(pkey, None)
        style_running.pop(pkey, None)
        if not style_guard.done():
            release_reservation(db, reservation_id)
        raise
    if getattr(request.app.state, "durable_queue_required", False) is True:
        if not style_guard.done():
            style_guard.set_result(None)
        style_running.pop(pkey, None)
    return {"status": "started", "job": generation_job_payload(request.app, queued_job)}


@router.post("/styles/generate-samples")
async def generate_style_samples(
    request: Request,
    project_id: str,
    body: dict,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Regenerate sample images for specific style indices (per-card retry)."""
    project_dir, config, _state = project
    pkey = project_key(user_id, project_id)

    _assert_no_pipeline_task(request, pkey)
    _assert_no_style_task(request, pkey)

    suggestions = load_suggestions(project_dir)
    ids = body.get("ids", [])
    indices = body.get("indices", [])
    if ids:
        if not isinstance(ids, list):
            raise HTTPException(400, "'ids' must be a list")
        indices = [suggestion_index_by_id(suggestions, str(item)) for item in ids]
        if any(index is None for index in indices):
            raise HTTPException(400, "One or more style ids were not found")
    if not indices or not isinstance(indices, list):
        raise HTTPException(400, "Provide non-empty 'ids' or 'indices' list")

    if not suggestions:
        raise HTTPException(404, "No style suggestions found — run suggest first.")

    for idx in indices:
        if idx < 1 or idx > len(suggestions):
            raise HTTPException(400, f"Index {idx} out of range (1-{len(suggestions)})")

    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")

    operations = style_sample_operations(config)
    classify_operations(operations)
    jobs = []
    prune_finished_generation_jobs(request.app)
    for idx in indices:
        existing = find_active_generation_job(
            request.app, project_name=pkey, kind="style_sample", payload={"index": idx},
        )
        if existing:
            jobs.append(generation_job_payload(request.app, existing))
            continue

        s = suggestions[idx - 1]
        template = style_template_for_suggestion(s)
        candidate_id = s.get("id")
        direction = load_style_direction(project_dir, s.get("direction_id")) if s.get("direction_id") else None
        style_reference = style_direction_image(project_dir, direction)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = artifacts.style_sample_path(project_dir, idx)
        estimate = _style_sample_credit_estimate(
            sample_config, reserve=True, has_style_reference=style_reference is not None,
            exact_cost_usd=estimate_style_proof_cost_usd(
                sample_config, project_dir, bible, template, candidate_id,
                style_reference=style_reference,
                style_reference_mode=s["style_reference_mode"],
            ),
        )

        async def _runner(
            sample_config=sample_config, sample_path=sample_path,
            candidate_id=candidate_id, style_reference=style_reference,
            style_reference_mode=s["style_reference_mode"],
        ) -> None:
            # Brief generation is paid too: keep it inside the queued hold.
            brief = await ensure_style_sample_brief(sample_config, bible, project_dir)
            await generate_sample_image(
                sample_config, bible, sample_path, brief=brief,
                candidate_id=candidate_id, style_reference=style_reference,
                style_reference_mode=style_reference_mode,
            )

        job, _created = enqueue_reserved_generation_job(
            request.app,
            project_name=pkey,
            kind="style_sample",
            label=f"style {idx}",
            payload={"index": idx},
            work=_runner, user_id=user_id, project_id=project_id,
            project_dir=project_dir, stage="style",
            debit_description=f"Style sample {idx}",
            reservation_credits=estimate["reserved_credits"] or estimate["estimate_credits"],
            operations=operations,
            command=command("style_sample", project_dir, config,
                bible=bible.model_dump(mode="json"), candidate=s, index=idx),
            semaphore=generation_semaphore_for_config(request.app, sample_config),
        )
        jobs.append(generation_job_payload(request.app, job))

    return {
        "status": "queued", "ids": [suggestions[index - 1].get("id") for index in indices],
        "indices": indices, "jobs": jobs,
    }


@router.post("/styles/validation")
async def generate_style_validation(
    request: Request,
    project_id: str,
    body: dict,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Queue an optional second proof that auditions action and environment."""
    project_dir, config, _state = project
    operations = image_operations(config)
    classify_operations(operations)
    pkey = project_key(user_id, project_id)
    _assert_no_pipeline_task(request, pkey)
    _assert_no_style_task(request, pkey)
    suggestions = load_suggestions(project_dir)
    suggestion_id = str(body.get("id") or "")
    index = suggestion_index_by_id(suggestions, suggestion_id)
    if index is None:
        raise HTTPException(404, "Style suggestion not found")
    bible = _get_bible(project_dir)
    if not bible:
        raise HTTPException(404, "Story bible not found — run extract first.")
    prune_finished_generation_jobs(request.app)
    payload = {"id": suggestion_id, "index": index}
    existing = find_active_generation_job(
        request.app, project_name=pkey, kind="style_validation", payload=payload,
    )
    if existing:
        return {
            "status": "queued", "id": suggestion_id,
            "url": f"/api/projects/{project_id}/files/samples/validations/{suggestion_id}.png",
            "job": generation_job_payload(request.app, existing),
        }
    suggestion = suggestions[index - 1]
    direction = (
        load_style_direction(project_dir, suggestion.get("direction_id"))
        if suggestion.get("direction_id") else None
    )
    style_reference = style_direction_image(project_dir, direction)
    exact_cost = estimate_style_proof_cost_usd(
        config,
        project_dir,
        bible,
        style_template_for_suggestion(suggestion),
        f"{suggestion_id}:validation",
        style_reference=style_reference,
        style_reference_mode=suggestion["style_reference_mode"],
        subject_action=STYLE_VALIDATION_ACTION,
        composition=STYLE_VALIDATION_COMPOSITION,
    )
    estimate = _style_sample_credit_estimate(
        config,
        reserve=True,
        has_style_reference=style_reference is not None,
        exact_cost_usd=exact_cost,
        validation=True,
    )
    brief = style_validation_brief(bible)
    output_path = artifacts.style_validation_path(project_dir, suggestion_id)
    sample_config = config.model_copy(
        update={"style_template": style_template_for_suggestion(suggestion)}
    )

    async def _runner() -> None:
        await generate_sample_image(
            sample_config, bible, output_path, brief=brief,
            candidate_id=f"{suggestion_id}:validation",
            style_reference=style_reference,
            style_reference_mode=suggestion["style_reference_mode"],
            project_dir=project_dir,
            subject_action=STYLE_VALIDATION_ACTION,
            composition=STYLE_VALIDATION_COMPOSITION,
        )

    job, _created = enqueue_reserved_generation_job(
        request.app, project_name=pkey, kind="style_validation",
        label=f"{suggestion['label']} validation",
        payload=payload, work=_runner, user_id=user_id,
        project_id=project_id, project_dir=project_dir, stage="style",
        debit_description="Style validation",
        reservation_credits=estimate["reserved_credits"] or estimate["estimate_credits"],
        operations=operations,
        command=command("style_validation", project_dir, config,
            bible=bible.model_dump(mode="json"), candidate=suggestion, index=index),
        semaphore=generation_semaphore_for_config(request.app, sample_config),
    )
    return {
        "status": "queued", "id": suggestion_id,
        "url": f"/api/projects/{project_id}/files/samples/validations/{suggestion_id}.png",
        "job": generation_job_payload(request.app, job),
    }


@router.patch("/styles/active")
def set_active_style(
    project_id: str,
    body: dict,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project

    with production_lock(project_dir):
        state = load_state(project_dir)
        suggestions = load_suggestions(project_dir)
        if not suggestions:
            raise HTTPException(404, "No style suggestions found — run suggest first.")
        suggestion_id = body.get("id")
        index = suggestion_index_by_id(suggestions, suggestion_id) if suggestion_id else body.get("index")
        if index is None:
            raise HTTPException(400, "Provide 'id' or 'index'")

        if index < 1 or index > len(suggestions):
            raise HTTPException(400, f"Index {index} out of range (1-{len(suggestions)})")

        template = style_template_for_suggestion(suggestions[index - 1])
        changed = template.strip() != config.style_template.strip()
        target = TargetArtifacts(project_dir)
        next_style = None
        if changed:
            try:
                style_revision = target.read_lettering_style().revision + 1
            except ArtifactMissing:
                style_revision = 1
            # Validate before changing selected authority or deleting derived work.
            next_style = style_from_template(template, revision=style_revision)
        config = config.model_copy(update={"style_template": template})
        save_config(config, project_dir)
        if changed:
            clear_style_failures_after_selection(state)
            for stage in ("cast", "adapt", "plan", "draw", "finish"):
                state.stages[stage] = StageState()
            for path in REGISTRY["cast"].clean_paths(project_dir):
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            target.write_lettering_style(next_style)
            save_state(state, project_dir)
        elif clear_style_failures_after_selection(state):
            save_state(state, project_dir)

        result = {"status": "updated", "index": index, "style_template": template, "style_changed": changed}
        if suggestion_id:
            result["id"] = suggestions[index - 1].get("id")
        if isinstance(user_id, str):
            capture_server_event(
                "style_selected",
                user_id=user_id,
                project_id=project_id,
                properties={"style_id": str(result.get("id") or index)},
            )
        return result


@router.patch("/styles/{suggestion_id}")
def update_style_presentation(
    suggestion_id: str,
    body: dict,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Rename or hide a proof. Presentation only: never changes its style or id."""
    project_dir, config, _state = project
    unknown = set(body) - {"display_label", "hidden"}
    if unknown or not body:
        raise HTTPException(400, "Provide display_label and/or hidden")
    fields = {}
    if "display_label" in body:
        label = body["display_label"]
        if label is not None and not isinstance(label, str):
            raise HTTPException(400, "display_label must be a string")
        label = (label or "").strip()
        if len(label) > DISPLAY_LABEL_MAX_CHARS:
            raise HTTPException(400, f"Names must be {DISPLAY_LABEL_MAX_CHARS} characters or fewer")
        fields["display_label"] = label
    if "hidden" in body:
        if not isinstance(body["hidden"], bool):
            raise HTTPException(400, "hidden must be true or false")
        fields["hidden"] = body["hidden"]
    suggestions = load_suggestions(project_dir)
    index = suggestion_index_by_id(suggestions, suggestion_id)
    if index is None:
        raise HTTPException(404, "Style direction not found.")
    if fields.get("hidden") and _active_suggestion(suggestions, config)[1] == suggestion_id:
        raise HTTPException(409, "The selected style cannot be hidden")
    bible = _get_bible(project_dir)
    updated = update_suggestion_fields(
        project_dir, suggestion_id, fields, bible.title if bible else "",
    )
    if updated is None:
        raise HTTPException(404, "Style direction not found.")
    return {"suggestion": updated}
