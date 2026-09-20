"""Project listing, creation, display names, and pipeline status."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import shutil
import tempfile
import time
from json import JSONDecodeError
from pathlib import Path
from typing import cast

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel, ValidationError

from novel_to_comic.ai import ai_request_context
from novel_to_comic.config import Config, mock_mode_active, save_config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.input_limits import (
    InputLimitError,
    InputLimits,
    decode_remote_story,
    read_source,
)
from novel_to_comic.style_contract import (
    page_style_template,
    style_template_for_suggestion,
)
from novel_to_comic.models.generation import PromptAnchor, PromptSubject
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.asset_generation import (
    ProjectCoverInput,
    compile_non_panel_request,
    reference_plan_for_assets,
    style_reference_plan,
    submit_non_panel_request,
)
from novel_to_comic.state import (
    STAGE_NAMES,
    StageState,
    StageStatus,
    create_initial_state,
    is_stale,
    load_state,
    save_state,
)
from novel_to_comic.usage import estimate_image_cost
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts

from ..auth import get_current_user
from ..credits import (
    credit_estimate_for_provider_cost,
    provider_usd_to_credits,
)
from novel_to_comic.codex_dev import classify_operations
from ..codex_admission import image_operations
from ..db import get_db
from ..deps import get_project, get_project_dir, get_projects_dir, project_key
from ..project_paths import project_directory
from ..ratelimit import cost_limit, create_limit, limiter
from ..product_events import capture_server_event
from .styles import clear_style_failures_after_selection, is_style_selected
from ..generation_jobs import (
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
    recovered_generation_jobs,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple cache in-memory for the short story library catalog
_story_catalog_cache: list[dict] | None = None
_story_catalog_last_fetch: float = 0.0
_CACHE_EXPIRY: int = 86400  # 24 hours
_INCOMPATIBLE_PROJECT_REASON = (
    "This project was created with an older pipeline version and must be deleted."
)


def _stage_payload(
    project_dir: Path,
    name: str,
    state,
    *,
    is_task_alive: bool = False,
    in_flight: list[dict] | None = None,
) -> dict:
    s = state.stages[name]
    status = s.status.value
    error = s.error

    # Ground truth for liveness: if the asyncio task is alive, the stage
    # cannot be stale regardless of how long it's been since the last
    # state.json save. The wall-clock heuristic in is_stale() only fires
    # when the task is gone (server restart, crash).
    stale = is_stale(s) and not is_task_alive
    from ..diagnostics import local_diagnostics_enabled

    return {
        "status": status,
        "items_done": s.items_done,
        "items_total": s.items_total,
        "items_failed": s.items_failed,
        "approved": s.approved,
        "cost_credits": provider_usd_to_credits(s.cost_usd),
        "estimated_cost_credits": provider_usd_to_credits(s.estimated_cost_usd),
        "error": error,
        "error_detail": s.error_detail if local_diagnostics_enabled() else None,
        "error_code": s.error_code,
        "balance_credits": s.balance_credits,
        "required_credits": s.required_credits,
        "shortfall_credits": s.shortfall_credits,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "last_progress_at": s.last_progress_at.isoformat()
        if s.last_progress_at
        else None,
        "stale": stale,
        "in_flight": in_flight or [],
    }


def _reopen_unapproved_brief(project_dir: Path, state) -> bool:
    """Repair pipeline state that advanced beyond an unapproved brief."""
    try:
        brief = TargetArtifacts(project_dir).read_brief()
    except (ArtifactMissing, ValueError):
        return False

    brief_stage = state.stages["brief"]
    downstream = ("adapt", "plan", "draw", "finish")
    brief_state_needs_repair = (
        brief_stage.status == StageStatus.COMPLETE or brief_stage.approved is True
    )
    downstream_needs_reset = any(
        state.stages[stage].status != StageStatus.PENDING for stage in downstream
    )
    if brief.status == "approved" or not (
        brief_state_needs_repair or downstream_needs_reset
    ):
        return False

    brief_stage.status = StageStatus.AWAITING_REVIEW
    brief_stage.approved = None
    for stage in downstream:
        state.stages[stage] = StageState()
    return True


def _target_page_count(project_dir: Path) -> int:
    try:
        return len(TargetArtifacts(project_dir).read_plan().pages)
    except (ArtifactMissing, ValueError):
        return 0


def _target_issue_summary(project_dir: Path) -> dict:
    from novel_to_comic.page_review import summarize_page_issues

    return summarize_page_issues(TargetArtifacts(project_dir)).model_dump(
        mode="json"
    )


def _finish_ready(project_dir: Path) -> bool:
    try:
        return TargetArtifacts(project_dir).read_preflight().ready_to_export
    except (ArtifactMissing, ValueError):
        return False


def _is_project_running(user_id: str, project_id: str, request: Request) -> bool:
    from ..admission import project_busy

    return project_busy(request.app, project_key(user_id, project_id))


def _cover_path(project_dir: Path) -> Path:
    return project_dir / "cover" / "cover.png"


def _latest_project_cover_job(request: Request, pkey: str):
    jobs = [
        job
        for job in request.app.state.generation_jobs.values()
        if job.project_name == pkey and job.kind == "project_cover"
    ]
    if not jobs:
        return None
    return max(jobs, key=lambda job: job.sequence)


def _active_project_cover_job(request: Request, pkey: str):
    for job in request.app.state.generation_jobs.values():
        if (
            job.project_name == pkey
            and job.kind == "project_cover"
            and job.status in ("queued", "running")
        ):
            return job
    return None


def needs_initial_project_cover(request: Request, pkey: str, project_dir: Path) -> bool:
    """Auto-create once; prior attempts require an explicit user retry."""
    return (
        not _cover_path(project_dir).exists()
        and _latest_project_cover_job(request, pkey) is None
        and not any(
            job["kind"] == "project_cover"
            for job in recovered_generation_jobs(request.app, pkey)
        )
    )


def _project_cover_job_payload(request: Request, pkey: str) -> dict | None:
    job = _latest_project_cover_job(request, pkey)
    if job is not None:
        return generation_job_payload(request.app, job)
    return max(
        (job for job in recovered_generation_jobs(request.app, pkey) if job["kind"] == "project_cover"),
        key=lambda job: job["queued_at"],
        default=None,
    )


def _story_bible_author(project_dir: Path) -> str | None:
    bible_path = project_dir / "story_bible.json"
    if not bible_path.exists():
        return None
    try:
        return StoryBible.model_validate_json(bible_path.read_text()).author
    except Exception:
        return None


def _stored_project_name(project_dir: Path, fallback: str) -> str:
    """Read only the display name from an invalid state file when possible."""
    try:
        payload = json.loads((project_dir / "state.json").read_text())
    except (OSError, JSONDecodeError, UnicodeDecodeError):
        return fallback
    name = payload.get("project_name") if isinstance(payload, dict) else None
    return name if isinstance(name, str) and name.strip() else fallback


def _incompatible_project_summary(row: dict, project_dir: Path) -> dict:
    """Return a safe library entry for data the current pipeline cannot load."""
    return {
        "id": row["id"],
        "name": row["name"],
        "project_name": _stored_project_name(project_dir, row["name"]),
        "author": None,
        "created_at": row["created_at"],
        "total_cost_credits": 0,
        "furthest_stage": None,
        "is_running": False,
        "has_cover": False,
        "page_count": 0,
        "page_issue_summary": None,
        "finish_ready": False,
        "cover_job": None,
        "incompatible": True,
        "incompatibility_reason": _INCOMPATIBLE_PROJECT_REASON,
    }


def _find_style_ref(project_dir: Path, style_template: str) -> Path | None:
    suggestions_path = project_dir / "samples" / "style_suggestions.json"
    if suggestions_path.exists():
        try:
            data = json.loads(suggestions_path.read_text())
            active = page_style_template(style_template)
            for i, suggestion in enumerate(data.get("suggestions", []), 1):
                if (
                    isinstance(suggestion, dict)
                    and style_template_for_suggestion(suggestion) == active
                ):
                    sample = project_dir / "samples" / f"style_{i}.png"
                    if sample.exists():
                        return sample
        except Exception:
            pass
    return None






def _project_cover_credit_estimate(config: Config) -> dict:
    funding = classify_operations(image_operations(config))
    if funding == "codex_subscription":
        return dict(credit_estimate_for_provider_cost(0.0, "cast", reserve=False, funding=funding))
    if mock_mode_active(config):
        return dict(credit_estimate_for_provider_cost(0.0, "cast", reserve=False))
    return dict(credit_estimate_for_provider_cost(
        estimate_image_cost(
            config.effective_image_model(), 1, width=768, height=1024,
            quality=getattr(config, "image_quality", None),
        ),
        "cast",
        reserve=False,
        zero_cost_estimate=1,
    ))


async def _generate_project_cover(
    config: Config,
    project_dir: Path,
    user_id: str,
    project_id: str | None,
):
    from novel_to_comic.state import load_state, record_misc_usage, save_state

    bible_path = project_dir / "story_bible.json"
    if not bible_path.exists():
        raise FileNotFoundError("Story bible not found")

    bible = StoryBible.model_validate_json(bible_path.read_text())
    output_path = _cover_path(project_dir)
    style_ref = _find_style_ref(project_dir, config.style_template)
    cover_cast = bible.characters[:3]
    anchors = tuple(
        PromptAnchor(kind="location", entity_id=loc.id, name=loc.name, text=loc.visual_anchor)
        for loc in bible.locations[:2]
    )
    input_data = ProjectCoverInput(
        asset_identity="project_cover:cover",
        prompt=GenerationPromptInput(
            anchors=anchors,
            subjects=tuple(
                PromptSubject(character_id=char.id, name=char.name, identity=char.visual_anchor)
                for char in cover_cast
            ),
            visual_brief=(
                f"Book cover illustration for {bible.title} by {bible.author}. "
                "Feature the central mood and conflict without text, title, logos, captions, "
                "or typography. Portrait cover composition, one strong focal image, cinematic "
                "lighting, finished production art, no words."
            ),
            constraints="No lettering, title, logos, captions, typography, or readable words.",
            width=768,
            height=1024,
            generation_width=768,
            generation_height=1024,
            generation_shape="portrait",
        ),
        selected_style_text=config.style_template,
    )
    from novel_to_comic import artifacts
    from novel_to_comic.image_references import AuthorityScope, ReferenceAsset

    references = list(style_reference_plan(config, style_ref).selected)
    for char in cover_cast:
        path = artifacts.character_ref_sheet_path(project_dir, char.id)
        if not path.exists():
            raise ValueError(f"Generate and approve the character reference for {char.name} before creating this cover.")
        references.append(ReferenceAsset(
            path=path, role="subject", entity_id=char.id, appearance_state_id=None,
            authority_scope=AuthorityScope.FULL_APPEARANCE,
            preserve_facets=("face", "hair", "build", "anatomy", "wardrobe"),
            ignore_facets=(), pose=None,
            content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            lineage_parent_sha256=None, label=char.name,
        ))
    request = compile_non_panel_request(
        config, input_data, reference_plan=reference_plan_for_assets(config, references)
    )
    with ai_request_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_dir.name,
        workspace_id=str(project_dir.parent),
        stage="cover",
    ):
        submission = await submit_non_panel_request(
            config=config, project_dir=project_dir, request=request,
            output_path=output_path, feature="project.cover", kind="project_cover",
        )
    result = submission.result
    if result is None:
        raise RuntimeError("project cover request was queued without a result")
    if result.usage:
        state = load_state(project_dir)
        record_misc_usage(state, result.usage)
        save_state(state, project_dir)
    return result


_ALLOWED_EXTENSIONS = {".txt", ".epub", ".pdf"}


def _env_int(name: str, default: int) -> int:
    """Read an integer env var, falling back to ``default`` on a bad value.

    A misconfigured knob (e.g. ``CANARY_MAX_UPLOAD_MB=abc``) would otherwise
    crash the request with ValueError; a typed fallback is safer for ops knobs.
    """
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _rows(resp) -> list[dict]:
    """Typed view of a Supabase query response (always a list of dict rows).

    The supabase-py client types ``.data`` loosely (``bool | JSON | None``); in
    practice every query here returns a list of dict rows (or an empty list).
    """
    return cast(list[dict], resp.data or [])


def _max_upload_bytes() -> int:
    """Hard cap on uploaded novel size, before any bytes are persisted."""
    return InputLimits.from_env().upload_bytes


def _max_projects_per_user() -> int:
    """Cap on how many projects a single user may own."""
    return _env_int("CANARY_MAX_PROJECTS_PER_USER", 25)


def _save_upload_capped(file: UploadFile, dst: Path) -> None:
    """Stream an upload to disk, aborting (and cleaning up) past the size cap.

    Rejecting via Content-Length alone is unsafe (chunked transfers omit it), so
    we enforce while streaming. Raises 413 on overflow and removes the partial file.
    """
    cap = _max_upload_bytes()
    written = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dst, "wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > cap:
                    f.close()
                    dst.unlink(missing_ok=True)
                    limit_mb = cap // (1024 * 1024)
                    raise HTTPException(
                        413, f"Uploaded file exceeds the {limit_mb} MB limit."
                    )
                f.write(chunk)
    except OSError:
        # Disk/permission failure mid-write: clean up the partial file and
        # surface a clean error instead of leaking an OSError traceback.
        dst.unlink(missing_ok=True)
        raise HTTPException(500, "Could not save uploaded file.") from None


def _count_user_projects(user_id: str) -> int:
    result = get_db().table("projects").select("id").eq("user_id", user_id).execute()
    return len(_rows(result))


def _slugify(name: str) -> str:
    """Turn a display name into a filesystem-safe directory name."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-")
    return slug.lower() or "untitled"


@router.post("/")
@limiter.limit(create_limit)
async def create_project(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    config_overrides: str = Form(None),
    projects_dir: Path = Depends(get_projects_dir),
    user_id: str = Depends(get_current_user),
):
    # Per-user project cap — prevents unbounded disk growth / project spam.
    existing = _count_user_projects(user_id)
    if existing >= _max_projects_per_user():
        raise HTTPException(
            409,
            f"You've reached the project limit ({_max_projects_per_user()}). "
            f"Delete an existing project to create a new one.",
        )

    # Validate file extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type: {suffix}. Accepted: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )

    overrides = {}
    if config_overrides:
        try:
            overrides = json.loads(config_overrides)
        except JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in config_overrides") from None
    try:
        from ..account_models import creation_config
        config = creation_config(overrides, projects_dir, user_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid project configuration.") from exc

    # Resolve the final path before staging, but do not create any project
    # state until the source has passed the same extraction budgets as Stage 1.
    slug = _slugify(name)
    try:
        project_dir = project_directory(projects_dir, user_id, slug)
    except ValueError as exc:
        raise HTTPException(409, "Project storage is unavailable") from exc
    if project_dir.exists():
        raise HTTPException(409, f"Project '{slug}' already exists")

    user_dir = project_dir.parent
    user_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=".incoming-", dir=user_dir))
    safe_filename = Path(file.filename or f"source{suffix}").name
    staged_source = staging_dir / safe_filename
    try:
        _save_upload_capped(file, staged_source)
        read_source(staged_source)
    except InputLimitError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except HTTPException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    try:
        project_dir.mkdir()
    except FileExistsError:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(409, f"Project '{slug}' already exists") from None

    for subdir in [
        "input",
        "source",
        "brief",
        "samples",
        "refs",
        "plates",
        "adapt",
        "plan",
        "draw",
        "finish",
        "exports",
        "cover",
    ]:
        (project_dir / subdir).mkdir()

    dst = project_dir / "input" / safe_filename
    shutil.move(str(staged_source), dst)
    shutil.rmtree(staging_dir, ignore_errors=True)
    save_config(config, project_dir)

    # Create state
    state = create_initial_state(name, str(dst))
    save_state(state, project_dir)

    # .env.example
    (project_dir / ".env.example").write_text(
        "# AI gateway keys — copy to a .env at your repo root (not per-project).\n"
        "# The pipeline walks up from any project dir to find the nearest .env.\n"
        "# Never commit the real .env — add it to your root .gitignore.\n\n"
        "LITELLM_BASE_URL=http://localhost:4000\n"
        "LITELLM_API_KEY=sk-local-canary\n"
        "AI_BILL_FAILED_REQUESTS=provider_usage_only\n"
    )

    # Register project in DB. On failure, clean up the directory so filesystem
    # and DB don't get out of sync.
    try:
        db_result = (
            get_db()
            .table("projects")
            .insert({"user_id": user_id, "name": slug})
            .execute()
        )
        inserted = _rows(db_result)
        project_id = inserted[0]["id"] if inserted else None
    except Exception as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        logger.exception("Failed to register project %s for user %s", slug, user_id)
        raise HTTPException(
            500, "Failed to register project. Please try again."
        ) from exc

    capture_server_event(
        "project_created",
        user_id=user_id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        properties={"source": "upload", "file_type": suffix.lstrip(".")},
    )

    return {"id": project_id, "name": slug, "project_name": name, "status": "created"}


@router.get("/")
def list_projects(
    request: Request,
    projects_dir: Path = Depends(get_projects_dir),
    user_id: str = Depends(get_current_user),
):
    """Return projects owned by the user, ordered by DB created_at."""
    resp = (
        get_db()
        .table("projects")
        .select("id, name, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    results = []
    for row in _rows(resp):
        try:
            d = project_directory(projects_dir, user_id, row["name"])
        except ValueError:
            logger.warning("Skipping project %s with an unsafe storage path", row["id"])
            continue
        state_file = d / "state.json"
        if not d.is_dir() or not state_file.exists():
            continue  # orphaned DB row — directory missing, skip silently
        try:
            state = load_state(d)
        except (ValidationError, JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "Project %s has state data from an incompatible pipeline version",
                row["id"],
            )
            results.append(_incompatible_project_summary(row, d))
            continue
        pkey = project_key(user_id, row["id"])
        cover_job = _project_cover_job_payload(request, pkey)
        furthest = None
        for name in STAGE_NAMES:
            if _stage_payload(d, name, state)["status"] in (
                "complete",
                "awaiting_review",
            ):
                furthest = name
        results.append(
            {
                "id": row["id"],
                "name": row["name"],
                "project_name": state.project_name,
                "author": _story_bible_author(d),
                "created_at": state.created_at.isoformat(),
                "total_cost_credits": provider_usd_to_credits(state.total_cost_usd),
                "furthest_stage": furthest,
                "is_running": _is_project_running(user_id, row["id"], request),
                "has_cover": _cover_path(d).exists(),
                "page_count": _target_page_count(d),
                "page_issue_summary": _target_issue_summary(d),
                "finish_ready": _finish_ready(d),
                "cover_job": cover_job,
                "incompatible": False,
                "incompatibility_reason": None,
            }
        )
    return results


class RenameProjectRequest(BaseModel):
    name: str


@router.patch("/{project_id}")
def rename_project(
    project_id: str,
    payload: RenameProjectRequest,
    project=Depends(get_project),
):
    """Rename display metadata without changing the project's stable identity."""
    name = payload.name.strip()
    if not name or len(name) > 200:
        raise HTTPException(422, "Project name must contain between 1 and 200 characters.")
    project_dir, _config, state = project
    # Admission rejects active jobs and serializes mutations and status reads
    # before get_project loads state, so no stale writer can undo this rename.
    state.project_name = name
    save_state(state, project_dir)
    return {"id": project_id, "project_name": name}


@router.get("/{project_id}/status")
def project_status(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    running = _is_project_running(user_id, project_id, request)

    state_changed = not running and _reopen_unapproved_brief(project_dir, state)
    style_selected = is_style_selected(project_dir, config)
    if style_selected and clear_style_failures_after_selection(state):
        state_changed = True
    if (
        not running
        and style_selected
        and state.stages["style"].status == StageStatus.COMPLETE
        and state.stages["cast"].status == StageStatus.PENDING
    ):
        from novel_to_comic.stages.s3_cast import ready_asset_count
        from novel_to_comic.state import complete_stage, hash_style_template

        count = ready_asset_count(config, project_dir)
        if count is not None:
            state.stages["cast"].items_done = count
            state.stages["cast"].items_total = count
            state.style_template_hash = hash_style_template(config.style_template)
            complete_stage(state, "cast")
            state_changed = True
    if state_changed:
        save_state(state, project_dir)

    active_jobs = [generation_job_payload(request.app, job)
                   for job in request.app.state.generation_jobs.values()
                   if job.project_name == project_key(user_id, project_id)
                   and job.status in {"queued", "running"}]
    active_stages = {job["stage"] for job in active_jobs}
    stages = {}
    for name in STAGE_NAMES:
        stages[name] = _stage_payload(
            project_dir, name, state, is_task_alive=name in active_stages
        )
    stages["cast"]["approval_blocker"] = None
    if not running and state.stages["cast"].status in {StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE}:
        from novel_to_comic.stages.s3_cast import cast_approval_blocker
        stages["cast"]["approval_blocker"] = cast_approval_blocker(config, project_dir, state.stages["cast"])
    total_estimated = sum(state.stages[n].estimated_cost_usd for n in STAGE_NAMES)
    db_row = (
        get_db()
        .table("projects")
        .select("share_token, is_public")
        .eq("user_id", user_id)
        .eq("id", project_id)
        .execute()
    )
    share_rows = _rows(db_row)
    share_info = share_rows[0] if share_rows else {}

    return {
        "id": project_id,
        "project_name": state.project_name,
        "created_at": state.created_at.isoformat(),
        "total_cost_credits": provider_usd_to_credits(state.total_cost_usd),
        "misc_cost_credits": provider_usd_to_credits(state.misc_cost_usd),
        "total_estimated_cost_credits": provider_usd_to_credits(total_estimated),
        "is_running": running,
        "active_jobs": active_jobs,
        "has_cover": _cover_path(project_dir).exists(),
        "style_selected": style_selected,
        "is_public": share_info.get("is_public", False),
        "share_token": share_info.get("share_token"),
        "stages": stages,
        "page_count": _target_page_count(project_dir),
        "page_issue_summary": _target_issue_summary(project_dir),
        "finish_ready": _finish_ready(project_dir),
    }


@router.get("/{project_id}/cover-estimate")
def project_cover_estimate(
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the credit estimate for the project's background cover image."""
    _project_dir, config, _state = project
    return _project_cover_credit_estimate(config)


@router.post("/{project_id}/cover")
@limiter.limit(cost_limit)
async def generate_cover(
    request: Request,
    project_id: str,
    force: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    return enqueue_project_cover(request, project_id, project, user_id, force=force)


def enqueue_project_cover(request: Request, project_id: str, project, user_id: str, *, force: bool = False):
    """Shared HTTP and post-Cast orchestration; generation stays in its own job."""
    from novel_to_comic.artifacts import character_ref_sheet_path

    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    cover_path = _cover_path(project_dir)
    if cover_path.exists() and not force:
        return {"status": "exists", "path": "cover/cover.png", "job": None}

    if not (project_dir / "story_bible.json").exists():
        raise HTTPException(404, "Story bible not found — run extract first.")

    existing = _active_project_cover_job(request, pkey)
    if existing:
        return {
            "status": "queued",
            "path": "cover/cover.png",
            "job": generation_job_payload(request.app, existing),
        }

    # Reject missing inputs before publishing a paid job or reserving credits.
    bible = StoryBible.model_validate_json((project_dir / "story_bible.json").read_text())
    missing = [
        char.name for char in bible.characters[:3]
        if not character_ref_sheet_path(project_dir, char.id).exists()
    ]
    if missing:
        raise HTTPException(409, "Generate character references before creating the cover: " + ", ".join(missing))
    cover_estimate = _project_cover_credit_estimate(config)

    async def _runner():
        return await _generate_project_cover(config, project_dir, user_id, project_id)

    prune_finished_generation_jobs(request.app)
    from ..credited_job import enqueue_credited_job

    from ..job_commands import command
    job, _created = enqueue_credited_job(
        request.app,
        project_name=pkey,
        kind="project_cover",
        label=f"{state.project_name} cover",
        payload={"path": "cover/cover.png"},
        work=_runner,
        command=command("cover", project_dir, config),
        project_id=project_id,
        project_dir=project_dir,
        stage="cover",
        estimate_credits=cover_estimate["estimate_credits"],
        operations=image_operations(config),
        debit_description="Model call: project cover",
        user_id=user_id,
        semaphore=generation_semaphore_for_config(request.app, config),
    )
    return {
        "status": "queued",
        "path": "cover/cover.png",
        "job": generation_job_payload(request.app, job),
    }


@router.delete("/{project_id}")
def delete_project(
    request: Request,
    project_id: str,
    project_dir: Path = Depends(get_project_dir),
    user_id: str = Depends(get_current_user),
):
    if _is_project_running(user_id, project_id, request):
        raise HTTPException(409, "Cannot delete a project while a stage is running")

    get_db().table("projects").delete().eq("user_id", user_id).eq(
        "id", project_id
    ).execute()
    try:
        shutil.rmtree(project_dir)
    except OSError as exc:
        # DB row already removed; filesystem cleanup is best-effort. A stranded
        # dir can be reclaimed later — don't fail the already-committed delete.
        logger.warning("Could not remove project directory %s: %s", project_dir, exc)
    return {"status": "deleted", "id": project_id}


@router.get("/short-stories")
async def list_short_stories():
    global _story_catalog_cache, _story_catalog_last_fetch
    now = time.time()
    if (
        _story_catalog_cache is not None
        and (now - _story_catalog_last_fetch) < _CACHE_EXPIRY
    ):
        return _story_catalog_cache

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://www.libraryofshortstories.com/storylist-reduced"
            )
            r.raise_for_status()
            data = r.json()
            _story_catalog_cache = data
            _story_catalog_last_fetch = now
            return data
    except Exception as exc:
        logger.exception("Failed to fetch short story catalog")
        if _story_catalog_cache is not None:
            return _story_catalog_cache
        raise HTTPException(502, f"Failed to retrieve story catalog: {exc}") from exc


class ImportStoryRequest(BaseModel):
    name: str
    url_or_code: str
    config_overrides: str | None = None


async def _download_remote_story(url: str) -> bytes:
    """Stream a remote story while enforcing the compressed-byte budget."""
    limit = InputLimits.from_env().remote_compressed_bytes
    content = bytearray()
    async with httpx.AsyncClient(timeout=15.0) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > limit:
                    raise InputLimitError(
                        "Remote story exceeds the compressed download limit.",
                        status_code=413,
                    )
    return bytes(content)


@router.post("/import-story")
@limiter.limit(create_limit)
async def import_short_story(
    request: Request,
    payload: ImportStoryRequest,
    projects_dir: Path = Depends(get_projects_dir),
    user_id: str = Depends(get_current_user),
):
    # Per-user project cap — same guard as POST /, applied here too so the labs
    # import path can't be used to bypass the disk-growth limit. Checked before
    # the external fetch to avoid wasted work for an over-cap user.
    existing = _count_user_projects(user_id)
    if existing >= _max_projects_per_user():
        raise HTTPException(
            409,
            f"You've reached the project limit ({_max_projects_per_user()}). "
            f"Delete an existing project to create a new one.",
        )

    url_or_code = payload.url_or_code.strip()
    match = re.search(r"onlinereader/([a-zA-Z0-9_\-]+)", url_or_code)
    if match:
        story_code = match.group(1)
    else:
        if "/" in url_or_code:
            story_code = url_or_code.split("/")[-1].strip()
        else:
            story_code = url_or_code

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", story_code):
        raise HTTPException(400, "Could not parse a valid story code from input")

    story_url = f"https://www.libraryofshortstories.com/storiesgzip/{story_code}.txt"
    try:
        content_bytes = await _download_remote_story(story_url)
        story_text = decode_remote_story(content_bytes)
    except InputLimitError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to fetch story text from %s", story_url)
        raise HTTPException(502, f"Failed to download story text: {exc}") from exc

    if not story_text.strip():
        raise HTTPException(400, "Story content is empty")

    overrides = {}
    if payload.config_overrides:
        try:
            overrides = json.loads(payload.config_overrides)
        except JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in config_overrides") from None
    try:
        from ..account_models import creation_config
        config = creation_config(overrides, projects_dir, user_id)
    except Exception as exc:
        raise HTTPException(400, "Invalid project configuration.") from exc

    slug = _slugify(payload.name)
    try:
        project_dir = project_directory(projects_dir, user_id, slug)
    except ValueError as exc:
        raise HTTPException(409, "Project storage is unavailable") from exc
    if project_dir.exists():
        raise HTTPException(409, f"Project '{slug}' already exists")

    project_dir.mkdir(parents=True)
    for subdir in [
        "input",
        "source",
        "brief",
        "samples",
        "refs",
        "plates",
        "adapt",
        "plan",
        "draw",
        "finish",
        "exports",
        "cover",
    ]:
        (project_dir / subdir).mkdir()

    dst = project_dir / "input" / f"{story_code}.txt"
    dst.write_text(story_text, encoding="utf-8")

    save_config(config, project_dir)

    state = create_initial_state(payload.name, str(dst))
    save_state(state, project_dir)

    (project_dir / ".env.example").write_text(
        "# AI gateway keys — copy to a .env at your repo root (not per-project).\n"
        "# The pipeline walks up from any project dir to find the nearest .env.\n"
        "# Never commit the real .env — add it to your root .gitignore.\n\n"
        "LITELLM_BASE_URL=http://localhost:4000\n"
        "LITELLM_API_KEY=sk-local-canary\n"
        "AI_BILL_FAILED_REQUESTS=provider_usage_only\n"
    )

    try:
        db_result = (
            get_db()
            .table("projects")
            .insert({"user_id": user_id, "name": slug})
            .execute()
        )
        inserted = _rows(db_result)
        project_id = inserted[0]["id"] if inserted else None
    except Exception as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        logger.exception(
            "Failed to register imported project %s for user %s", slug, user_id
        )
        raise HTTPException(
            500, "Failed to register project. Please try again."
        ) from exc

    capture_server_event(
        "project_created",
        user_id=user_id,
        project_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        properties={"source": "sample", "file_type": "txt"},
    )

    return {
        "id": project_id,
        "name": slug,
        "project_name": payload.name,
        "status": "created",
    }
