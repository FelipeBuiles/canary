"""Style suggestion, sample generation, and active style selection."""

import asyncio
import hashlib
import io
import json
import logging
import warnings
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from novel_to_comic import artifacts
from novel_to_comic.ai import ai_request_context
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.config import Config, mock_mode_active, save_config
from novel_to_comic.image_models import image_model_profile_for_config
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.non_panel_generation import asset_matches_request
from novel_to_comic.state import (
    StageStatus, begin_stage, complete_stage, fail_stage, record_item_done, save_state,
)
from novel_to_comic.stages.s2_style import (
    STYLE_VALIDATION_ACTION,
    STYLE_VALIDATION_COMPOSITION,
    ensure_style_sample_brief,
    generate_sample_image,
    generate_samples_for_indices,
    generate_suggestions,
    custom_direction_candidate,
    build_style_sample_request,
    load_style_direction,
    load_suggestions,
    missing_sample_indices,
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
from ..db import get_db
from ..deps import get_project, project_key
from ..generation_jobs import (
    enqueue_generation_job,
    find_active_generation_job,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
)
from ..product_events import capture_server_event

router = APIRouter()
logger = logging.getLogger("canary.styles")
_STYLE_IMAGE_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
}
_MAX_STYLE_REFERENCE_BYTES = 10 * 1024 * 1024
_MAX_STYLE_MULTIPART_BYTES = _MAX_STYLE_REFERENCE_BYTES + 1024 * 1024
_MAX_STYLE_IMAGE_DIMENSION = 10_000
_MAX_STYLE_IMAGE_PIXELS = 40_000_000


def is_style_selected(project_dir, config) -> bool:
    """Check whether an active style has been selected for this project."""
    return any(
        s.get("template", "").strip() == config.style_template.strip()
        for s in load_suggestions(project_dir)
    )


def _active_suggestion(suggestions: list[dict], config: Config) -> tuple[int | None, str | None]:
    for index, suggestion in enumerate(suggestions, 1):
        if suggestion.get("template", "").strip() == config.style_template.strip():
            return index, suggestion.get("id")
    return None, None


def clear_style_failures_after_selection(state) -> bool:
    """A selected style resolves partial style-sample failures for navigation.

    Failed sample attempts can leave ``items_failed`` on an otherwise completed
    style stage. Once the user chooses an active style, those failures are no
    longer blocking for downstream stages.
    """
    style_state = state.stages["style"]
    if style_state.status not in (StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW):
        return False
    if not style_state.items_failed:
        return False
    style_state.items_failed = []
    return True


def _get_bible(project_dir):
    path = artifacts.story_bible_path(project_dir)
    if not path.exists():
        return None
    return StoryBible.model_validate_json(path.read_text())


def _suggest_batch_credit_estimate(
    config: Config,
    project_dir,
    sample_count: int = 5,
    *,
    has_style_reference: bool = False,
    reference_size: tuple[int, int] | None = None,
) -> dict:
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
) -> dict:
    """Keep one-sample preflight and generation credit checks in lockstep."""
    if mock_mode_active(config):
        return dict(credit_estimate_for_provider_cost(0.0, "style", reserve=reserve))
    if exact_cost_usd is None:
        cost_kwargs = {"quality": getattr(config, "image_quality", None)}
        if has_style_reference and _supports_style_reference(config):
            cost_kwargs["ref_count"] = 1
        exact_cost_usd = estimate_image_cost(
            config.effective_image_model(), 1,
            **cost_kwargs,
        )
    return dict(credit_estimate_for_provider_cost(
        exact_cost_usd, "style", reserve=reserve, zero_cost_estimate=1,
    ))


def _direction_credit_estimates(
    config: Config,
    project_dir,
    *,
    has_style_reference: bool = False,
    template: str | None = None,
    candidate_id: str = "direction_estimate",
    reference_size: tuple[int, int] | None = None,
) -> dict:
    if mock_mode_active(config):
        zero = dict(credit_estimate_for_provider_cost(0.0, "style", reserve=True))
        return {
            "faithful": zero,
            "neighbors": dict(zero),
            "faithful_with_neighbors": dict(zero),
        }
    reference_count = 1 if has_style_reference and _supports_style_reference(config) else 0
    bible = _get_bible(project_dir)
    faithful_cost = (
        estimate_style_proof_cost_usd(
            config, project_dir, bible, template or config.style_template, candidate_id,
            reference_size=(reference_size or (1024, 1024)) if reference_count else None,
        )
        if bible is not None
        else estimate_image_cost(
            config.effective_image_model(), 1,
            quality=getattr(config, "image_quality", None),
            ref_count=reference_count,
            ref_image_sizes=[reference_size or (1024, 1024)] if reference_count else None,
        )
    )
    neighbor_cost = estimate_style_batch_cost_usd(
        config, project_dir, 4,
        has_style_reference=bool(reference_count),
        reference_size=reference_size,
    )
    return {
        "faithful": dict(credit_estimate_for_provider_cost(
            faithful_cost, "style", reserve=True, zero_cost_estimate=1,
        )),
        "neighbors": dict(credit_estimate_for_provider_cost(
            neighbor_cost, "style", reserve=True,
        )),
        "faithful_with_neighbors": dict(credit_estimate_for_provider_cost(
            faithful_cost + neighbor_cost, "style", reserve=True,
            zero_cost_estimate=1,
        )),
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
def get_styles(project_id: str, project=Depends(get_project)):
    project_dir, config, _state = project
    suggestions = load_suggestions(project_dir)
    bible = _get_bible(project_dir)
    stale_indices = set(missing_sample_indices(
        project_dir, suggestions, config=config, bible=bible,
    )) if bible else set()

    active_index, active_id = _active_suggestion(suggestions, config)

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
            validation_config = config.model_copy(update={"style_template": s["template"]})
            validation_request = build_style_sample_request(
                validation_config, bible, style_validation_brief(bible),
                candidate_id=f"{s['id']}:validation",
                style_reference=style_reference,
                subject_action=STYLE_VALIDATION_ACTION,
                composition=STYLE_VALIDATION_COMPOSITION,
            )
            validation_fresh = asset_matches_request(validation_path, validation_request)
        result.append({
            **s,
            "index": i,
            # Existence and freshness are separate UI concerns.  A proof made
            # under an older prompt contract is still valuable project work:
            # keep it visible and let the author decide when to replace it.
            "has_sample": sample_exists,
            "sample_stale": sample_exists and i in stale_indices,
            "has_validation": validation_fresh,
            "has_style_reference": bool(
                style_reference is not None and _supports_style_reference(config)
            ),
            "validation_url": (
                f"/api/projects/{project_id}/files/samples/validations/{s['id']}.png"
                if validation_fresh else None
            ),
            "is_active": i == active_index,
        })

    return {"suggestions": result, "active_index": active_index, "active_id": active_id}


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
        suffix = _STYLE_IMAGE_TYPES.get((image.content_type or "").lower(), "")
        if not suffix:
            raise HTTPException(400, "Style reference must be PNG, JPEG, or WebP")
        image_bytes = await image.read(_MAX_STYLE_REFERENCE_BYTES + 1)
        if len(image_bytes) > _MAX_STYLE_REFERENCE_BYTES:
            raise HTTPException(413, "Style reference exceeds the 10 MiB limit")
        try:
            from PIL import Image
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(image_bytes)) as decoded:
                    expected_format = {".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP"}[suffix]
                    if decoded.format != expected_format:
                        raise ValueError("declared and decoded image formats differ")
                    if (
                        decoded.width > _MAX_STYLE_IMAGE_DIMENSION
                        or decoded.height > _MAX_STYLE_IMAGE_DIMENSION
                        or decoded.width * decoded.height > _MAX_STYLE_IMAGE_PIXELS
                    ):
                        raise ValueError("decoded image dimensions exceed limits")
                    reference_size = decoded.size
                    decoded.verify()
        except Exception:
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
            template=prepared["candidate"]["template"],
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
            StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE,
        )
        if lifecycle_owned:
            begin_stage(state, "style", 5 if with_neighbors else 1)
            save_state(state, project_dir)
    except BaseException:
        if reservation_id:
            release_reservation(db, reservation_id)
        if request.app.state.style_tasks.get(pkey) is style_guard:
            request.app.state.style_tasks.pop(pkey, None)
        if not style_guard.done():
            style_guard.set_result(None)
        raise

    async def _runner() -> None:
        try:
            with ai_request_context(
                user_id=user_id, project_id=project_id, project_name=project_dir.name,
                workspace_id=str(project_dir.parent), stage="style", job_id=job_id,
            ):
                brief = await ensure_style_sample_brief(config, bible, project_dir)
                await generate_sample_image(
                    config.model_copy(update={"style_template": candidate["template"]}),
                    bible, sample_path, brief=brief, candidate_id=candidate["id"],
                    style_reference=image_path,
                )
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
                    # Commit the four neighbors only after every proof succeeds.
                    # A failed attempt may leave replaceable image files, but a
                    # retry cannot append duplicate suggestion records.
                    save_suggestions(project_dir, merged, bible.title)
            if lifecycle_owned:
                for _ in range(5 if with_neighbors else 1):
                    record_item_done(state, "style")
                complete_stage(state, "style")
                save_state(state, project_dir)
        except BaseException as exc:
            if lifecycle_owned:
                fail_stage(state, "style", str(exc) or type(exc).__name__)
                save_state(state, project_dir)
            raise
        finally:
            if reservation_id:
                release_reservation(db, reservation_id)
            if not style_guard.done():
                style_guard.set_result(None)
            if request.app.state.style_tasks.get(pkey) is style_guard:
                request.app.state.style_tasks.pop(pkey, None)

    try:
        prune_finished_generation_jobs(request.app)
        job = enqueue_generation_job(
            request.app, project_name=pkey, kind="style_sample",
            label=candidate["label"], payload={"id": candidate["id"], "index": index},
            runner=_runner,
            semaphore=generation_semaphore_for_config(request.app, config),
        )
    except BaseException:
        if lifecycle_owned:
            fail_stage(state, "style", "Failed to enqueue style generation")
            save_state(state, project_dir)
        if reservation_id:
            release_reservation(db, reservation_id)
        if request.app.state.style_tasks.get(pkey) is style_guard:
            request.app.state.style_tasks.pop(pkey, None)
        if not style_guard.done():
            style_guard.set_result(None)
        raise
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
        config, project_dir, 4 if direction else 5,
        has_style_reference=style_reference is not None,
        reference_size=_reference_image_size(style_reference),
    )
    required = estimate["reserved_credits"] or estimate["estimate_credits"]
    db = get_db()
    assert_sufficient_credits(db, user_id, required, action="style_suggest")
    # Share one job_id across reservation + every per-call debit so the credit
    # ledger collapses the batch into a single grouped row.
    reservation_id, job_id = reserve_credits(db, user_id, project_id, "style", required)
    queue: asyncio.Queue | None = None
    lifecycle_owned = False
    lifecycle_started = False

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
                if direction:
                    new_suggestions = new_suggestions[:4]
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
                
                async def _on_sample_done(idx: int, result) -> None:
                    done_count = idx - existing_count
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
        finally:
            if reservation_id:
                release_reservation(db, reservation_id)
            if style_running.get(pkey) is asyncio.current_task():
                style_running.pop(pkey, None)

    try:
        queue = asyncio.Queue()
        request.app.state.event_queues[pkey] = queue
        lifecycle_owned = state.stages["style"].status not in (
            StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE,
        )
        if lifecycle_owned:
            begin_stage(state, "style", 4 if direction else 5)
            lifecycle_started = True
            save_state(state, project_dir)
        task = asyncio.create_task(_job())
        style_running[pkey] = task
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
        release_reservation(db, reservation_id)
        raise
    return {"status": "started"}


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

    # Credit pre-check: each sample calls the image model for real and is
    # debited via ai.client._settle_event_usage on success. Sum the per-sample
    # estimate so a zero-balance user can't queue free regens.
    per_sample = _style_sample_credit_estimate(config)["estimate_credits"]
    assert_sufficient_credits(
        get_db(), user_id, max(1, per_sample) * len(indices),
        action="style_sample_regen",
    )

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
        template = s.get("template", config.style_template)
        candidate_id = s.get("id")
        direction = load_style_direction(project_dir, s.get("direction_id")) if s.get("direction_id") else None
        style_reference = style_direction_image(project_dir, direction)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = artifacts.style_sample_path(project_dir, idx)

        async def _runner(
            sample_config=sample_config, sample_path=sample_path,
            candidate_id=candidate_id, style_reference=style_reference,
        ) -> None:
            with ai_request_context(
                user_id=user_id,
                project_id=project_id,
                project_name=project_dir.name,
                workspace_id=str(project_dir.parent),
                stage="style",
            ):
                # Disk-cached after the first sample batch, so regens reuse
                # the same scene the original samples were judged on.
                brief = await ensure_style_sample_brief(sample_config, bible, project_dir)
                await generate_sample_image(
                    sample_config, bible, sample_path, brief=brief,
                    candidate_id=candidate_id,
                    style_reference=style_reference,
                )

        job = enqueue_generation_job(
            request.app,
            project_name=pkey,
            kind="style_sample",
            label=f"style {idx}",
            payload={"index": idx},
            runner=_runner,
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
        suggestion["template"],
        f"{suggestion_id}:validation",
        style_reference=style_reference,
        subject_action=STYLE_VALIDATION_ACTION,
        composition=STYLE_VALIDATION_COMPOSITION,
    )
    estimate = _style_sample_credit_estimate(
        config,
        reserve=True,
        has_style_reference=style_reference is not None,
        exact_cost_usd=exact_cost,
    )
    db = get_db()
    assert_sufficient_credits(
        db, user_id, estimate["reserved_credits"] or estimate["estimate_credits"],
        action="style_validation",
    )
    reservation_id, job_id = reserve_credits(
        db, user_id, project_id, "style",
        estimate["reserved_credits"] or estimate["estimate_credits"],
    )
    brief = style_validation_brief(bible)
    output_path = artifacts.style_validation_path(project_dir, suggestion_id)
    sample_config = config.model_copy(update={"style_template": suggestion["template"]})

    async def _runner() -> None:
        try:
            with ai_request_context(
                user_id=user_id, project_id=project_id, project_name=project_dir.name,
                workspace_id=str(project_dir.parent), stage="style", job_id=job_id,
            ):
                await generate_sample_image(
                    sample_config, bible, output_path, brief=brief,
                    candidate_id=f"{suggestion_id}:validation",
                    style_reference=style_reference,
                    project_dir=project_dir,
                    subject_action=STYLE_VALIDATION_ACTION,
                    composition=STYLE_VALIDATION_COMPOSITION,
                )
        finally:
            if reservation_id:
                release_reservation(db, reservation_id)

    try:
        job = enqueue_generation_job(
            request.app, project_name=pkey, kind="style_validation",
            label=f"{suggestion['label']} validation",
            payload=payload, runner=_runner,
            semaphore=generation_semaphore_for_config(request.app, sample_config),
        )
    except BaseException:
        if reservation_id:
            release_reservation(db, reservation_id)
        raise
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

    suggestions = load_suggestions(project_dir)
    if not suggestions:
        raise HTTPException(404, "No style suggestions found — run suggest first.")
    suggestion_id = body.get("id")
    index = suggestion_index_by_id(suggestions, suggestion_id) if suggestion_id else body.get("index")
    if index is None:
        raise HTTPException(400, "Provide 'id' or 'index'")

    if index < 1 or index > len(suggestions):
        raise HTTPException(400, f"Index {index} out of range (1-{len(suggestions)})")

    template = suggestions[index - 1].get("template", config.style_template)
    config = config.model_copy(update={"style_template": template})
    save_config(config, project_dir)
    if clear_style_failures_after_selection(state):
        save_state(state, project_dir)

    result = {"status": "updated", "index": index, "style_template": template}
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
