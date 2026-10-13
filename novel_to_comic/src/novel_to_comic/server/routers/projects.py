"""Project listing, creation, display names, and pipeline status."""

from __future__ import annotations

from ..cover_operations import (_cover_path, _latest_project_cover_job, _project_cover_credit_estimate, _recovered_cover_jobs, enqueue_project_cover)


import asyncio
import json
import hashlib
import logging
import os
import re
import shutil
import tempfile
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

from novel_to_comic.config import Config, save_config
from novel_to_comic.input_limits import (
    InputLimitError,
    InputLimits,
    decode_remote_story,
    read_source,
)
from novel_to_comic import sample_library
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import (
    STAGE_NAMES,
    StageState,
    StageStatus,
    is_stale,
    load_state,
    save_state,
)
from novel_to_comic.series import initialize_series
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import FIRST_PART_ID

from ..auth import get_current_user
from ..credits import (
    provider_usd_to_credits,
)
from ..db import get_db
from ..deps import _ensure_series_layout, get_project, get_project_dir, get_projects_dir, project_key
from ..project_paths import project_directory
from ..ratelimit import cost_limit, create_limit, limiter, preview_limit
from ..product_events import capture_server_event
from .styles import clear_style_failures_after_selection, is_style_selected
from ..generation_jobs import (
    generation_job_payload,
    generation_jobs_snapshot,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_INCOMPATIBLE_PROJECT_REASON = (
    "This project was created with an older pipeline version and must be deleted."
)


@router.get("/short-stories")
def list_short_stories():
    return sample_library.catalog() + sample_library.archive_catalog()


@router.get("/short-stories/{code}")
async def read_short_story(code: str):
    sample = sample_library.find(code)
    if sample is not None:
        _entry, text = sample
        return {"code": code, "text": text}
    if sample_library.find_archive(code) is None:
        raise HTTPException(404, "Sample story not found")
    try:
        content = await _download_remote_story(
            f"https://www.libraryofshortstories.com/storiesgzip/{code}.txt"
        )
        text = decode_remote_story(content)
    except InputLimitError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to read classic archive story %s", code)
        raise HTTPException(502, "The classic archive story is unavailable") from exc
    if not text.strip():
        raise HTTPException(502, "The classic archive story is empty")
    return {"code": code, "text": text}


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
        "snapshot": s.snapshot,
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














def _project_cover_job_payload(request: Request, pkey: str, project_dir: Path) -> dict | None:
    job = _latest_project_cover_job(request, pkey, project_dir)
    if job is not None:
        return generation_job_payload(request.app, job)
    return max(
        _recovered_cover_jobs(request, pkey, project_dir),
        key=lambda job: job["queued_at"],
        default=None,
    )




def _story_bible_author(project_dir: Path) -> str | None:
    from novel_to_comic import artifacts

    bible_path = artifacts.story_bible_path(project_dir)
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












_ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".docx", ".epub", ".pdf"}


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


def _save_upload_capped(file: UploadFile, dst: Path, *, account: Path | None = None, budget: dict | None = None) -> None:
    """Stream an upload to disk, aborting (and cleaning up) past the size cap.

    Rejecting via Content-Length alone is unsafe (chunked transfers omit it), so
    we enforce while streaming. Raises 413 on overflow and removes the partial file.
    """
    cap = _max_upload_bytes()
    written = 0
    if account is not None and budget is None:
        from ..storage_budget import usage
        budget = usage(account)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dst, "wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                if account is not None:
                    from ..storage_budget import require_capacity
                    require_capacity(account, written + len(chunk), budget=budget)
                written += len(chunk)
                if written > cap:
                    f.close()
                    dst.unlink(missing_ok=True)
                    limit_mb = cap // (1024 * 1024)
                    raise HTTPException(
                        413, f"Uploaded file exceeds the {limit_mb} MB limit."
                    )
                f.write(chunk)
    except HTTPException:
        dst.unlink(missing_ok=True)
        raise
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


def _word_count(text: str) -> int:
    return len(text.split())


@router.post("/source-preview", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
@limiter.limit(preview_limit)
async def preview_source(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """Read a manuscript the way creation will and report how it would be split.

    Nothing is stored: the staged copy is removed before responding, and the
    parts use the same chapter grouping as project creation.
    """
    from novel_to_comic.chapter_detection import PART_TARGET_CHARACTERS, detect_chapters, group_chapters

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type: {suffix}. Accepted: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )
    with tempfile.TemporaryDirectory(prefix="canary-preview-") as staging:
        staged = Path(staging) / f"source{suffix}"
        _save_upload_capped(file, staged)
        try:
            text = read_source(staged)
        except InputLimitError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
    if not text.strip():
        raise HTTPException(422, "This manuscript has no text.")
    chapters = detect_chapters(text)
    parts = group_chapters(text)
    return {
        "characters": len(text),
        "words": _word_count(text),
        "chapters": len(chapters),
        "part_target_characters": PART_TARGET_CHARACTERS,
        "parts": [
            {"title": title, "characters": len(piece), "words": _word_count(piece)}
            for title, piece in parts
        ],
    }


@router.post("/", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
@limiter.limit(create_limit)
async def create_project(
    request: Request, file: UploadFile = File(...), name: str = Form(...),
    config_overrides: str = Form(None), projects_dir: Path = Depends(get_projects_dir),
    user_id: str = Depends(get_current_user),
):
    def commit():
        from novel_to_comic.artifact_lock import production_lock
        try:
            directory = project_directory(projects_dir, user_id, _slugify(name))
        except ValueError as exc:
            raise HTTPException(409, "Project storage is unavailable") from exc
        # Capacity and the project cap are atomic across all this account's imports.
        with production_lock(directory.parent):
            existed = directory.exists()
            try:
                return _create_project_commit(request, file, name, config_overrides, projects_dir, user_id)
            except BaseException:
                if not existed:
                    shutil.rmtree(directory, ignore_errors=True)
                raise
    return await asyncio.to_thread(commit)


def _create_project_commit(
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
    from ..storage_budget import usage, require_capacity
    budget = usage(user_dir)
    staging_dir = Path(tempfile.mkdtemp(prefix=".incoming-", dir=user_dir))
    safe_filename = Path(file.filename or f"source{suffix}").name
    staged_source = staging_dir / safe_filename
    try:
        _save_upload_capped(file, staged_source, account=user_dir, budget=budget)
        source_text = read_source(staged_source)
    except InputLimitError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except HTTPException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    if not source_text.strip():
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(422, "This manuscript has no text.")

    try:
        require_capacity(user_dir, staged_source.stat().st_size + len(source_text.encode()) + 65536, budget=budget)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    try:
        project_dir.mkdir()
    except FileExistsError:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise HTTPException(409, f"Project '{slug}' already exists") from None

    (project_dir / "input").mkdir()
    dst = project_dir / "input" / safe_filename
    shutil.move(str(staged_source), dst)
    shutil.rmtree(staging_dir, ignore_errors=True)
    save_config(config, project_dir)
    initialize_series(
        project_dir, project_name=name, novel_path=dst, text=source_text,
        origin=safe_filename, auto_split=True,
    )

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

    return {"id": project_id, "name": slug, "project_name": name, "status": "created",
            "part_id": FIRST_PART_ID}


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
            load_state(d)
            _ensure_series_layout(d)
            part_dir = current_part_dir(d)
            state = load_state(part_dir)
        except (ValidationError, JSONDecodeError, UnicodeDecodeError, HTTPException):
            logger.warning(
                "Project %s has state data from an incompatible pipeline version",
                row["id"],
            )
            results.append(_incompatible_project_summary(row, d))
            continue
        from novel_to_comic.workspace import part_id_for_path, part_workspaces

        workspaces = part_workspaces(d) or [d]
        cover_dir = workspaces[0]
        pkey = project_key(user_id, row["id"])
        cover_job = _project_cover_job_payload(request, pkey, cover_dir)
        furthest = None
        for name in STAGE_NAMES:
            if _stage_payload(part_dir, name, state)["status"] in (
                "complete",
                "awaiting_review",
            ):
                furthest = name
        total_cost, _misc = _series_cost_usd(d)
        results.append(
            {
                "id": row["id"],
                "name": row["name"],
                "project_name": state.project_name,
                "author": _story_bible_author(d),
                "created_at": state.created_at.isoformat(),
                "total_cost_credits": provider_usd_to_credits(total_cost),
                "furthest_stage": furthest,
                "is_running": _is_project_running(user_id, row["id"], request),
                "has_cover": _cover_path(cover_dir).exists(),
                "cover_part_id": part_id_for_path(cover_dir),
                "current_part_id": part_id_for_path(part_dir),
                "part_count": len(workspaces),
                "page_count": sum(_target_page_count(workspace) for workspace in workspaces),
                "page_issue_summary": _target_issue_summary(part_dir),
                "finish_ready": _finish_ready(part_dir),
                "cover_job": cover_job,
                "incompatible": False,
                "incompatibility_reason": None,
            }
        )
    return results


class RenameProjectRequest(BaseModel):
    name: str


@router.patch("/{project_id}", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
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


def current_part_dir(root: Path) -> Path:
    """The part a project opens on: the first unfinished part, else the last."""
    from novel_to_comic.workspace import current_part_workspace

    return current_part_workspace(root)


def _series_cost_usd(root: Path, series=None) -> tuple[float, float]:
    """Total and miscellaneous provider cost across the series and its parts."""
    from novel_to_comic.state import load_series_state
    from novel_to_comic.workspace import part_workspaces

    series = series or load_series_state(root)
    total, misc = series.total_cost_usd, series.misc_cost_usd
    for workspace in part_workspaces(root):
        try:
            part = json.loads((workspace / "state.json").read_text())
        except (OSError, JSONDecodeError):
            continue
        total += float(part.get("total_cost_usd") or 0.0)
        misc += float(part.get("misc_cost_usd") or 0.0)
    return total, misc


def _reconcile_series_stages(root: Path, config: Config, running: bool, series) -> bool:
    """Style selection and ready Cast references settle the series stages.

    Returns whether ``series`` (the root's state) changed and was saved.
    """
    changed = False
    style_selected = is_style_selected(root, config)
    if style_selected and clear_style_failures_after_selection(series):
        changed = True
    if (
        not running
        and style_selected
        and series.stages["style"].status == StageStatus.COMPLETE
        and series.stages["cast"].status == StageStatus.PENDING
    ):
        from novel_to_comic.stages.s3_cast import ready_asset_count
        from novel_to_comic.state import complete_stage, hash_style_template

        count = ready_asset_count(config, root)
        if count is not None:
            series.stages["cast"].items_done = count
            series.stages["cast"].items_total = count
            series.style_template_hash = hash_style_template(config.style_template)
            complete_stage(series, "cast")
            changed = True
    if changed:
        save_state(series, root)
    return changed


def _project_status_payload(
    request: Request, project_id: str, root: Path, part_dir: Path, config: Config, user_id: str,
    *, series_state, part_state,
) -> dict:
    """One part's view of the project; for a single-book project root == part_dir."""
    from novel_to_comic.workspace import part_id_for_path
    from ..generation_jobs import job_part_id
    from .parts import part_summaries

    part = part_id_for_path(part_dir)
    from ..admission import project_busy
    key = project_key(user_id, project_id)
    series_busy = project_busy(request.app, key, series=True)
    part_busy = project_busy(request.app, key, part)
    running = part_busy
    if _reconcile_series_stages(root, config, series_busy, series_state) and part_dir != root:
        part_state = load_state(part_dir)
    state = series_state if part_dir == root else part_state
    if not running and _reopen_unapproved_brief(part_dir, state):
        save_state(state, part_dir)
    style_selected = is_style_selected(root, config)
    part = part_id_for_path(part_dir)

    active_jobs = [generation_job_payload(request.app, job)
                   for job in generation_jobs_snapshot(request.app)
                   if job.project_name == project_key(user_id, project_id)
                   and job.status in {"queued", "running"}
                   and job_part_id(job) in {None, part}]
    active_stages = {job["stage"] for job in active_jobs}
    stages = {}
    for name in STAGE_NAMES:
        stages[name] = _stage_payload(
            part_dir, name, state, is_task_alive=name in active_stages
        )
    stages["cast"]["approval_blocker"] = None
    stages["cast"]["failures"] = []
    if not running and state.stages["cast"].status in {
        StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE, StageStatus.FAILED,
    }:
        from novel_to_comic.stages.s3_cast import cast_approval_blocker, cast_failure_details
        stages["cast"]["approval_blocker"] = cast_approval_blocker(config, root, state.stages["cast"])
        stages["cast"]["failures"] = cast_failure_details(root, state.stages["cast"])
    total_estimated = sum(state.stages[n].estimated_cost_usd for n in STAGE_NAMES)
    total_cost, misc_cost = _series_cost_usd(root, series_state)
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
        "total_cost_credits": provider_usd_to_credits(total_cost),
        "misc_cost_credits": provider_usd_to_credits(misc_cost),
        "total_estimated_cost_credits": provider_usd_to_credits(total_estimated),
        "is_running": running,
        "part_busy": part_busy,
        "series_busy": series_busy,
        "active_jobs": active_jobs,
        "has_cover": _cover_path(part_dir).exists(),
        "style_selected": style_selected,
        "is_public": share_info.get("is_public", False),
        "share_token": share_info.get("share_token"),
        "stages": stages,
        "page_count": _target_page_count(part_dir),
        "page_issue_summary": _target_issue_summary(part_dir),
        "finish_ready": _finish_ready(part_dir),
        "part_id": part,
        "parts": part_summaries(root),
    }


@router.get("/{project_id}/status")
def project_status(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """The project opened on its current part (see ``current_part_dir``)."""
    root, config, state = project
    part_dir = current_part_dir(root)
    return _project_status_payload(
        request, project_id, root, part_dir, config, user_id,
        series_state=state, part_state=state if part_dir == root else load_state(part_dir),
    )


@router.get("/{project_id}/parts/{part_id}/status")
def part_status(
    request: Request,
    project_id: str,
    part_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    part_dir, config, state = project
    from novel_to_comic.state import load_series_state
    from novel_to_comic.workspace import series_root

    root = series_root(part_dir)
    series_state = state if root == part_dir else load_series_state(root)
    return _project_status_payload(
        request, project_id, root, part_dir, config, user_id,
        series_state=series_state, part_state=state,
    )


@router.get("/{project_id}/parts/{part_id}/cover-estimate")
def project_cover_estimate(
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — auth gate
):
    """Return the credit estimate for the project's background cover image."""
    _project_dir, config, _state = project
    return _project_cover_credit_estimate(config)


@router.post("/{project_id}/parts/{part_id}/cover", openapi_extra={'x-canary-action': {'spends': True, 'dispatches': True}})
@limiter.limit(cost_limit)
async def generate_cover(
    request: Request,
    project_id: str,
    force: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    return await enqueue_project_cover(request, project_id, project, user_id, force=force)




@router.delete("/{project_id}", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def delete_project(
    request: Request,
    project_id: str,
    project_dir: Path = Depends(get_project_dir),
    user_id: str = Depends(get_current_user),
):
    if _is_project_running(user_id, project_id, request):
        raise HTTPException(409, "Cannot delete a project while a stage is running")

    from .. import publications
    from novel_to_comic.artifact_lock import production_lock

    with production_lock(publications.root(request.app.state.projects_dir)):
        get_db().table("projects").delete().eq("user_id", user_id).eq(
            "id", project_id
        ).execute()
        try:
            shutil.rmtree(project_dir)
        except OSError as exc:
            # DB row already removed; filesystem cleanup is best-effort. A stranded
            # dir can be reclaimed later — don't fail the already-committed delete.
            logger.warning("Could not remove project directory %s: %s", project_dir, exc)
        owner = publications.read_json(publications.owner_path(request.app.state.projects_dir, user_id, project_id))
        if owner:
            (publications.root(request.app.state.projects_dir) / owner["id"] / "current.json").unlink(missing_ok=True)
    return {"status": "deleted", "id": project_id}


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


@router.post("/import-story", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
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
    existing = await asyncio.to_thread(_count_user_projects, user_id)
    if existing >= _max_projects_per_user():
        raise HTTPException(
            409,
            f"You've reached the project limit ({_max_projects_per_user()}). "
            f"Delete an existing project to create a new one.",
        )

    url_or_code = payload.url_or_code.strip()
    bundled = sample_library.find(url_or_code)
    match = re.fullmatch(
        r"https?://(?:www\.)?libraryofshortstories\.com/onlinereader/([a-zA-Z0-9_-]+)/?",
        url_or_code,
    )
    story_code = bundled[0]["code"] if bundled else match.group(1) if match else url_or_code

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,200}", story_code):
        raise HTTPException(400, "Could not parse a valid story code from input")
    archive_entry = None if bundled else sample_library.find_archive(story_code)

    if bundled:
        story_text = bundled[1]
    else:
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

    def commit():
        from ..storage_budget import ingestion
        with ingestion(project_dir, 2 * len(story_text.encode()) + 65536):
            if _count_user_projects(user_id) >= _max_projects_per_user():
                raise HTTPException(409, "Project limit reached. Delete a project before importing another.")
            if project_dir.exists():
                raise HTTPException(409, f"Project '{slug}' already exists")
            try:
                project_dir.mkdir(parents=True)
                (project_dir / "input").mkdir()
                dst = project_dir / "input" / f"{story_code}.txt"
                dst.write_text(story_text, encoding="utf-8")

                save_config(config, project_dir)
                initialize_series(
                    project_dir, project_name=payload.name, novel_path=dst,
                    text=read_source(dst), origin=dst.name,
                )
                if bundled or archive_entry:
                    entry = bundled[0] if bundled else archive_entry
                    assert entry is not None
                    (project_dir / "sample_source.json").write_text(
                        json.dumps({
                            "code": entry["code"],
                            "title": entry["title"],
                            "author": entry["author"],
                            "source_kind": "curated" if bundled else "archive",
                            "license": entry.get("license"),
                            "license_url": entry.get("license_url"),
                            "source_url": entry["source_url"],
                            "text_source_url": entry.get("text_source_url", f"https://www.libraryofshortstories.com/storiesgzip/{story_code}.txt"),
                            "attribution_url": entry.get("attribution_url"),
                            "sha256": entry["sha256"] if bundled else hashlib.sha256(story_text.encode("utf-8")).hexdigest(),
                            "source_note": entry.get("source_note"),
                            "rights_note": entry.get("rights_note"),
                        }, indent=2) + "\n",
                        encoding="utf-8",
                    )

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
            except BaseException:
                shutil.rmtree(project_dir, ignore_errors=True)
                raise

    return await asyncio.to_thread(commit)
