"""Project listing, creation, and pipeline status."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form

from novel_to_comic.config import Config, save_config
from novel_to_comic.ai import ai_request_context
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import STAGE_NAMES, StageStatus, create_initial_state, is_stale, load_state, save_state

from ..auth import get_current_user
from ..credits import debit_model_usage, provider_usd_to_credits
from ..db import get_db
from ..deps import get_project, get_projects_dir, project_key
from .styles import is_style_selected
from ..generation_jobs import (
    enqueue_generation_job,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _draw_prompt_files(project_dir: Path, config: Config) -> list[Path]:
    prompts_dir = project_dir / "direct"
    if not prompts_dir.exists():
        return []
    scene_dirs = sorted(d for d in prompts_dir.iterdir() if d.is_dir())
    if config.dev_mode:
        scene_dirs = scene_dirs[:1]
    return [prompt for scene_dir in scene_dirs for prompt in sorted(scene_dir.glob("panel_*.json"))]


def _draw_output_path_for_prompt(project_dir: Path, prompt_path: Path) -> Path | None:
    try:
        prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
        return project_dir / "draw" / prompt.scene_id / f"panel_{prompt.panel_number:03d}.png"
    except Exception:
        match = re.match(r"panel_(\d+)$", prompt_path.stem)
        if not match:
            return None
        return project_dir / "draw" / prompt_path.parent.name / f"panel_{int(match.group(1)):03d}.png"


def _reconcile_completed_draw_stage(project_dir: Path, config: Config, state, *, is_running: bool) -> bool:
    """Recover draw state when images were written but the final state save was missed."""
    draw_state = state.stages["draw"]
    if is_running or draw_state.status != StageStatus.RUNNING:
        return False

    prompt_files = _draw_prompt_files(project_dir, config)
    if not prompt_files:
        return False

    output_paths = [
        output_path
        for prompt_path in prompt_files
        if (output_path := _draw_output_path_for_prompt(project_dir, prompt_path)) is not None
    ]
    if len(output_paths) != len(prompt_files):
        return False

    completed_paths = [
        output_path
        for output_path in output_paths
        if output_path.exists() and not output_path.with_suffix(f"{output_path.suffix}.failure.json").exists()
    ]
    if len(completed_paths) != len(prompt_files):
        return False

    draw_state.items_done = len(completed_paths)
    draw_state.items_total = len(prompt_files)
    draw_state.items_failed = []
    draw_state.status = StageStatus.AWAITING_REVIEW
    draw_state.finished_at = draw_state.finished_at or datetime.now(timezone.utc)
    draw_state.error = None
    return True


def _assemble_artifact_error(project_dir: Path) -> str | None:
    """Return a user-facing reason when a completed assemble stage is unusable."""
    page_json = list((project_dir / "compose" / "pages").glob("page_*.json"))
    if page_json:
        return None

    legacy_png = list((project_dir / "pages").glob("page_*.png"))
    if legacy_png:
        return (
            "Missing editable page JSON in assembly/pages. Found legacy rendered "
            "PNGs in pages/. Re-run the assemble stage with the current pipeline."
        )

    return "Missing editable page JSON in assembly/pages. Re-run the assemble stage."


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

    if name == "compose" and status == "complete":
        artifact_error = _assemble_artifact_error(project_dir)
        if artifact_error:
            status = "failed"
            error = artifact_error

    # Ground truth for liveness: if the asyncio task is alive, the stage
    # cannot be stale regardless of how long it's been since the last
    # state.json save. The wall-clock heuristic in is_stale() only fires
    # when the task is gone (server restart, crash).
    stale = is_stale(s) and not is_task_alive

    return {
        "status": status,
        "items_done": s.items_done,
        "items_total": s.items_total,
        "items_failed": s.items_failed,
        "cost_credits": provider_usd_to_credits(s.cost_usd),
        "estimated_cost_credits": provider_usd_to_credits(s.estimated_cost_usd),
        "error": error,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "last_progress_at": s.last_progress_at.isoformat() if s.last_progress_at else None,
        "stale": stale,
        "in_flight": in_flight or [],
    }


def _is_project_running(user_id: str, project_id: str, request: Request) -> bool:
    key = project_key(user_id, project_id)
    task = request.app.state.running_tasks.get(key)
    return task is not None and not task.done()


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


def _story_bible_author(project_dir: Path) -> str | None:
    bible_path = project_dir / "story_bible.json"
    if not bible_path.exists():
        return None
    try:
        return StoryBible.model_validate_json(bible_path.read_text()).author
    except Exception:
        return None


def _find_style_ref(project_dir: Path, style_template: str) -> Path | None:
    suggestions_path = project_dir / "samples" / "style_suggestions.json"
    if suggestions_path.exists():
        try:
            data = json.loads(suggestions_path.read_text())
            for i, suggestion in enumerate(data.get("suggestions", []), 1):
                if isinstance(suggestion, dict) and suggestion.get("template", "").strip() == style_template.strip():
                    sample = project_dir / "samples" / f"style_{i}.png"
                    if sample.exists():
                        return sample
        except Exception:
            pass
    for i in range(1, 20):
        sample = project_dir / "samples" / f"style_{i}.png"
        if sample.exists():
            return sample
    return None


def _cover_prompt(config: Config, bible: StoryBible) -> str:
    characters = "; ".join(
        f"{c.name}: {c.visual_anchor[:180]}"
        for c in bible.characters[:3]
    )
    locations = "; ".join(
        f"{loc.name}: {loc.visual_anchor[:160]}"
        for loc in bible.locations[:2]
    )
    return (
        f"{config.style_template}\n\n"
        f"Book cover illustration for {bible.title} by {bible.author}. "
        f"Feature the central mood and conflict of the story without text, title, logos, captions, or typography. "
        f"Key characters: {characters or 'the central protagonist'}. "
        f"Key settings: {locations or 'the primary story world'}. "
        f"Portrait cover composition, one strong focal image, cinematic lighting, finished production art, no words."
    )


async def _generate_project_cover(
    config: Config,
    project_dir: Path,
    user_id: str,
    project_id: str | None,
) -> Path:
    from novel_to_comic.clients import flux
    from novel_to_comic.state import load_state, record_misc_usage, save_state

    bible_path = project_dir / "story_bible.json"
    if not bible_path.exists():
        raise FileNotFoundError("Story bible not found")

    bible = StoryBible.model_validate_json(bible_path.read_text())
    output_path = _cover_path(project_dir)
    style_ref = _find_style_ref(project_dir, config.style_template)
    with ai_request_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_dir.name,
        workspace_id=str(project_dir.parent),
        stage="cover",
    ):
        result = await flux.generate_image(
            config=config,
            prompt=_cover_prompt(config, bible),
            output_path=output_path,
            width=768,
            height=1024,
            reference_image_path=style_ref,
            ref_type="style",
            feature="project.cover",
        )
    if result.usage:
        state = load_state(project_dir)
        record_misc_usage(state, result.usage)
        save_state(state, project_dir)
        debit_model_usage(
            get_db(),
            user_id,
            project_id,
            result.usage,
            description="Model call: project cover",
        )
    return output_path


_ALLOWED_EXTENSIONS = {".txt", ".epub", ".pdf"}


def _slugify(name: str) -> str:
    """Turn a display name into a filesystem-safe directory name."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-")
    return slug.lower() or "untitled"


@router.post("/")
async def create_project(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    config_overrides: str = Form(None),
    projects_dir: Path = Depends(get_projects_dir),
    user_id: str = Depends(get_current_user),
):
    # Validate file extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Accepted: {', '.join(sorted(_ALLOWED_EXTENSIONS))}")

    # Build project directory (user-scoped to prevent cross-user collisions)
    slug = _slugify(name)
    project_dir = projects_dir / user_id / slug
    if project_dir.exists():
        raise HTTPException(409, f"Project '{slug}' already exists")

    # Create directory structure
    project_dir.mkdir(parents=True)
    for subdir in ["input", "scenes", "refs", "plates", "adapt", "plan", "storyboard",
                   "direct", "draw", "compose", "exports", "cover"]:
        (project_dir / subdir).mkdir()

    # Save uploaded file
    dst = project_dir / "input" / (file.filename or "novel")
    with open(dst, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Build config with optional overrides
    overrides = {}
    if config_overrides:
        try:
            overrides = json.loads(config_overrides)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON in config_overrides")
    config = Config(**overrides)
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
        db_result = get_db().table("projects").insert({"user_id": user_id, "name": slug}).execute()
        project_id = db_result.data[0]["id"] if db_result.data else None
    except Exception as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        logger.exception("Failed to register project %s for user %s", slug, user_id)
        raise HTTPException(500, "Failed to register project. Please try again.") from exc

    return {"id": project_id, "name": slug, "project_name": name, "status": "created"}


@router.get("/")
def list_projects(
    request: Request,
    projects_dir: Path = Depends(get_projects_dir),
    user_id: str = Depends(get_current_user),
):
    """Return projects owned by the user, ordered by DB created_at."""
    rows = (
        get_db()
        .table("projects")
        .select("id, name, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    results = []
    for row in rows.data:
        d = projects_dir / user_id / row["name"]
        state_file = d / "state.json"
        if not d.is_dir() or not state_file.exists():
            continue  # orphaned DB row — directory missing, skip silently
        state = load_state(d)
        pkey = project_key(user_id, row["id"])
        cover_job = _latest_project_cover_job(request, pkey)
        furthest = None
        for name in STAGE_NAMES:
            if _stage_payload(d, name, state)["status"] in ("complete", "awaiting_review"):
                furthest = name
        results.append({
            "id": row["id"],
            "name": row["name"],
            "project_name": state.project_name,
            "author": _story_bible_author(d),
            "created_at": state.created_at.isoformat(),
            "total_cost_credits": provider_usd_to_credits(state.total_cost_usd),
            "furthest_stage": furthest,
            "is_running": _is_project_running(user_id, row["id"], request),
            "has_cover": _cover_path(d).exists(),
            "cover_job": generation_job_payload(request.app, cover_job) if cover_job else None,
        })
    return results


@router.get("/{project_id}/status")
def project_status(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    running = _is_project_running(user_id, project_id, request)

    # Reconcile draw stage only when a task was running and has just finished.
    # This avoids mutating state on every GET /status poll.
    if not running:
        if _reconcile_completed_draw_stage(project_dir, config, state, is_running=False):
            save_state(state, project_dir)

    pkey = project_key(user_id, project_id)
    draw_in_flight = list(getattr(request.app.state, "draw_in_flight", {}).get(pkey, []))

    stages = {}
    for name in STAGE_NAMES:
        in_flight = draw_in_flight if name == "draw" else None
        stages[name] = _stage_payload(
            project_dir, name, state, is_task_alive=running, in_flight=in_flight
        )
    total_estimated = sum(state.stages[n].estimated_cost_usd for n in STAGE_NAMES)
    db_row = (
        get_db()
        .table("projects")
        .select("share_token, is_public")
        .eq("user_id", user_id)
        .eq("id", project_id)
        .execute()
    )
    share_info = db_row.data[0] if db_row.data else {}

    return {
        "id": project_id,
        "project_name": state.project_name,
        "created_at": state.created_at.isoformat(),
        "total_cost_credits": provider_usd_to_credits(state.total_cost_usd),
        "misc_cost_credits": provider_usd_to_credits(state.misc_cost_usd),
        "total_estimated_cost_credits": provider_usd_to_credits(total_estimated),
        "is_running": running,
        "has_cover": _cover_path(project_dir).exists(),
        "style_selected": is_style_selected(project_dir, config),
        "is_public": share_info.get("is_public", False),
        "share_token": share_info.get("share_token"),
        "stages": stages,
    }


@router.post("/{project_id}/cover")
async def generate_cover(
    request: Request,
    project_id: str,
    force: bool = Query(False),
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
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

    async def _runner() -> None:
        await _generate_project_cover(config, project_dir, user_id, project_id)

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=pkey,
        kind="project_cover",
        label=f"{state.project_name} cover",
        payload={"path": "cover/cover.png"},
        runner=_runner,
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
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    if _is_project_running(user_id, project_id, request):
        raise HTTPException(409, "Cannot delete a project while a stage is running")

    get_db().table("projects").delete().eq("user_id", user_id).eq("id", project_id).execute()
    shutil.rmtree(project_dir)
    return {"status": "deleted", "id": project_id}
