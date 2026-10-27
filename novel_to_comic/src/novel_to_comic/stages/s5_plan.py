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
from novel_to_comic.models.story_bible import MissingVisualAnchor, StoryBible, blank_visual_anchors
from novel_to_comic.page_drawing import ApprovedReferenceFile
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic import artifacts
from novel_to_comic.cast_roster import cast_character_ids

from novel_to_comic.stages import Stage, clean_cascade


def reference_id(entity_id: str, appearance_state_id: str | None = None) -> str:
    """The one spelling of an approved reference's identity.

    The inventory Plan validates against and the Cast bytes Draw uploads are
    matched by this string, so both sides must derive it from here rather than
    formatting it independently.
    """

    return f"{entity_id}:{appearance_state_id or 'base'}"


def approved_visual_inventory(project_dir: Path, bible: StoryBible | None = None) -> ApprovedVisualReferenceInventory:
    """Every reference the Story Bible names; ``bible`` previews an unsaved edit."""
    bible = bible if bible is not None else artifacts.read_story_bible(project_dir)
    if blank := blank_visual_anchors(bible):
        raise MissingVisualAnchor(blank)
    references = []
    recurring = cast_character_ids(bible, project_dir)
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
                    identity=character_identity(entity) if kind == "character" else "",
                    requires_image=kind != "character" or entity.id in recurring,
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
                        identity=character_identity(entity) if kind == "character" else "",
                        requires_image=kind != "character" or entity.id in recurring,
                    )
                )
    # A scene's described objects (a carved figurine, a figurehead) carry their
    # anchor as written authority so every page that shows them agrees.
    named = {reference.entity_id for reference in references}
    for scene in bible.scenes:
        for item in scene.transient_objects:
            if item.id in named or not item.visual_anchor.strip():
                continue
            named.add(item.id)
            references.append(ApprovedVisualReference(
                id=reference_id(item.id), entity_id=item.id, visual_anchor=item.visual_anchor,
                label=item.name, kind="object", requires_image=False,
            ))
    return ApprovedVisualReferenceInventory(references=references)


def character_identity(character) -> str:
    """Gender, age and unusual stature as one short identity line."""
    return "; ".join(filter(None, (
        " ".join(filter(None, (character.age_range.strip(), character.gender.strip()))),
        f"stature: {character.stature.strip()}" if character.stature.strip() else "",
    )))


def approved_reference_files(
    project_dir: Path,
) -> dict[str, ApprovedReferenceFile]:
    bible = artifacts.read_story_bible(project_dir)
    selected_poses = artifacts.read_primary_refs(project_dir)
    files: dict[str, ApprovedReferenceFile] = {}
    recurring = cast_character_ids(bible, project_dir)

    def image_states(entity) -> dict[str, str | None]:
        """Minor changes inherit the carried visual design, not an earlier outfit.

        Use only explicit chronology and catalog flags. A reusable minor state
        with different declared ancestors keeps the canonical reference; its
        self-contained anchor remains authoritative for every request.
        """
        states = {state.id: state for state in entity.appearance_states}
        order = {scene.id: index for index, scene in enumerate(bible.scenes)}
        carried = None
        parents: dict[str, set[str | None]] = {}
        for activation in sorted(entity.appearance_timeline,
                                 key=lambda item: (order[item.at.scene_id], item.at.beat or 0)):
            state = states[activation.state_id]
            if state.canonical_equivalent:
                carried = None
            elif state.visually_significant:
                carried = state.id
            else:
                parents.setdefault(state.id, set()).add(carried)
        return {state.id: (None if state.canonical_equivalent else state.id if state.visually_significant
                          else next(iter(parents[state.id])) if len(parents.get(state.id, ())) == 1 else None)
                for state in entity.appearance_states}

    for character in bible.characters:
        if character.id not in recurring:
            continue
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
        inherited_images = image_states(character)
        for appearance in character.appearance_states:
            state_reference = reference_id(character.id, appearance.id)
            image_state = inherited_images[appearance.id]
            appearance_path = (
                path
                if image_state is None
                else artifacts.character_state_ref_sheet_path(
                    project_dir,
                    character.id,
                    image_state,
                )
            )
            files[state_reference] = ApprovedReferenceFile(
                reference_id=state_reference,
                path=appearance_path,
                media_type="image/png",
                metadata_path=artifacts.asset_meta_path(
                    artifacts.character_ref_sheet_path(project_dir, character.id)
                    if image_state is None
                    else appearance_path
                ),
            )
    for location in bible.locations:
        files[reference_id(location.id)] = ApprovedReferenceFile(
            reference_id=reference_id(location.id),
            path=artifacts.location_plate_path(project_dir, location.id),
            media_type="image/png",
        )
        inherited_images = image_states(location)
        for appearance in location.appearance_states:
            state_reference = reference_id(location.id, appearance.id)
            image_state = inherited_images[appearance.id]
            appearance_path = (
                artifacts.location_plate_path(project_dir, location.id)
                if image_state is None
                else artifacts.location_state_plate_path(
                    project_dir,
                    location.id,
                    image_state,
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
        inherited_images = image_states(prop)
        for appearance in prop.appearance_states:
            state_reference = reference_id(prop.id, appearance.id)
            image_state = inherited_images[appearance.id]
            files[state_reference] = ApprovedReferenceFile(
                reference_id=state_reference,
                path=(artifacts.prop_ref_path(project_dir, prop.id)
                      if image_state is None
                      else artifacts.prop_state_ref_path(project_dir, prop.id, image_state)),
                media_type="image/png",
            )
    return files


async def run(config: Config, project_dir: Path, ctx: StageRuntime):
    target = TargetArtifacts(project_dir)
    brief = target.read_brief()
    from novel_to_comic.narrative_review import adaptation_context, require_narrative_review
    require_narrative_review(target, "adapt", adaptation_context(target.read_source(), brief, target.read_adaptation()))
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
        story_tone=brief.tone,
        concurrency=config.effective_text_concurrency(),
        integrated_lettering=config.lettering_mode == "integrated",
    )
    return result


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    target = TargetArtifacts(project_dir)
    if not target.adaptation_path.exists() or not target.brief_path.exists():
        return 0.0
    brief = target.read_brief()
    return estimate_book_plan_cost(
        target.read_adaptation(),
        approved_visual_inventory(project_dir),
        ApprovedPageRange(
            minimum=brief.target_page_min,
            maximum=brief.target_page_max,
        ),
        model=config.effective_plan_model(),
        story_tone=brief.tone,
        integrated_lettering=config.lettering_mode == "integrated",
    )


STAGE = Stage(
    name="plan",
    run=run,
    outputs=lambda d: [TargetArtifacts(d).plan_path, d / "plan" / "pages"],
    clean_paths=lambda d: clean_cascade(d, "plan"),
    estimate_cost=estimate_cost,
)
