"""Project listing, creation, and pipeline status."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form

from novel_to_comic.config import Config, load_config, save_config
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import STAGE_NAMES, create_initial_state, load_state, save_state

from ..deps import get_project, get_projects_dir
from ..generation_jobs import (
    enqueue_generation_job,
    generation_job_payload,
    prune_finished_generation_jobs,
)

router = APIRouter()


def _assemble_artifact_error(project_dir: Path) -> str | None:
    """Return a user-facing reason when a completed assemble stage is unusable."""
    page_json = list((project_dir / "assembly" / "pages").glob("page_*.json"))
    if page_json:
        return None

    legacy_png = list((project_dir / "pages").glob("page_*.png"))
    if legacy_png:
        return (
            "Missing editable page JSON in assembly/pages. Found legacy rendered "
            "PNGs in pages/. Re-run the assemble stage with the current pipeline."
        )

    return "Missing editable page JSON in assembly/pages. Re-run the assemble stage."


def _stage_payload(project_dir: Path, name: str, state) -> dict:
    s = state.stages[name]
    status = s.status.value
    error = s.error

    if name == "assemble" and status == "complete":
        artifact_error = _assemble_artifact_error(project_dir)
        if artifact_error:
            status = "failed"
            error = artifact_error

    return {
        "status": status,
        "items_done": s.items_done,
        "items_total": s.items_total,
        "items_failed": s.items_failed,
        "cost_usd": s.cost_usd,
        "error": error,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
    }


def _is_project_running(project_name: str, request: Request) -> bool:
    task = request.app.state.running_tasks.get(project_name)
    return task is not None and not task.done()


def _cover_path(project_dir: Path) -> Path:
    return project_dir / "cover" / "cover.png"


def _latest_project_cover_job(request: Request, project_name: str):
    jobs = [
        job
        for job in request.app.state.generation_jobs.values()
        if job.project_name == project_name and job.kind == "project_cover"
    ]
    if not jobs:
        return None
    return max(jobs, key=lambda job: job.sequence)


def _active_project_cover_job(request: Request, project_name: str):
    for job in request.app.state.generation_jobs.values():
        if (
            job.project_name == project_name
            and job.kind == "project_cover"
            and job.status in ("queued", "running")
        ):
            return job
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


async def _generate_project_cover(config: Config, project_dir: Path) -> Path:
    from novel_to_comic.clients import flux

    bible_path = project_dir / "story_bible.json"
    if not bible_path.exists():
        raise FileNotFoundError("Story bible not found")

    bible = StoryBible.model_validate_json(bible_path.read_text())
    output_path = _cover_path(project_dir)
    style_ref = _find_style_ref(project_dir, config.style_template)
    await flux.generate_image(
        config=config,
        prompt=_cover_prompt(config, bible),
        output_path=output_path,
        width=768,
        height=1024,
        reference_image_path=style_ref,
        ref_type="style",
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
):
    # Validate file extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Accepted: {', '.join(sorted(_ALLOWED_EXTENSIONS))}")

    # Build project directory
    slug = _slugify(name)
    project_dir = projects_dir / slug
    if project_dir.exists():
        raise HTTPException(409, f"Project '{slug}' already exists")

    # Create directory structure
    project_dir.mkdir(parents=True)
    for subdir in ["input", "scenes", "refs", "plates", "screenplays", "panels",
                   "prompts", "images", "assembly", "exports", "cover"]:
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
        "# API keys — copy to a .env at your repo root (not per-project).\n"
        "# The pipeline walks up from any project dir to find the nearest .env.\n"
        "# Never commit the real .env — add it to your root .gitignore.\n\n"
        "GEMINI_API_KEY=\n"
        "ANTHROPIC_API_KEY=\n"
        "TOGETHER_API_KEY=\n"
        "OPENAI_API_KEY=\n"
    )

    return {"name": slug, "project_name": name, "status": "created"}


@router.get("/")
def list_projects(request: Request, projects_dir: Path = Depends(get_projects_dir)):
    """Scan projects_dir for subdirectories containing state.json."""
    results = []
    for d in sorted(projects_dir.iterdir()):
        state_file = d / "state.json"
        if not d.is_dir() or not state_file.exists():
            continue
        state = load_state(d)
        cover_job = _latest_project_cover_job(request, d.name)
        # Summarise: furthest completed stage
        furthest = None
        for name in STAGE_NAMES:
            if _stage_payload(d, name, state)["status"] in ("complete", "awaiting_review"):
                furthest = name
        results.append({
            "name": d.name,
            "project_name": state.project_name,
            "created_at": state.created_at.isoformat(),
            "total_cost_usd": state.total_cost_usd,
            "furthest_stage": furthest,
            "is_running": _is_project_running(d.name, request),
            "has_cover": _cover_path(d).exists(),
            "cover_job": generation_job_payload(request.app, cover_job) if cover_job else None,
        })
    return results


@router.get("/{project_name}/status")
def project_status(request: Request, project=Depends(get_project)):
    project_dir, config, state = project
    stages = {}
    for name in STAGE_NAMES:
        stages[name] = _stage_payload(project_dir, name, state)
    return {
        "project_name": state.project_name,
        "created_at": state.created_at.isoformat(),
        "total_cost_usd": state.total_cost_usd,
        "is_running": _is_project_running(project_dir.name, request),
        "has_cover": _cover_path(project_dir).exists(),
        "stages": stages,
    }


@router.post("/{project_name}/cover")
async def generate_cover(
    request: Request,
    project_name: str,
    force: bool = Query(False),
    project=Depends(get_project),
):
    project_dir, config, state = project

    cover_path = _cover_path(project_dir)
    if cover_path.exists() and not force:
        return {"status": "exists", "path": "cover/cover.png", "job": None}

    if not (project_dir / "story_bible.json").exists():
        raise HTTPException(404, "Story bible not found — run extract first.")

    existing = _active_project_cover_job(request, project_name)
    if existing:
        return {
            "status": "queued",
            "path": "cover/cover.png",
            "job": generation_job_payload(request.app, existing),
        }

    async def _runner() -> None:
        async with request.app.state.generation_semaphore:
            await _generate_project_cover(config, project_dir)

    prune_finished_generation_jobs(request.app)
    job = enqueue_generation_job(
        request.app,
        project_name=project_name,
        kind="project_cover",
        label=f"{state.project_name} cover",
        payload={"path": "cover/cover.png"},
        runner=_runner,
    )
    return {
        "status": "queued",
        "path": "cover/cover.png",
        "job": generation_job_payload(request.app, job),
    }
