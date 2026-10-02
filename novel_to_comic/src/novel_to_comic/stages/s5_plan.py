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
from novel_to_comic.page_planning import (
    estimate_book_plan_cost,
    produce_book_plan,
)
from novel_to_comic.models.story_bible import MissingVisualAnchor, blank_visual_anchors
from novel_to_comic.page_drawing import ApprovedReferenceFile
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic import artifacts

from novel_to_comic.stages import Stage, clean_cascade


def reference_id(entity_id: str, appearance_state_id: str | None = None) -> str:
    """The one spelling of an approved reference's identity.

    The inventory Plan validates against and the Cast bytes Draw uploads are
    matched by this string, so both sides must derive it from here rather than
    formatting it independently.
    """

    return f"{entity_id}:{appearance_state_id or 'base'}"


def approved_visual_inventory(project_dir: Path) -> ApprovedVisualReferenceInventory:
    bible = artifacts.read_story_bible(project_dir)
    if blank := blank_visual_anchors(bible):
        raise MissingVisualAnchor(blank)
    references = []
    kinds = (("character", bible.characters), ("location", bible.locations), ("prop", bible.props))
    for kind, entities in kinds:
        for entity in entities:
            references.append(
                ApprovedVisualReference(
                    id=reference_id(entity.id),
                    entity_id=entity.id,
                    visual_anchor=entity.visual_anchor,
                    label=entity.name,
                    kind=kind,
                )
            )
            for appearance in getattr(entity, "appearance_states", ()):
                references.append(
                    ApprovedVisualReference(
                        id=reference_id(entity.id, appearance.id),
                        entity_id=entity.id,
                        appearance_state_id=appearance.id,
                        visual_anchor=appearance.visual_anchor,
                        label=entity.name,
                        continuity_guard=appearance.continuity_guard or "",
                        kind=kind,
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
        files[reference_id(character.id)] = ApprovedReferenceFile(
            reference_id=reference_id(character.id),
            path=path,
            media_type="image/png",
            metadata_path=artifacts.asset_meta_path(artifacts.character_ref_sheet_path(project_dir, character.id)),
        )
        for appearance in character.appearance_states:
            state_reference = reference_id(character.id, appearance.id)
            appearance_path = (
                path
                if appearance.canonical_equivalent
                or not appearance.visually_significant
                else artifacts.character_state_ref_sheet_path(
                    project_dir,
                    character.id,
                    appearance.id,
                )
            )
            files[state_reference] = ApprovedReferenceFile(
                reference_id=state_reference,
                path=appearance_path,
                media_type="image/png",
                metadata_path=artifacts.asset_meta_path(
                    artifacts.character_ref_sheet_path(project_dir, character.id)
                    if appearance.canonical_equivalent or not appearance.visually_significant
                    else appearance_path
                ),
            )
    for location in bible.locations:
        files[reference_id(location.id)] = ApprovedReferenceFile(
            reference_id=reference_id(location.id),
            path=artifacts.location_plate_path(project_dir, location.id),
            media_type="image/png",
        )
        for appearance in location.appearance_states:
            state_reference = reference_id(location.id, appearance.id)
            appearance_path = (
                artifacts.location_plate_path(project_dir, location.id)
                if appearance.canonical_equivalent
                or not appearance.visually_significant
                else artifacts.location_state_plate_path(
                    project_dir,
                    location.id,
                    appearance.id,
                )
            )
            files[state_reference] = ApprovedReferenceFile(
                reference_id=state_reference,
                path=appearance_path,
                media_type="image/png",
            )
    for prop in bible.props:
        files[reference_id(prop.id)] = ApprovedReferenceFile(
            reference_id=reference_id(prop.id),
            path=artifacts.prop_ref_path(project_dir, prop.id),
            media_type="image/png",
        )
        for appearance in prop.appearance_states:
            state_reference = reference_id(prop.id, appearance.id)
            files[state_reference] = ApprovedReferenceFile(
                reference_id=state_reference,
                path=(artifacts.prop_ref_path(project_dir, prop.id)
                      if appearance.canonical_equivalent or not appearance.visually_significant
                      else artifacts.prop_state_ref_path(project_dir, prop.id, appearance.id)),
                media_type="image/png",
            )
    return files


async def run(config: Config, project_dir: Path, ctx: StageRuntime):
    from novel_to_comic.editorial import (
        load_story_directive,
        mark_story_change_applied,
    )

    target = TargetArtifacts(project_dir)
    brief = target.read_brief()
    from novel_to_comic.narrative_review import adaptation_context, require_narrative_review
    require_narrative_review(target, "adapt", adaptation_context(target.read_source(), brief, target.read_adaptation()))
    # One-shot layout/pacing input from an explicitly applied story change.
    # The instruction travels inside Plan's prompts under a hard constraint:
    # Plan reallocates pages but never rewrites Adapt's lettering. It is
    # retained across a failed run for explicit retry and cleared only after
    # the regenerated plan is persisted.
    directive = load_story_directive(target, "plan")
    instruction = directive.instruction if directive is not None else ""
    model = config.effective_plan_model()

    async def generate(**kwargs):
        return await generate_json(
            config=config,
            model=model,
            temperature=0.25,
            **kwargs,
        )

    result = await produce_book_plan(
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
        max_generation_calls=config.narrative_max_calls,
        story_instruction=instruction,
        concurrency=config.effective_text_concurrency(),
    )
    if directive is not None:
        target.clear_story_directive("plan")
        mark_story_change_applied(target, directive.proposal_id)
    return result


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    target = TargetArtifacts(project_dir)
    if not target.adaptation_path.exists() or not target.brief_path.exists():
        return 0.0
    brief = target.read_brief()
    directive = target.peek_story_directive("plan")
    return estimate_book_plan_cost(
        target.read_adaptation(),
        approved_visual_inventory(project_dir),
        ApprovedPageRange(
            minimum=brief.target_page_min,
            maximum=brief.target_page_max,
        ),
        model=config.effective_plan_model(),
        story_instruction=directive.instruction if directive is not None else "",
    )


STAGE = Stage(
    name="plan",
    run=run,
    outputs=lambda d: [TargetArtifacts(d).plan_path, d / "plan" / "pages"],
    clean_paths=lambda d: clean_cascade(d, "plan"),
    estimate_cost=estimate_cost,
)
