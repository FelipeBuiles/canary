"""Active global Plan stage."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic.clients.text import generate_json
from novel_to_comic.config import Config
from novel_to_comic.models.page import (
    ApprovedPageRange,
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
)
from novel_to_comic.page_planning import build_book_plan_prompt, produce_book_plan
from novel_to_comic.page_drawing import ApprovedReferenceFile
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import estimate_text_cost
from novel_to_comic import artifacts

from novel_to_comic.stages import Stage, clean_cascade


def approved_visual_inventory(project_dir: Path) -> ApprovedVisualReferenceInventory:
    bible = artifacts.read_story_bible(project_dir)
    references = []
    for entity in (*bible.characters, *bible.locations, *bible.props):
        references.append(
            ApprovedVisualReference(
                id=f"{entity.id}:base",
                entity_id=entity.id,
                visual_anchor=entity.visual_anchor,
            )
        )
        for appearance in getattr(entity, "appearance_states", ()):
            references.append(
                ApprovedVisualReference(
                    id=f"{entity.id}:{appearance.id}",
                    entity_id=entity.id,
                    appearance_state_id=appearance.id,
                    visual_anchor=appearance.visual_anchor,
                )
            )
    return ApprovedVisualReferenceInventory(references=references)


def approved_reference_files(
    project_dir: Path,
) -> dict[str, ApprovedReferenceFile]:
    bible = artifacts.read_story_bible(project_dir)
    selected_poses = artifacts.read_primary_refs(project_dir)
    files: dict[str, ApprovedReferenceFile] = {}
    for character in bible.characters:
        pose = selected_poses.get(character.id)
        path = (
            artifacts.character_ref_pose_path(project_dir, character.id, pose)
            if pose in artifacts.CHARACTER_REF_POSES
            else artifacts.character_ref_sheet_path(project_dir, character.id)
        )
        files[f"{character.id}:base"] = ApprovedReferenceFile(
            reference_id=f"{character.id}:base",
            path=path,
            media_type="image/png",
        )
        for appearance in character.appearance_states:
            reference_id = f"{character.id}:{appearance.id}"
            files[reference_id] = ApprovedReferenceFile(
                reference_id=reference_id,
                path=artifacts.character_state_ref_sheet_path(
                    project_dir,
                    character.id,
                    appearance.id,
                ),
                media_type="image/png",
            )
    for location in bible.locations:
        files[f"{location.id}:base"] = ApprovedReferenceFile(
            reference_id=f"{location.id}:base",
            path=artifacts.location_plate_path(project_dir, location.id),
            media_type="image/png",
        )
        for appearance in location.appearance_states:
            reference_id = f"{location.id}:{appearance.id}"
            files[reference_id] = ApprovedReferenceFile(
                reference_id=reference_id,
                path=artifacts.location_state_plate_path(
                    project_dir,
                    location.id,
                    appearance.id,
                ),
                media_type="image/png",
            )
    for prop in bible.props:
        files[f"{prop.id}:base"] = ApprovedReferenceFile(
            reference_id=f"{prop.id}:base",
            path=artifacts.prop_ref_path(project_dir, prop.id),
            media_type="image/png",
        )
    return files


async def run(config: Config, project_dir: Path, ctx: StageRuntime):
    target = TargetArtifacts(project_dir)
    brief = target.read_brief()
    model = config.effective_plan_model()

    async def generate(**kwargs):
        kwargs.pop("json_schema", None)
        return await generate_json(config=config, model=model, **kwargs)

    return await produce_book_plan(
        target.read_adaptation(),
        approved_visual_inventory(project_dir),
        ApprovedPageRange(
            minimum=brief.target_page_min,
            maximum=brief.target_page_max,
        ),
        artifacts=target,
        ctx=ctx,
        model=model,
        generate=generate,
    )


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    target = TargetArtifacts(project_dir)
    if not target.adaptation_path.exists() or not target.brief_path.exists():
        return 0.0
    brief = target.read_brief()
    prompt = build_book_plan_prompt(
        target.read_adaptation(),
        approved_visual_inventory(project_dir),
        ApprovedPageRange(
            minimum=brief.target_page_min,
            maximum=brief.target_page_max,
        ),
    )
    return estimate_text_cost(
        config.effective_plan_model(),
        prompt,
        output_chars=max(8_000, len(target.read_adaptation().beats) * 2_000),
    )


STAGE = Stage(
    name="plan",
    run=run,
    outputs=lambda d: [TargetArtifacts(d).plan_path, d / "plan" / "pages"],
    clean_paths=lambda d: clean_cascade(d, "plan"),
    estimate_cost=estimate_cost,
)
