"""Application operations independent of HTTP routing."""

from __future__ import annotations
import json
import hashlib
from pathlib import Path
from fastapi import HTTPException, Request
from novel_to_comic.ai import ai_request_context
from novel_to_comic.ai.context import current_ai_request_context
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.generation_input import GenerationPromptInput
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
from novel_to_comic.state import load_state, save_state
from novel_to_comic.usage import estimate_image_cost
from .credits import credit_estimate_for_provider_cost
from novel_to_comic.codex_dev import classify_operations, is_subscription
from .codex_admission import image_operations
from .deps import project_key
from .generation_jobs import (
    generation_jobs_snapshot,
    generation_job_payload,
    generation_semaphore_for_config,
    prune_finished_generation_jobs,
    recovered_generation_jobs,
)


def _cover_path(project_dir: Path) -> Path:
    return project_dir / "cover" / "cover.png"


def _cover_jobs(request: Request, pkey: str, project_dir: Path):
    """Cover jobs for the part that ``project_dir`` addresses (each part has one)."""
    from novel_to_comic.workspace import part_id_for_path
    from .generation_jobs import job_part_id

    part = part_id_for_path(project_dir)
    return [
        job
        for job in generation_jobs_snapshot(request.app)
        if job.project_name == pkey
        and job.kind == "project_cover"
        and job_part_id(job) == part
    ]


def _recovered_cover_jobs(request: Request, pkey: str, project_dir: Path) -> list[dict]:
    from novel_to_comic.workspace import part_id_for_path

    part = part_id_for_path(project_dir)
    return [
        job
        for job in recovered_generation_jobs(request.app, pkey)
        if job["kind"] == "project_cover" and job.get("part_id") == part
    ]


def _latest_project_cover_job(request: Request, pkey: str, project_dir: Path):
    jobs = _cover_jobs(request, pkey, project_dir)
    if not jobs:
        return None
    return max(jobs, key=lambda job: job.sequence)


def _active_project_cover_job(request: Request, pkey: str, project_dir: Path):
    return next(
        (
            job
            for job in _cover_jobs(request, pkey, project_dir)
            if job.status in ("queued", "running")
        ),
        None,
    )


def needs_initial_project_cover(request: Request, pkey: str, project_dir: Path) -> bool:
    """Auto-create once; prior attempts require an explicit user retry."""
    return (
        not _cover_path(project_dir).exists()
        and _latest_project_cover_job(request, pkey, project_dir) is None
        and not _recovered_cover_jobs(request, pkey, project_dir)
    )


def _cover_characters(bible: StoryBible, project_dir: Path, limit: int = 3) -> list:
    """The characters most present in this part's scenes, in story order."""
    from novel_to_comic.workspace import part_id_for_path

    part = part_id_for_path(project_dir)
    if part is None:
        return bible.characters[:limit]
    counts: dict[str, int] = {}
    for scene in bible.scenes:
        if scene.part_id == part:
            for character_id in scene.character_ids:
                counts[character_id] = counts.get(character_id, 0) + 1
    order = {character.id: index for index, character in enumerate(bible.characters)}
    ranked = sorted(counts, key=lambda cid: (-counts[cid], order.get(cid, len(order))))
    by_id = {character.id: character for character in bible.characters}
    return [by_id[cid] for cid in ranked if cid in by_id][:limit] or bible.characters[
        :limit
    ]


def _find_style_ref(project_dir: Path, style_template: str) -> Path | None:
    from novel_to_comic.workspace import series_root

    project_dir = series_root(project_dir)
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
    if is_subscription(funding):
        return dict(
            credit_estimate_for_provider_cost(
                0.0, "cast", reserve=False, funding=funding
            )
        )
    if mock_mode_active(config):
        return dict(credit_estimate_for_provider_cost(0.0, "cast", reserve=False))
    return dict(
        credit_estimate_for_provider_cost(
            estimate_image_cost(
                config.effective_image_model(),
                1,
                width=768,
                height=1024,
                quality=getattr(config, "image_quality", None),
            ),
            "cast",
            reserve=False,
            zero_cost_estimate=1,
        )
    )


async def _generate_project_cover(
    config: Config,
    project_dir: Path,
    user_id: str,
    project_id: str | None,
):
    from novel_to_comic import artifacts as story_artifacts
    from novel_to_comic.state import record_misc_usage

    bible_path = story_artifacts.story_bible_path(project_dir)
    if not bible_path.exists():
        raise FileNotFoundError("Story bible not found")

    bible = StoryBible.model_validate_json(bible_path.read_text())
    output_path = _cover_path(project_dir)
    style_ref = _find_style_ref(project_dir, config.style_template)
    cover_cast = _cover_characters(bible, project_dir)
    anchors = tuple(
        PromptAnchor(
            kind="location", entity_id=loc.id, name=loc.name, text=loc.visual_anchor
        )
        for loc in bible.locations[:2]
    )
    input_data = ProjectCoverInput(
        asset_identity="project_cover:cover",
        prompt=GenerationPromptInput(
            anchors=anchors,
            subjects=tuple(
                PromptSubject(
                    character_id=char.id, name=char.name, identity=char.visual_anchor
                )
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
            raise ValueError(
                f"Generate and approve the character reference for {char.name} before creating this cover."
            )
        references.append(
            ReferenceAsset(
                path=path,
                role="subject",
                entity_id=char.id,
                appearance_state_id=None,
                authority_scope=AuthorityScope.FULL_APPEARANCE,
                preserve_facets=("face", "hair", "build", "anatomy", "wardrobe"),
                ignore_facets=(),
                pose=None,
                content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                lineage_parent_sha256=None,
                label=char.name,
            )
        )
    request = compile_non_panel_request(
        config, input_data, reference_plan=reference_plan_for_assets(config, references)
    )
    with ai_request_context(
        user_id=user_id,
        project_id=project_id,
        project_name=project_dir.name,
        workspace_id=str(project_dir.parent),
        stage="cover",
        job_id=current_ai_request_context().job_id,
    ):
        submission = await submit_non_panel_request(
            config=config,
            project_dir=project_dir,
            request=request,
            output_path=output_path,
            feature="project.cover",
            kind="project_cover",
        )
    result = submission.result
    if result is None:
        raise RuntimeError("project cover request was queued without a result")
    if result.usage:
        state = load_state(project_dir)
        record_misc_usage(state, result.usage)
        save_state(state, project_dir)
    return result


async def enqueue_project_cover(
    request: Request, project_id: str, project, user_id: str, *, force: bool = False
):
    """Shared HTTP and post-Draw-start orchestration; generation stays in its own job."""
    from novel_to_comic.artifacts import character_ref_sheet_path

    project_dir, config, state = project
    pkey = project_key(user_id, project_id)

    from novel_to_comic import artifacts as story_artifacts

    cover_path = _cover_path(project_dir)
    if cover_path.exists() and not force:
        return {"status": "exists", "path": "cover/cover.png", "job": None}

    bible_path = story_artifacts.story_bible_path(project_dir)
    if not bible_path.exists():
        raise HTTPException(404, "Story bible not found — run extract first.")

    existing = _active_project_cover_job(request, pkey, project_dir)
    if existing:
        return {
            "status": "queued",
            "path": "cover/cover.png",
            "job": generation_job_payload(request.app, existing),
        }

    # Reject missing inputs before publishing a paid job or reserving credits.
    bible = StoryBible.model_validate_json(bible_path.read_text())
    missing = [
        char.name
        for char in _cover_characters(bible, project_dir)
        if not character_ref_sheet_path(project_dir, char.id).exists()
    ]
    if missing:
        raise HTTPException(
            409,
            "Generate character references before creating the cover: "
            + ", ".join(missing),
        )
    cover_estimate = _project_cover_credit_estimate(config)

    prune_finished_generation_jobs(request.app)
    from .credited_job import enqueue_credited_job

    from .job_commands import command

    job, _created = await enqueue_credited_job(
        request.app,
        project_name=pkey,
        kind="project_cover",
        label=f"{state.project_name} cover",
        payload={"path": "cover/cover.png"},
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
