"""Stage 3: character reference images + location plates.

Part A: Generate character reference sheets
Part B: Generate location background plates
"""

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts, reference_forms
from novel_to_comic.models.appearance import ReferenceForm
from novel_to_comic.style_contract import figure_free_style_template
from novel_to_comic.cast_roster import read_cast_story_bible
from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_ref_strategy import RefStrategy
from novel_to_comic.events import make_progress
from novel_to_comic.models.generation import PromptAnchor, PromptSubject
from novel_to_comic.models.story_bible import (
    Character, MissingVisualAnchor, Prop, StoryBible, blank_visual_anchors,
)
from novel_to_comic.look_assets import produce_look_asset, produce_stage_look_asset
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.workspace import series_root
from novel_to_comic.style_reference import find_style_reference as _find_style_ref

from novel_to_comic.state_assets import (
    StateAssetGenerationSpec,
    build_character_state_spec,
    build_location_state_spec,
)
from novel_to_comic.asset_generation import (
    CanonicalCharacterReferenceInput,
    CanonicalLocationPlateInput,
    CharacterStateReferenceInput,
    LocationStatePlateInput,
    PropReferenceInput,
    StyleCalibrationInput,
    asset_matches_request,
    compile_non_panel_request,
    style_reference_plan,
)
from novel_to_comic.usage import ApiResult
from novel_to_comic.cast_design import (
    CastDesignPlan, character_fingerprint, current_designs, design_notes, ensure_design, estimate_design_review,
    read_design, review_cast, review_status,
)

console = Console()

_CAST_RENDERING_CONSISTENCY = (
    "Keep one artistic hand across the entire cast, matching the shared style reference's "
    "medium, line weight, facial modeling, and degree of realism. Human, animal, and "
    "creature anatomy must not switch the rendering style. Do not render one character "
    "photographically and another as animation. Identity and age differences change "
    "the subject, not the artistic treatment."
)


_SHEET_POSE_BOXES: dict[str, tuple[float, float, float, float]] = {
    # Wide turnaround sheet produced by the character prompt: the top-left
    # three-quarter head and the three-view full-body turnaround, both square.
    # Fractions are (x0, y0, x1, y1).
    "portrait":  (0.0, 0.0, 1 / 3, 0.5),
    "full_body": (1 / 3, 0.0, 1.0, 1.0),
}


def _crop_sheet_to_poses(sheet_path: Path) -> None:
    """Crop a turnaround character reference sheet into reusable reference PNGs.

    The combined generation keeps identity coherent across portrait and body
    views, while the derived crops prevent the sheet layout leaking into panel
    composition. Close shots use ``portrait``; other framings use ``full_body``.
    """
    from PIL import Image

    with Image.open(sheet_path) as img:
        w, h = img.size
        for name, (x0, y0, x1, y1) in _SHEET_POSE_BOXES.items():
            box = (int(w * x0), int(h * y0), int(w * x1), int(h * y1))
            out_path = sheet_path.parent / f"{name}.png"
            img.crop(box).save(out_path)


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _relative_to_project(path: Path | None, project_dir: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(series_root(project_dir)))
    except ValueError:
        return str(path)


def _asset_meta_common(config: Config, project_dir: Path, style_ref: Path | None) -> dict:
    return {
        "version": 1,
        "style_template": config.style_template,
        "image_model": config.effective_image_model(),
        "style_ref": _relative_to_project(style_ref, project_dir),
        "style_ref_sha256": _file_sha256(style_ref),
    }


def _character_ref_meta(
    config: Config,
    project_dir: Path,
    style_ref: Path | None,
    char: Character,
    prompt: str,
    addendum: str = "",
) -> dict:
    meta = {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "character_ref",
        "character_id": char.id,
        "visual_anchor": char.visual_anchor,
        "default_outfit": char.default_outfit,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if addendum:
        meta["instruction_addendum"] = addendum
    return meta


def _location_plate_meta(
    config: Config,
    project_dir: Path,
    style_ref: Path | None,
    loc,
    prompt: str,
    width: int | None = None,
    height: int | None = None,
    addendum: str = "",
    state_id: str | None = None,
    anchor: str | None = None,
) -> dict:
    meta = {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "location_plate",
        "location_id": loc.id,
        "visual_anchor": anchor or loc.visual_anchor,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if state_id:
        meta["location_state_id"] = state_id
    if RefStrategy.for_config(config).include_dimensions_in_asset_meta() and width and height:
        meta["width"] = width
        meta["height"] = height
    if addendum:
        meta["instruction_addendum"] = addendum
    return meta


def _prop_ref_meta(
    config: Config,
    project_dir: Path,
    style_ref: Path | None,
    prop: Prop,
    prompt: str,
    addendum: str = "",
) -> dict:
    meta = {
        **_asset_meta_common(config, project_dir, style_ref),
        "kind": "prop_ref",
        "prop_id": prop.id,
        "visual_anchor": prop.visual_anchor,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if addendum:
        meta["instruction_addendum"] = addendum
    return meta


def _asset_style_text(config: Config, form: ReferenceForm | None = None) -> str:
    """Selected style text for a Cast asset; only figures receive the
    character proportion system (``form=None`` is a plate or prop)."""
    return (config.style_template if form == "figure"
            else figure_free_style_template(config.style_template))


def _cast_asset_style_ref(config: Config, style_ref: Path | None) -> Path | None:
    return RefStrategy.for_config(config).cast_style_ref(style_ref)


def _require_shared_character_style(config: Config, style_ref: Path | None) -> None:
    if style_ref is None or not style_ref.is_file():
        raise ValueError(
            "The selected Style proof is missing or stale. "
            "Rerun Style and select a proof before generating character references."
        )


def require_character_inputs(config: Config, project_dir: Path, char_id: str, *, state=False) -> None:
    """Read-only preflight before admitting an individual paid correction."""
    bible = read_cast_story_bible(project_dir, character_ids=[char_id])
    design = read_design(config, project_dir, bible, character_ids=[char_id])
    style = _character_style_reference(config, project_dir, _find_style_ref(project_dir, config.style_template))
    _require_shared_character_style(config, style)
    if state:
        char = next(c for c in bible.characters if c.id == char_id)
        request = _compile_cast_request(config, project_dir, _character_generation_input(
            config, bible, char, _read_character_ref_addendum(project_dir, char_id), design=design
        ), reference_plan=style_reference_plan(config, style))
        if not asset_matches_request(artifacts.character_ref_sheet_path(project_dir, char_id), request):
            raise ValueError("The canonical character reference is stale; run Cast before regenerating its appearance states.")


def _location_plate_dimensions(config: Config) -> tuple[int | None, int | None]:
    return RefStrategy.for_config(config).location_plate_dimensions()


CAST_BLOCKED_MESSAGE = (
    "The image provider declined this reference without saying why, usually because of "
    "explicit wording such as nudity or gore. Make a less graphic version, or reword the "
    "description; resuming Cast does not resend the same request."
)

def _location_plate_jobs(loc) -> list[tuple[str, str, str | None]]:
    """(plate_stem, anchor, state_id) tuples with entity-scoped state paths."""
    jobs: list[tuple[str, str, str | None]] = [(loc.id, loc.visual_anchor, None)]
    for state in loc.appearance_states or []:
        jobs.append((f"{loc.id}/states/{state.id}", state.visual_anchor, state.id))
    return jobs


def _character_state_jobs(char: Character) -> list[tuple[str, str]]:
    """(state_id, anchor) for each visually-significant appearance state.

    A character whose body changes mid-story (stumps, silver hands, restored)
    gets a dedicated reference sheet per flagged state so panels in that state
    reference the changed body instead of the canonical one. Minor, text-only
    appearance states are not flagged and produce no extra generation.
    """
    return [
        (state.id, state.visual_anchor)
        for state in char.appearance_states or []
        if state.visually_significant
    ]


def _cast_semaphore(config: Config) -> asyncio.Semaphore:
    return asyncio.Semaphore(config.effective_image_concurrency())


def _character_generation_input(
    config: Config, story_bible: StoryBible, char: Character, addendum: str = "",
    *, design=None,
) -> CanonicalCharacterReferenceInput:
    form = reference_forms.reference_form(char)
    composition, direction = reference_forms.CANONICAL_DIRECTION[form]
    identity_details = "\n".join(filter(None, (
        f"Canonical age: {char.age_range}.",
        f"Canonical gender: {char.gender}. Make it read clearly in face, build and silhouette "
        "while keeping every stated physique trait." if char.gender.strip() else "",
        f"Canonical stature: {char.stature}. Show this scale on the sheet: beside the full-body "
        "views, draw a plain unlabeled silhouette of an ordinary adult of the setting at true "
        "relative height; keep it featureless so it is never mistaken for another character. "
        "That scale silhouette is the only permitted extra figure."
        if char.stature.strip() else "",
        f"Canonical wardrobe: {char.default_outfit}." if char.default_outfit else "",
        "Canonical distinguishing details: " + "; ".join(char.distinguishing_features)
        if char.distinguishing_features else "",
        reference_forms.IDENTITY_DESIGN[form],
        design_notes(design, char.id) if design is not None else "",
    )))
    return CanonicalCharacterReferenceInput(
        asset_identity=f"character_ref:{char.id}",
        prompt=GenerationPromptInput(
            subjects=(PromptSubject(
                character_id=char.id, name=char.name, identity=char.visual_anchor,
                reference_form=form,
            ),),
            visual_brief=direction,
            editorial_addendum=addendum,
            composition=composition,
            constraints=(
                "Preserve active anatomy, age, and proportions in the selected style. "
                "Each view stays fully inside its own region. No text, labels, "
                "divider lines, scenery, or other characters.\n" + identity_details
                + "\n" + _CAST_RENDERING_CONSISTENCY
            ),
            width=1536,
            height=1024,
            generation_width=1536,
            generation_height=1024,
            generation_shape="landscape",
        ),
        selected_style_text=_asset_style_text(config, form),
        selected_style_source_hash=hashlib.sha256(config.style_template.encode()).hexdigest(),
    )


def _character_style_reference(
    config: Config, project_dir: Path, proof: Path | None,
) -> Path | None:
    """Keep the selected proof's facial abstraction and proportion evidence.

    A generated material board cannot convey how faces and bodies are drawn.
    Identity, pose and composition are excluded by the style reference scope.
    """
    return _cast_asset_style_ref(config, proof)


# A plate shows the place at the size its anchor establishes. A fixed wide
# establishing shot let the image model invent a large room around sparse or
# small anchors and fill it from the Style proof's scene.
LOCATION_PLATE_COMPOSITION = (
    "Character-free location design plate, framed at the location's true scale and enclosure."
)
_LOCATION_PLATE_DIRECTION = (
    "Show the specified location at its true scale. A small or enclosed space must look "
    "small and enclosed: frame it from inside, close to its walls, showing only the room the anchor "
    "establishes. Where the anchor describes only objects or a work surface, frame a restrained view "
    "around them rather than inventing a larger room. Construct architecture and spatial layout from the "
    "location anchor. No characters."
)


LOCATION_STYLE_BOARD_LABEL = "selected style rendering board"


def _location_style_board_path(project_dir: Path) -> Path:
    return series_root(project_dir) / "refs" / "location_style_board.png"


def _location_style_board_input(config: Config) -> StyleCalibrationInput:
    """The proof's rendering language without any room, object or figure to copy.

    Plates once took the proof directly and its room carried into other
    locations; text alone then lost the proof's rendering, and Draw inherited
    that drift from the plates.
    """
    return StyleCalibrationInput(
        asset_identity="cast:location_style_board",
        prompt=GenerationPromptInput(
            visual_brief=(
                "Rendering-only environment study. Translate the selected style into separate, "
                "unrecognizable studies on one support: tonal fields from lightest to darkest, "
                "contour and edge samples, cast-shadow and light-falloff studies on plain geometric "
                "solids (cube, cylinder, sphere) standing on a bare ground plane, and material "
                "swatches of plaster, wood grain, cloth folds, stone, glass and metal. Match its "
                "artistic hand, palette, value range, line weight, medium, edge treatment, shadow "
                "depth and degree of simplification. Show each material's distinct mark scale; keep "
                "paper aging on the support rather than painting it into every material. Do not "
                "magnify incidental mottling from the proof into an all-over stain pattern. Preserve "
                "deliberate granulation and authored distress where the selected style calls for "
                "them. Do not reproduce any recognizable subject, room or object from the reference."
            ),
            composition="Landscape arrangement of separate abstract rendering and material studies.",
            constraints=(
                "No people, faces, heads, bodies, silhouettes of beings, animals, creatures, costumes, "
                "rooms, interiors, architecture, furniture, landscapes, scenery, text or labels. "
                "Rendering evidence only."
            ),
            width=1344,
            height=768,
            generation_width=1344,
            generation_height=768,
            generation_shape="landscape",
        ),
        selected_style_text=_asset_style_text(config),
        selected_style_source_hash=hashlib.sha256(config.style_template.encode()).hexdigest(),
    )


def _location_style_board_request(config: Config, project_dir: Path, proof: Path):
    return _compile_cast_request(
        config, project_dir, _location_style_board_input(config),
        reference_plan=style_reference_plan(config, proof),
    )


def _location_style_board(config: Config, project_dir: Path) -> Path | None:
    """The board, only while it was made from the current proof and style."""
    proof = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    if proof is None or not proof.is_file():
        return None
    board = _location_style_board_path(project_dir)
    return board if asset_matches_request(board, _location_style_board_request(config, project_dir, proof)) else None


def _require_location_style_board(config: Config, project_dir: Path) -> Path:
    board = _location_style_board(config, project_dir)
    if board is None:
        raise ValueError(
            "The location style board is missing or out of date. Resume Cast to prepare it "
            "from the selected Style proof before redrawing location plates."
        )
    return board


def _location_plate_reference_plan(config: Config, board: Path | None):
    """Plates take the proof's rendering through the board, never the proof's scene."""
    return style_reference_plan(config, board, label=LOCATION_STYLE_BOARD_LABEL)


async def _ensure_location_style_board(config: Config, project_dir: Path, ctx: StageRuntime) -> Path | None:
    """Generate the shared board once per proof; plates wait for it."""
    proof = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    if proof is None or not proof.is_file():
        raise ValueError("Select and generate a Style sample before running Cast.")
    output_path = _location_style_board_path(project_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = _location_style_board_request(config, project_dir, proof)
    outcome = await produce_stage_look_asset(
        ctx=ctx, item_id="location_style_board", label="location style board",
        config=config, project_dir=project_dir, request=request, output_path=output_path,
        feature="cast.location_style_board", semaphore=_cast_semaphore(config),
    )
    return output_path if outcome and outcome.status != "held" else None


def _location_generation_input(
    config: Config, loc, addendum: str = "", anchor: str | None = None,
) -> CanonicalLocationPlateInput:
    direction = _LOCATION_PLATE_DIRECTION
    return CanonicalLocationPlateInput(
        asset_identity=f"location_plate:{loc.id}",
        prompt=GenerationPromptInput(
            anchors=(PromptAnchor(
                kind="location", entity_id=loc.id, name=loc.name,
                text=anchor or loc.visual_anchor,
            ),),
            visual_brief=direction,
            editorial_addendum=addendum,
            composition=LOCATION_PLATE_COMPOSITION,
            constraints="No text, noisy grain, repeated texture fields, or muddy micro-detail.",
            width=1344,
            height=768,
            generation_width=1344,
            generation_height=768,
            generation_shape="landscape",
        ),
        selected_style_text=_asset_style_text(config),
        selected_style_source_hash=hashlib.sha256(config.style_template.encode()).hexdigest(),
    )


def _prop_generation_input(
    config: Config, prop: Prop, addendum: str = "",
) -> PropReferenceInput:
    direction = (
        "Single object isolated on a neutral mid-grey background, three-quarter view, evenly lit, "
        "centered and fully visible with generous margin."
    )
    return PropReferenceInput(
        asset_identity=f"prop_ref:{prop.id}",
        prompt=GenerationPromptInput(
            anchors=(PromptAnchor(
                kind="prop", entity_id=prop.id, name=prop.name, text=prop.visual_anchor,
            ),),
            visual_brief=direction,
            composition="Single centered prop reference, no cropping.",
            editorial_addendum=addendum,
            constraints="No characters, hands, scenery, other objects, text, labels, or captions.",
            width=1024,
            height=1024,
            generation_width=1024,
            generation_height=1024,
            generation_shape="square",
        ),
        selected_style_text=_asset_style_text(config),
        selected_style_source_hash=hashlib.sha256(config.style_template.encode()).hexdigest(),
    )


def _read_character_ref_addendum(project_dir: Path, char_id: str) -> str:
    return artifacts.read_active_addendum(
        artifacts.character_ref_instructions_path(project_dir, char_id)
    )


def _read_location_plate_addendum(project_dir: Path, loc_id: str) -> str:
    return artifacts.read_active_addendum(
        artifacts.location_plate_instructions_path(project_dir, loc_id)
    )


def _read_prop_ref_addendum(project_dir: Path, prop_id: str) -> str:
    return artifacts.read_active_addendum(
        artifacts.prop_ref_instructions_path(project_dir, prop_id)
    )


def _state_asset_prompt(spec: StateAssetGenerationSpec) -> GenerationPromptInput:
    """Build the canonical prompt IR for a state asset.

    The active state anchor remains protected on the subject/location field;
    state-specific direction (including continuity guards and user addenda)
    travels through ``visual_brief`` so the shared compiler owns its final
    rendering.
    """
    if spec.asset_kind == "character_state_ref":
        subjects = [PromptSubject(
            character_id=spec.entity_id,
            name=spec.entity_id,
            identity=spec.active_state_anchor,
            baseline_affect=spec.baseline_affect,
            appearance_state_id=spec.state_id,
            appearance_locked=True,
            appearance_guard=spec.continuity_guard,
            reference_form=spec.reference_form,
        )]
        anchors = []
        composition = reference_forms.STATE_COMPOSITION[spec.reference_form]
    else:
        subjects = []
        anchors = [PromptAnchor(
            kind="prop" if spec.asset_kind == "prop_state_ref" else "location", entity_id=spec.entity_id, name=spec.entity_id,
            appearance_state_id=spec.state_id, text=spec.active_state_anchor,
            continuity_guard=spec.continuity_guard,
        )]
        composition = ("Single prop on a neutral background; no characters or text."
                       if spec.asset_kind == "prop_state_ref" else LOCATION_PLATE_COMPOSITION)
    return GenerationPromptInput(
        anchors=tuple(anchors), subjects=tuple(subjects), composition=composition,
        visual_brief=spec.state_direction or None,
        editorial_addendum=spec.state_addendum,
        constraints=(
            "The active-state anchor and verbatim guard win over changed canonical facts. "
            "Canonical references preserve only explicitly compatible identity facets; "
            "selected art direction owns rendering."
            + ("\n" + _CAST_RENDERING_CONSISTENCY if spec.asset_kind == "character_state_ref" else "")
        ),
        location_state_id=spec.state_id if spec.asset_kind == "location_state_plate" else None,
        width=spec.effective_width, height=spec.effective_height,
        generation_width=spec.effective_width, generation_height=spec.effective_height,
        generation_shape=spec.requested_shape,
    )


def _compile_cast_request(config, project_dir, input_data, *, reference_plan):
    from novel_to_comic.cast_reference_inputs import with_cast_reference_inputs

    plan = with_cast_reference_inputs(config, project_dir, input_data, reference_plan)
    return compile_non_panel_request(config, input_data, reference_plan=plan)


def _compile_state_asset_wire(
    config: Config,
    spec: StateAssetGenerationSpec,
    project_dir: Path,
):
    """Compile one state request and update metadata before transport/cache checks."""
    from novel_to_comic.state_assets import build_state_reference_plan, edits_canonical_parent

    prompt = _state_asset_prompt(spec)
    from novel_to_comic.image_models import image_model_profile_for_config

    profile = image_model_profile_for_config(config)
    plan = build_state_reference_plan(spec, project_dir, route_profile=profile)
    input_data = (
        CharacterStateReferenceInput if spec.asset_kind == "character_state_ref"
        else PropReferenceInput if spec.asset_kind == "prop_state_ref"
        else LocationStatePlateInput
    )(
        asset_identity=f"{spec.entity_id}:{spec.state_id}",
        prompt=prompt,
        selected_style_text=_asset_style_text(
            config, spec.reference_form if spec.asset_kind == "character_state_ref" else None),
        selected_style_source_hash=spec.style_sha256,
        lineage=spec.lineage_metadata(),
        edit_parent_indices=tuple(index for index, ref in enumerate(plan.selected) if ref.role != "style")
        if edits_canonical_parent(spec) else (),
    )
    request = _compile_cast_request(config, project_dir, input_data, reference_plan=plan)
    spec.compiled_request_sha256 = request.compiled.compiled_request_sha256
    spec.execution_fingerprint = request.wire.execution_fingerprint
    return replace(
        request,
        input=replace(request.input, lineage=spec.lineage_metadata()),
    )


async def _generate_state_asset_wire(
    config: Config,
    spec: StateAssetGenerationSpec,
    output_path: Path,
    project_dir: Path,
    *,
    feature: str,
    request=None,
) -> ApiResult[Path]:
    """Compile and submit a canonical-conditioned state asset through the shared wire seam.

    Slice 09: the state request now carries a ReferencePlan that conditions the
    active state on compatible canonical identity (character sheet / location
    plate) plus style where the route cap has room. A total transformation
    omits the contradictory parent (``lineage_mode=state_only``). The spec's
    lineage metadata is updated with the compiled/wire request hashes.
    """
    if request is None:
        request = _compile_state_asset_wire(config, spec, project_dir)
    submission = await produce_look_asset(force=True,
        config=config, project_dir=project_dir, request=request,
        output_path=output_path, feature=feature,
    )
    return submission.result


async def regenerate_character_ref(
    config: Config,
    project_dir: Path,
    char_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path]:
    story_bible = read_cast_story_bible(project_dir, character_ids=[char_id])
    char = next((candidate for candidate in story_bible.characters if candidate.id == char_id), None)
    if char is None:
        raise ValueError(f"Character not found: {char_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = series_root(project_dir) / "refs" / char.id / "sheet.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    approved_style_ref = _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    style_ref = _character_style_reference(config, project_dir, approved_style_ref)
    _require_shared_character_style(config, style_ref)
    addendum = _read_character_ref_addendum(project_dir, char.id)
    input_data = _character_generation_input(
        config, story_bible, char, addendum,
        design=read_design(config, project_dir, story_bible, character_ids=[char.id]),
    )
    request = _compile_cast_request(
        config, project_dir, input_data, reference_plan=style_reference_plan(config, style_ref)
    )
    async with sem:
        submission = await produce_look_asset(force=True,
            config=config, project_dir=project_dir, request=request,
            output_path=output_path, feature="cast.character_ref",
            refresh_review=True, on_generated=_crop_generated_sheet,
        )
    result = submission.result
    assert result is not None
    return result


async def regenerate_character_state_ref(
    config: Config,
    project_dir: Path,
    char_id: str,
    state_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path]:
    """Regenerate one character appearance-state ref sheet (e.g. silver hands).

    Mirrors regenerate_character_ref but renders from the state's self-contained
    anchor into refs/<char>/states/<state_id>/. Used to retry a state that
    failed during the cast batch, or to re-roll one on demand.
    """
    story_bible = read_cast_story_bible(project_dir, character_ids=[char_id])
    char = next((c for c in story_bible.characters if c.id == char_id), None)
    if char is None:
        raise ValueError(f"Character not found: {char_id}")
    state = next((s for s in char.appearance_states or [] if s.id == state_id), None)
    if state is None:
        raise ValueError(f"Appearance state not found: {char_id}/{state_id}")
    require_character_inputs(config, project_dir, char_id, state=True)

    sem = semaphore or asyncio.Semaphore(1)
    output_path = series_root(project_dir) / "refs" / char.id / "states" / state.id / "sheet.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    approved_style_ref = _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    style_ref = _character_style_reference(config, project_dir, approved_style_ref)
    _require_shared_character_style(config, style_ref)
    spec = build_character_state_spec(config, project_dir, char, state, style_path=style_ref)
    async with sem:
        result = await _generate_state_asset_wire(
            config, spec, output_path, project_dir,
            feature="cast.character_state_ref",
        )
    await asyncio.to_thread(_crop_sheet_to_poses, output_path)
    return result


async def regenerate_prop_ref(
    config: Config,
    project_dir: Path,
    prop_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path]:
    story_bible = read_cast_story_bible(project_dir)
    prop = next((p for p in story_bible.props if p.id == prop_id), None)
    if prop is None:
        raise ValueError(f"Prop not found: {prop_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = artifacts.prop_ref_path(project_dir, prop.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    addendum = _read_prop_ref_addendum(project_dir, prop.id)
    input_data = _prop_generation_input(config, prop, addendum)
    request = _compile_cast_request(
        config, project_dir, input_data, reference_plan=style_reference_plan(config, style_ref)
    )

    async with sem:
        submission = await produce_look_asset(force=True,
            config=config, project_dir=project_dir, request=request,
            output_path=output_path, feature="cast.prop_ref",
        )
    result = submission.result
    assert result is not None
    return result


async def regenerate_location_plate(
    config: Config,
    project_dir: Path,
    loc_id: str,
    semaphore: asyncio.Semaphore | None = None,
    state_id: str | None = None,
) -> ApiResult[Path]:
    story_bible = read_cast_story_bible(project_dir)
    loc = next((candidate for candidate in story_bible.locations if candidate.id == loc_id), None)
    if loc is None:
        raise ValueError(f"Location not found: {loc_id}")
    anchor = loc.visual_anchor
    plate_stem = loc.id
    if state_id:
        state = next((s for s in loc.appearance_states or [] if s.id == state_id), None)
        if state is None:
            raise ValueError(f"Location state not found: {state_id}")
        anchor = state.visual_anchor
        plate_stem = f"{loc.id}/states/{state.id}"

    sem = semaphore or asyncio.Semaphore(1)
    output_path = series_root(project_dir) / "plates" / f"{plate_stem}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    board = _require_location_style_board(config, project_dir)
    if state_id:
        spec = build_location_state_spec(config, project_dir, loc, state, style_path=board)
        request = _compile_state_asset_wire(config, spec, project_dir)
    else:
        addendum = _read_location_plate_addendum(project_dir, loc.id)
        input_data = _location_generation_input(config, loc, addendum, anchor=anchor)
        request = _compile_cast_request(
            config, project_dir, input_data, reference_plan=_location_plate_reference_plan(config, board)
        )
        spec = None
    async with sem:
        submission = await produce_look_asset(force=True,
            config=config, project_dir=project_dir, request=request,
            output_path=output_path,
            feature=("cast.location_state_plate" if state_id else "cast.location_plate"),
            refresh_review=state_id is None,
        )
    result = submission.result
    assert result is not None
    if state_id:
        return result
    return result


async def _crop_generated_sheet(result):
    await asyncio.to_thread(_crop_sheet_to_poses, result.value)
    return result


async def _generate_character_refs(
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    char_ids: list[str] | None = None,
    style_ref: Path | None = None,
) -> None:
    """Part B: Generate character reference sheets.

    Each character gets one wide composite image (sheet.png) containing a
    portrait and full-body view. Generating both views in one API call keeps
    identity, proportions, and rendering consistent within the reference.
    """
    chars_to_gen = [c for c in story_bible.characters if not char_ids or c.id in char_ids]
    if not chars_to_gen:
        return
    console.print("[bold]Generating character reference images...[/bold]")
    ctx.log("Generating character reference sheets...")
    refs_dir = series_root(project_dir) / "refs"

    # A visual style reference image is far stronger than text for locking style.
    # Without it, the model applies different stylistic conventions per character
    # type (human → concept art, cat → anime, creature → dark fantasy).
    candidate_style_ref = _find_style_ref(project_dir, config.style_template)
    style_ref = style_ref or _character_style_reference(config, project_dir, candidate_style_ref)
    _require_shared_character_style(config, style_ref)
    if style_ref:
        console.print(f"[dim]Using style reference: {style_ref.name}[/dim]")
    else:
        console.print(
            "[yellow]No style sample found — generate and select a Style sample "
            "in the app before generating character references.[/yellow]"
        )

    design = read_design(config, project_dir, story_bible, character_ids=[c.id for c in chars_to_gen])
    semaphore = _cast_semaphore(config)

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Character refs", total=len(chars_to_gen))

        async def _one_character(char: Character) -> None:
            char_dir = refs_dir / char.id
            char_dir.mkdir(parents=True, exist_ok=True)
            output_path = char_dir / "sheet.png"
            addendum = _read_character_ref_addendum(project_dir, char.id)
            input_data = _character_generation_input(config, story_bible, char, addendum, design=design)
            request = _compile_cast_request(
                config, project_dir, input_data, reference_plan=style_reference_plan(config, style_ref)
            )

            outcome = await produce_stage_look_asset(
                ctx=ctx, item_id=char.id, label=f"ref sheet for {char.name}",
                config=config, project_dir=project_dir, request=request,
                output_path=output_path, feature="cast.character_ref", semaphore=semaphore,
                on_generated=_crop_generated_sheet,
            )
            if outcome and outcome.status != "held":
                if outcome.status == "reused" and not (char_dir / "portrait.png").exists():
                    try:
                        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    except Exception:
                        pass
            if task is not None:
                progress.advance(task)

        await asyncio.gather(*(_one_character(char) for char in chars_to_gen))


async def _generate_character_state_refs(
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    char_ids: list[str] | None = None,
    style_ref: Path | None = None,
) -> None:
    """Generate a reference sheet per visually-significant appearance state.

    Each flagged state (e.g. silver hands) is generated from the state's own
    self-contained anchor, reusing the canonical character-sheet prompt so the
    identity lock and turnaround layout stay consistent. Output lives under
    refs/<char>/states/<state_id>/ and is selected by prompting.py when that
    state is active for a panel.
    """
    chars = [c for c in story_bible.characters if not char_ids or c.id in char_ids]
    jobs = [(c, sid, anchor) for c in chars for sid, anchor in _character_state_jobs(c)]
    if not jobs:
        return

    console.print("[bold]Generating character appearance-state refs...[/bold]")
    ctx.log("Generating character appearance-state refs...")
    style_ref = style_ref or _character_style_reference(
        config, project_dir, _find_style_ref(project_dir, config.style_template)
    )
    _require_shared_character_style(config, style_ref)
    semaphore = _cast_semaphore(config)

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("State refs", total=len(jobs))

        async def _one_state(char: Character, state_id: str, anchor: str) -> None:
            state_obj = next((s for s in char.appearance_states or [] if s.id == state_id), None)
            out_dir = series_root(project_dir) / "refs" / char.id / "states" / state_id
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / "sheet.png"
            parent_path = artifacts.character_ref_sheet_path(project_dir, char.id)
            if not parent_path.exists() or char.id in ctx.stage_state.items_failed:
                ctx.record_item_failed(f"{char.id}:{state_id}")
                ctx.log(
                    f"Skipped {state_id} ref for {char.name}: canonical ref is unavailable",
                    level="error",
                )
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                if task is not None:
                    progress.advance(task)
                return
            spec = build_character_state_spec(
                config, project_dir, char, state_obj, style_path=style_ref
            )
            # Build the conditioning plan up front so the lineage metadata
            # (mode, reference summary, status, request hashes) is available for
            # the cache check. The exact compiled wire is reused on a miss.
            # Canonical-first scheduling guarantees the parent exists here.
            wire = _compile_state_asset_wire(config, spec, project_dir)

            outcome = await produce_stage_look_asset(
                ctx=ctx, item_id=f"{char.id}:{state_id}", label=f"{state_id} ref for {char.name}",
                config=config, project_dir=project_dir, request=wire,
                output_path=output_path, feature="cast.character_state_ref", semaphore=semaphore,
                on_generated=_crop_generated_sheet,
            )
            if outcome and outcome.status != "held":
                if outcome.status == "reused" and not (out_dir / "portrait.png").exists():
                    try:
                        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    except Exception:
                        pass
            if task is not None:
                progress.advance(task)

        await asyncio.gather(*(_one_state(*job) for job in jobs))


async def _generate_location_plates(
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    loc_ids: list[str] | None = None, board: Path | None = None,
) -> None:
    """Part C: Generate location background plates — one per location state."""
    console.print("[bold]Generating location plates...[/bold]")
    ctx.log("Generating location plates...")
    plates_dir = series_root(project_dir) / "plates"
    plates_dir.mkdir(parents=True, exist_ok=True)

    locs_to_gen = [loc for loc in story_bible.locations if not loc_ids or loc.id in loc_ids]
    plate_jobs = [
        (loc, stem, anchor, state_id)
        for loc in locs_to_gen
        for stem, anchor, state_id in _location_plate_jobs(loc)
    ]
    semaphore = _cast_semaphore(config)

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Location plates", total=len(plate_jobs))

        async def _one_plate(loc, stem: str, anchor: str, state_id: str | None) -> None:
            label = f"{loc.name} ({state_id})" if state_id else loc.name
            output_path = plates_dir / f"{stem}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if state_id:
                parent_path = artifacts.location_plate_path(project_dir, loc.id)
                if not parent_path.exists():
                    ctx.record_item_failed(stem)
                    ctx.log(
                        f"Skipped {state_id} plate for {loc.name}: canonical plate is unavailable",
                        level="error",
                    )
                    ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                    if task is not None:
                        progress.advance(task)
                    return
                state = next(s for s in loc.appearance_states if s.id == state_id)
                spec = build_location_state_spec(
                    config, project_dir, loc, state, style_path=board
                )
                # Build the conditioning plan up front so lineage metadata is
                # (including request hashes) is available for the cache check.
                # Canonical-first scheduling guarantees the parent plate exists
                # here, and the exact compiled wire is reused on a miss.
                wire = _compile_state_asset_wire(config, spec, project_dir)
            else:
                addendum = _read_location_plate_addendum(project_dir, loc.id)
                input_data = _location_generation_input(config, loc, addendum, anchor=anchor)
                wire = _compile_cast_request(
                    config, project_dir, input_data, reference_plan=_location_plate_reference_plan(config, board)
                )
                spec = None
            await produce_stage_look_asset(
                ctx=ctx, item_id=stem, label=f"location plate for {label}",
                config=config, project_dir=project_dir, request=wire,
                output_path=output_path,
                feature="cast.location_state_plate" if state_id else "cast.location_plate",
                semaphore=semaphore,
            )
            if task is not None:
                progress.advance(task)

        # Parent plates must be materialized before state specs capture lineage.
        canonical_jobs = [job for job in plate_jobs if job[3] is None]
        state_jobs = [job for job in plate_jobs if job[3] is not None]
        await asyncio.gather(*(_one_plate(*job_args) for job_args in canonical_jobs))
        await asyncio.gather(*(_one_plate(*job_args) for job_args in state_jobs))


async def _generate_prop_refs(
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    prop_ids: list[str] | None = None,
) -> None:
    """Generate one neutral-background reference image per story prop.

    Stage 1 already filters props down to those that recur or are plot-central,
    so every prop in the bible gets a ref sheet. Every route conditions the
    image on the selected style proof so prop refs share the panel art style.
    """
    props_to_gen = [p for p in story_bible.props if not prop_ids or p.id in prop_ids]
    if not props_to_gen:
        return

    console.print("[bold]Generating prop reference images...[/bold]")
    ctx.log("Generating prop reference images...")

    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    semaphore = _cast_semaphore(config)

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Prop refs", total=len(props_to_gen))

        async def _one_prop(prop: Prop) -> None:
            output_path = artifacts.prop_ref_path(project_dir, prop.id)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            addendum = _read_prop_ref_addendum(project_dir, prop.id)
            input_data = _prop_generation_input(config, prop, addendum)
            request = _compile_cast_request(
                config, project_dir, input_data, reference_plan=style_reference_plan(config, style_ref)
            )

            await produce_stage_look_asset(
                ctx=ctx, item_id=prop.id, label=f"prop ref for {prop.name}",
                config=config, project_dir=project_dir, request=request,
                output_path=output_path, feature="cast.prop_ref", semaphore=semaphore,
            )
            if task is not None:
                progress.advance(task)

        await asyncio.gather(*(_one_prop(prop) for prop in props_to_gen))
        from novel_to_comic.state_assets import build_prop_state_spec
        for prop in props_to_gen:
            for state in prop.appearance_states:
                if state.canonical_equivalent or not state.visually_significant:
                    continue
                output_path = artifacts.prop_state_ref_path(project_dir, prop.id, state.id)
                try:
                    spec = build_prop_state_spec(config, project_dir, prop, state, style_path=style_ref)
                    wire = _compile_state_asset_wire(config, spec, project_dir)
                    await produce_stage_look_asset(
                        ctx=ctx, item_id=f"{prop.id}:{state.id}", label=f"prop state {prop.name}/{state.label}",
                        config=config, project_dir=project_dir, request=wire,
                        output_path=output_path, feature="cast.prop_state_ref", semaphore=semaphore,
                    )
                except Exception as exc:
                    ctx.record_item_failed(f"{prop.id}:{state.id}")
                    ctx.log(f"Failed prop state {prop.name}/{state.label}: {exc}", level="error")
                ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    char_ids: list[str] | None = None,
    loc_ids: list[str] | None = None,
    prop_ids: list[str] | None = None,
) -> None:
    """Execute Stage 3: generate character refs, location plates, and prop refs."""
    story_bible = read_cast_story_bible(project_dir, character_ids=char_ids or ())

    is_partial = bool(char_ids or loc_ids or prop_ids)
    should_generate_refs = not is_partial or char_ids is not None
    should_generate_plates = not is_partial or loc_ids is not None
    should_generate_prop_refs = not is_partial or prop_ids is not None

    total_items = 0
    if should_generate_refs:
        chars_for_count = [c for c in story_bible.characters if not char_ids or c.id in char_ids]
        if chars_for_count:
            total_items += 2  # ensemble design and visual review
        total_items += len(chars_for_count)
        total_items += sum(len(_character_state_jobs(c)) for c in chars_for_count)
    plate_locations = [loc for loc in story_bible.locations if not loc_ids or loc.id in loc_ids]
    if should_generate_plates and plate_locations:
        total_items += 1  # shared location style board
        total_items += sum(len(_location_plate_jobs(loc)) for loc in plate_locations)
    if should_generate_prop_refs:
        total_items += sum(1 + sum(state.visually_significant and not state.canonical_equivalent for state in p.appearance_states) for p in story_bible.props if not prop_ids or p.id in prop_ids)

    review_ready = False
    with ctx.execute(total=total_items):
        if should_generate_refs:
            if chars_for_count:
                proof = _find_style_ref(project_dir, config.style_template)
                if proof is None or not proof.is_file():
                    raise ValueError("Select and generate a Style sample before running Cast.")
                await ensure_design(config, project_dir, story_bible, ctx)
            character_style_ref = _cast_asset_style_ref(
                config, _find_style_ref(project_dir, config.style_template)
            )
            await _generate_character_refs(
                config, project_dir, story_bible, ctx, char_ids, character_style_ref
            )
            await _generate_character_state_refs(
                config, project_dir, story_bible, ctx, char_ids, character_style_ref
            )
            # Only character failures hold the review back; decide before
            # plates and props can add failures of their own.
            review_ready = bool(chars_for_count) and not ctx.stage_state.items_failed and all(
                artifacts.character_ref_sheet_path(project_dir, c.id).exists() for c in story_bible.characters
            )
            if chars_for_count and not review_ready:
                ctx.record_item_failed("cast_visual_review")
                ctx.log("Cast visual review waits until every character reference finishes", level="error")
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)

        if should_generate_plates:
            board = await _ensure_location_style_board(config, project_dir, ctx) if plate_locations else None
            if plate_locations and board is None:
                # Plates without the proof's rendering are the drift this board
                # prevents; the board's own failure names what stopped Cast.
                ctx.log("Location plates wait until the location style board is ready", level="error")
            else:
                await _generate_location_plates(config, project_dir, story_bible, ctx, loc_ids, board)

        if should_generate_prop_refs:
            await _generate_prop_refs(config, project_dir, story_bible, ctx, prop_ids)

        # The review compares character sheets only and is one slow model call.
        # Running it last lets reused plates and props count at once on resume,
        # and a failed review can no longer stop plates from being drawn.
        if review_ready:
            await review_cast(config, project_dir, story_bible, ctx)
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)

        if ctx.stage_state.items_failed:
            raise ValueError(cast_failure_summary(cast_failure_details(project_dir, ctx.stage_state)))

        # Pin the style template hash so downstream stages (draw, especially)
        # can detect if the style was edited after cast plates were generated.
        # Skip pinning on partial re-runs unless plates were regenerated, since
        # a refs-only re-run doesn't replace the plates that anchor visual style.
        if not is_partial or should_generate_plates:
            from novel_to_comic.state import hash_style_template
            ctx.set_style_template_hash(hash_style_template(config.style_template))

        if not is_partial:
            console.print("[yellow]Cast stage complete — awaiting review.[/yellow]")
            console.print("Review character refs in: refs/")
            console.print("Approve Cast in the web UI to continue.")


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_state_reference_count(
    config: Config,
    project_dir: Path,
    asset_kind: str,
    entity_id: str,
    state_id: str,
) -> int:
    """Return the final selected reference count for one state request.

    This is a local, deterministic estimate path: it may inspect current
    files, but it never invokes transport. When the canonical parent is also
    missing during a first cast estimate, conservatively predict the parent
    plus compatible style slots that canonical-first execution will have.
    """
    from novel_to_comic.image_models import image_model_profile_for_config
    from novel_to_comic.state_assets import (
        StateConditioningError,
        build_character_state_spec,
        build_location_state_spec,
        build_prop_state_spec,
        build_state_reference_plan,
        state_is_total_transformation,
    )

    story_bible = read_cast_story_bible(
        project_dir, character_ids=[entity_id] if asset_kind == "character" else ())
    approved_style_ref = _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    style_ref = (
        (_character_style_reference(config, project_dir, approved_style_ref) or approved_style_ref)
        if asset_kind == "character" else approved_style_ref
    )
    profile = image_model_profile_for_config(config)
    if asset_kind == "character":
        entity = next((item for item in story_bible.characters if item.id == entity_id), None)
        if entity is None:
            raise ValueError(f"Character not found: {entity_id}")
        state = next((item for item in entity.appearance_states or [] if item.id == state_id), None)
        if state is None:
            raise ValueError(f"Appearance state not found: {entity_id}/{state_id}")
        spec = build_character_state_spec(config, project_dir, entity, state, style_path=style_ref)
        required_role = "subject"
    elif asset_kind == "location":
        entity = next((item for item in story_bible.locations if item.id == entity_id), None)
        if entity is None:
            raise ValueError(f"Location not found: {entity_id}")
        state = next((item for item in entity.appearance_states or [] if item.id == state_id), None)
        if state is None:
            raise ValueError(f"Location state not found: {entity_id}/{state_id}")
        spec = build_location_state_spec(config, project_dir, entity, state, style_path=style_ref)
        required_role = "location_plate"
    elif asset_kind == "prop":
        entity = next((item for item in story_bible.props if item.id == entity_id), None)
        if entity is None:
            raise ValueError(f"Prop not found: {entity_id}")
        state = next((item for item in entity.appearance_states if item.id == state_id), None)
        if state is None:
            raise ValueError(f"Prop state not found: {entity_id}/{state_id}")
        spec = build_prop_state_spec(config, project_dir, entity, state, style_path=style_ref)
        required_role = "prop"
    else:
        raise ValueError(f"Unknown state asset kind: {asset_kind}")

    if required_role not in profile.supported_roles:
        raise StateConditioningError(
            f"route {profile.route.value} does not support {required_role} "
            f"for state {entity_id}:{state_id}"
        )

    parent_path = (
        artifacts.character_ref_sheet_path(project_dir, entity_id)
        if asset_kind == "character"
        else artifacts.prop_ref_path(project_dir, entity_id) if asset_kind == "prop"
        else artifacts.location_plate_path(project_dir, entity_id)
    )
    if not parent_path.exists():
        # Canonical-first execution may materialize this sibling job immediately
        # before the state job. Estimate that post-canonical request shape, but
        # do not hide errors when a parent already exists.
        count = 0 if state_is_total_transformation(spec) else 1
        if (
            style_ref is not None
            and "style" in profile.supported_roles
            and count < profile.max_references
        ):
            count += 1
        return count

    # Existing parents must pass the same plan validation as execution. Digest,
    # unreadable-parent, and route/role errors are real blockers, not estimate
    # fallbacks.
    return build_state_reference_plan(
        spec, project_dir, route_profile=profile,
    ).ref_count


INCOMPLETE_CAST_MESSAGE = (
    "Some Cast references or checks did not finish. Resume Cast to finish the "
    "missing work; current references are reused."
)


def _failed_cast_asset(bible: StoryBible | None, project_dir: Path, item_id: str) -> tuple[dict, Path | None]:
    """Map a Cast ``items_failed`` id to its asset identity, label, and output path."""
    characters = {c.id: c for c in bible.characters} if bible else {}
    locations = {loc.id: loc for loc in bible.locations} if bible else {}
    props = {prop.id: prop for prop in bible.props} if bible else {}
    entity_id, _, state_id = item_id.partition(":")
    if "/states/" in item_id:
        entity_id, _, state_id = item_id.partition("/states/")
    state_id = state_id or None

    def _state_label(entity) -> str:
        state = next((s for s in entity.appearance_states or [] if s.id == state_id), None)
        return f"{entity.name} — {state.label if state else state_id}"

    if entity_id in characters:
        char = characters[entity_id]
        return ({"asset_type": "character", "entity_id": entity_id, "state_id": state_id,
                 "label": _state_label(char) if state_id else char.name},
                artifacts.character_state_ref_sheet_path(project_dir, entity_id, state_id) if state_id
                else artifacts.character_ref_sheet_path(project_dir, entity_id))
    if entity_id in locations:
        loc = locations[entity_id]
        return ({"asset_type": "location", "entity_id": entity_id, "state_id": state_id,
                 "label": _state_label(loc) if state_id else loc.name},
                artifacts.location_state_plate_path(project_dir, entity_id, state_id) if state_id
                else artifacts.location_plate_path(project_dir, entity_id))
    if item_id == "location_style_board":
        return ({"asset_type": None, "entity_id": None, "state_id": None, "label": "Location style board"},
                _location_style_board_path(project_dir))
    if entity_id in props:
        prop = props[entity_id]
        return ({"asset_type": "prop", "entity_id": entity_id, "state_id": state_id,
                 "label": _state_label(prop) if state_id else prop.name},
                artifacts.prop_state_ref_path(project_dir, entity_id, state_id) if state_id
                else artifacts.prop_ref_path(project_dir, entity_id))
    return {"asset_type": None, "entity_id": None, "state_id": None, "label": item_id}, None


def cast_failure_details(project_dir: Path, stage_state) -> list[dict]:
    """Explain each failed Cast reference from its stored failure sidecar.

    Read-only and provider-free, so status polling can show which reference
    stopped Cast and why instead of a bare "resume" prompt. The visual review
    only waits on the others, so it is not listed as a failure of its own.
    """
    from novel_to_comic.asset_generation import read_asset_failure
    from novel_to_comic.content_triggers import find_content_triggers

    bible = read_cast_story_bible(project_dir, safe=True)
    details = []
    for item_id in stage_state.items_failed:
        if item_id == "cast_visual_review":
            continue
        identity, path = _failed_cast_asset(bible, project_dir, item_id)
        failure = read_asset_failure(path) if path is not None else None
        classification = failure.get("classification") if failure else None
        attempts = failure.get("attempts") if failure else None
        # The stored copy is written for pages; a blocked reference needs a changed request.
        message = (CAST_BLOCKED_MESSAGE if classification == "provider_blocked"
                   else (failure or {}).get("user_message") or "This reference did not finish. Resume Cast to retry it.")
        details.append({
            "item_id": item_id, **identity,
            "classification": classification,
            # Likely wording behind a decline, from the request that was sent.
            "likely_triggers": (find_content_triggers(str(failure.get("prompt") or ""))
                                if failure and classification == "provider_blocked" else []),
            "attempts": attempts if type(attempts) is int else (1 if failure else None),
            "message": message,
        })
    return details


def cast_failure_summary(details: list[dict]) -> str:
    """One actionable sentence naming what stopped Cast, for errors and gates."""
    if not details:
        return INCOMPLETE_CAST_MESSAGE
    first = details[0]
    summary = f"{first['label']}: {first['message']}"
    if len(details) > 1:
        others = ", ".join(detail["label"] for detail in details[1:4])
        more = len(details) - 4
        summary += f" Also unfinished: {others}{f' and {more} more' if more > 0 else ''}."
    return summary


def cast_approval_blocker(config: Config, project_dir: Path, stage_state) -> str | None:
    """Shared, read-only checkpoint gate for status and approval.

    Include appearance states: the identity review compares canonical sheets
    and cannot by itself certify the rest of the Cast inventory.
    """
    incomplete = INCOMPLETE_CAST_MESSAGE
    if stage_state.items_failed:
        return cast_failure_summary(cast_failure_details(project_dir, stage_state))
    if stage_state.items_done < stage_state.items_total:
        return incomplete
    bible = read_cast_story_bible(project_dir, safe=True)
    if bible is None:
        return "Cast source artifacts are missing or invalid. Restore the Story Bible before resuming Cast."
    if blank := blank_visual_anchors(bible):
        return str(MissingVisualAnchor(blank))
    paths = []
    for char in bible.characters:
        paths.append(artifacts.character_ref_sheet_path(project_dir, char.id))
        paths.extend(artifacts.character_state_ref_sheet_path(project_dir, char.id, sid)
                     for sid, _anchor in _character_state_jobs(char))
    for loc in bible.locations:
        paths.extend(series_root(project_dir) / "plates" / f"{stem}.png"
                     for stem, _anchor, _sid in _location_plate_jobs(loc))
    for prop in bible.props:
        paths.append(artifacts.prop_ref_path(project_dir, prop.id))
        paths.extend(artifacts.prop_state_ref_path(project_dir, prop.id, appearance.id)
                     for appearance in prop.appearance_states
                     if appearance.visually_significant and not appearance.canonical_equivalent)
    if any(not path.is_file() for path in paths):
        return incomplete
    if bible.characters and review_status(config, project_dir)["status"] != "current":
        return "Compare the current character references before approving Cast. Resume Cast to run its visual review."
    return None


def _reference_items(bible: StoryBible):
    """Every Cast reference image the Story Bible needs, as (kind, entity, state)."""
    for char in bible.characters:
        yield "characters", char, None
        for appearance in char.appearance_states or []:
            if appearance.visually_significant:
                yield "characters", char, appearance
    for loc in bible.locations:
        yield "locations", loc, None
        for appearance in loc.appearance_states or []:
            yield "locations", loc, appearance
    for prop in bible.props:
        yield "props", prop, None
        for appearance in prop.appearance_states:
            if appearance.visually_significant and not appearance.canonical_equivalent:
                yield "props", prop, appearance


class _ReferenceRequests:
    """Compile the request each reference would make now, as generation does.

    Readiness, freshness and keeping an image all compare against the same
    frozen requests, so changed styles, anchors, instructions and canonical
    parents cannot promote an obsolete reference.
    """

    def __init__(self, config: Config, project_dir: Path, bible: StoryBible, design: CastDesignPlan | None):
        self.config, self.project_dir, self.bible, self.design = config, project_dir, bible, design
        self.style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
        self.character_style_ref = _character_style_reference(config, project_dir, self.style_ref)
        self.location_style_board = _location_style_board(config, project_dir)

    def path(self, kind: str, entity, appearance) -> Path:
        d = self.project_dir
        if kind == "characters":
            return (artifacts.character_ref_sheet_path(d, entity.id) if appearance is None
                    else artifacts.character_state_ref_sheet_path(d, entity.id, appearance.id))
        if kind == "locations":
            return (artifacts.location_plate_path(d, entity.id) if appearance is None
                    else artifacts.location_state_plate_path(d, entity.id, appearance.id))
        return (artifacts.prop_ref_path(d, entity.id) if appearance is None
                else artifacts.prop_state_ref_path(d, entity.id, appearance.id))

    def request(self, kind: str, entity, appearance):
        from novel_to_comic.state_assets import build_prop_state_spec

        config, d = self.config, self.project_dir
        if kind == "characters":
            if appearance is None:
                if self.design is None:
                    raise ValueError("Character designs are missing; resume Cast to design them.")
                return _compile_cast_request(config, d, _character_generation_input(
                    config, self.bible, entity, _read_character_ref_addendum(d, entity.id), design=self.design,
                ), reference_plan=style_reference_plan(config, self.character_style_ref))
            spec = build_character_state_spec(config, d, entity, appearance, style_path=self.character_style_ref)
        elif kind == "locations":
            if appearance is None:
                return _compile_cast_request(config, d, _location_generation_input(
                    config, entity, _read_location_plate_addendum(d, entity.id),
                ), reference_plan=_location_plate_reference_plan(config, self.location_style_board))
            spec = build_location_state_spec(config, d, entity, appearance, style_path=self.location_style_board)
        else:
            if appearance is None:
                return _compile_cast_request(config, d, _prop_generation_input(
                    config, entity, _read_prop_ref_addendum(d, entity.id),
                ), reference_plan=style_reference_plan(config, self.style_ref))
            spec = build_prop_state_spec(config, d, entity, appearance, style_path=self.style_ref)
        return _compile_state_asset_wire(config, spec, d)


def reference_freshness(config: Config, project_dir: Path) -> list[dict]:
    """Each Cast reference: ``current``, ``outdated`` or ``missing``.

    An edited entity's existing images turn ``outdated``: they still serve
    drawing until the author regenerates them or keeps them as they are.
    Reads only; nothing is generated.
    """
    bible = read_cast_story_bible(project_dir, safe=True)
    if bible is None:
        return []
    try:
        designs = current_designs(config, project_dir, bible)
    except (OSError, ValueError):
        designs = {}
    builder = _ReferenceRequests(config, project_dir, bible, None)
    report = []
    for kind, entity, appearance in _reference_items(bible):
        path = builder.path(kind, entity, appearance)
        if not path.exists():
            status = "missing"
        elif kind == "characters" and entity.id not in designs:
            # The facts its design answered changed; the sheet predates them.
            status = "outdated"
        else:
            if kind == "characters":
                builder.design = CastDesignPlan(
                    characters=[designs[entity.id]],
                    fingerprints={entity.id: character_fingerprint(config, entity)},
                )
            try:
                status = "current" if asset_matches_request(path, builder.request(kind, entity, appearance)) else "outdated"
            except (OSError, ValueError):
                status = "outdated"
        report.append({
            "kind": kind, "entity_id": entity.id,
            "state_id": appearance.id if appearance is not None else None, "status": status,
        })
    return report


def keep_current_reference(
    config: Config, project_dir: Path, kind: str, entity_id: str, state_id: str | None = None,
) -> None:
    """Keep an existing reference image after the author edits its entity.

    Records that the author accepts the image for the request the current
    Story Bible makes, so it counts as current. A character's design is kept
    too, so it is not redesigned. Nothing is generated.
    """
    from novel_to_comic.asset_generation import accept_existing_asset
    from novel_to_comic.cast_design import keep_design

    bible = read_cast_story_bible(project_dir)
    entity, appearance = None, None
    for item_kind, item, item_state in _reference_items(bible):
        if item_kind == kind and item.id == entity_id and (item_state.id if item_state else None) == state_id:
            entity, appearance = item, item_state
            break
    if entity is None:
        raise KeyError(state_id or entity_id)
    builder = _ReferenceRequests(config, project_dir, bible, None)
    path = builder.path(kind, entity, appearance)
    if not path.exists():
        raise ValueError("There is no image to keep yet; generate it in Cast.")
    if kind == "characters" and appearance is None:
        if entity_id not in current_designs(config, project_dir, bible):
            keep_design(config, project_dir, bible, entity_id)
        builder.design = read_design(config, project_dir, bible, character_ids=[entity_id])
    accept_existing_asset(path, builder.request(kind, entity, appearance), reason="kept after a Story Bible edit")


def carry_over_references(
    config: Config, project_dir: Path, before: StoryBible, after: StoryBible, kind: str, entity_id: str,
) -> int:
    """Keep an entity's current references through an edit that changed no appearance.

    A rename, alias, relationship or look label is part of the request text
    but not of what the image shows, so references that matched the request
    before the edit stay current after it. A reference whose look changed is
    never carried over. Returns how many were carried over.
    """
    from novel_to_comic.asset_generation import accept_existing_asset
    from novel_to_comic.story_bible_edits import NON_VISUAL_FIELDS

    def items(bible: StoryBible) -> dict:
        return {
            (appearance.id if appearance is not None else None): (entity, appearance)
            for item_kind, entity, appearance in _reference_items(bible)
            if item_kind == kind and entity.id == entity_id
        }

    def looks(entity, appearance) -> tuple[dict, dict | None]:
        base = entity.model_dump(exclude=set(NON_VISUAL_FIELDS) | {"appearance_states", "appearance_timeline"})
        return base, appearance.model_dump(exclude={"label"}) if appearance is not None else None

    old_items, new_items = items(before), items(after)
    old = _ReferenceRequests(config, project_dir, before, None)
    new = _ReferenceRequests(config, project_dir, after, None)
    if kind == "characters":
        try:
            if entity_id not in current_designs(config, project_dir, before):
                return 0
            old.design = read_design(config, project_dir, before, character_ids=[entity_id])
            new.design = read_design(config, project_dir, after, character_ids=[entity_id])
        except (OSError, ValueError):
            return 0
    kept = 0
    for state_id, (entity, appearance) in old_items.items():
        if state_id not in new_items or looks(entity, appearance) != looks(*new_items[state_id]):
            continue
        path = old.path(kind, entity, appearance)
        if not path.exists():
            continue
        try:
            if not asset_matches_request(path, old.request(kind, entity, appearance)):
                continue
            updated = new.request(kind, *new_items[state_id])
        except (OSError, ValueError):
            continue
        if not asset_matches_request(path, updated):
            accept_existing_asset(path, updated, reason="kept: the edit changed no appearance details")
        kept += 1
    return kept


def ready_asset_count(config: Config, project_dir: Path) -> int | None:
    """Count a complete, current Cast inventory without generating any assets.

    Individually generated references are sufficient for review. The optional
    calibration board is an input when present, not a required Cast output.
    """
    bible = read_cast_story_bible(project_dir, safe=True)
    if bible is None:
        return None
    if bible.characters and review_status(config, project_dir)["status"] != "current":
        return None
    requests = []
    try:
        design = read_design(config, project_dir, bible) if bible.characters else None
        builder = _ReferenceRequests(config, project_dir, bible, design)
        for kind, entity, appearance in _reference_items(bible):
            requests.append((builder.path(kind, entity, appearance), builder.request(kind, entity, appearance)))
    except (OSError, ValueError):
        # Missing/unreadable parents and incompatible reference contracts remain
        # pending; status inspection must never turn into generation or recovery.
        return None
    if not requests or not all(asset_matches_request(path, request) for path, request in requests):
        return None
    return len(requests)


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.usage import estimate_image_cost
    from novel_to_comic.asset_generation import estimate_non_panel_request

    story_bible = read_cast_story_bible(project_dir, safe=True)
    if story_bible is None:
        return 0.0

    missing_state_refs = []
    missing_location_states: list[tuple[str, str]] = []
    for loc in story_bible.locations:
        for stem, _anchor, state_id in _location_plate_jobs(loc):
            if (series_root(project_dir) / "plates" / f"{stem}.png").exists():
                continue
            if state_id:
                missing_location_states.append((loc.id, state_id))
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    style_plan = style_reference_plan(config, style_ref)
    total = estimate_design_review(config, project_dir, story_bible) if story_bible.characters else 0.0
    character_style_ref = _character_style_reference(config, project_dir, style_ref)
    character_style_plan = style_reference_plan(config, character_style_ref or style_ref)
    try:
        designs = current_designs(config, project_dir, story_bible)
    except (ValueError, OSError):
        designs = {}
    # Only characters without a current design (new or changed) are redesigned.
    design = CastDesignPlan(characters=list(designs.values()), fingerprints={})
    dirty_characters = set()
    for char in story_bible.characters:
        input_data = _character_generation_input(config, story_bible, char,
            _read_character_ref_addendum(project_dir, char.id), design=design)
        request = _compile_cast_request(config, project_dir, input_data, reference_plan=character_style_plan)
        if char.id not in designs or character_style_ref is None or not asset_matches_request(
                artifacts.character_ref_sheet_path(project_dir, char.id), request):
            dirty_characters.add(char.id)
            total += estimate_non_panel_request(
                config, input_data,
                reference_plan=character_style_plan,
            ).cost_usd
        for appearance in char.appearance_states or []:
            if not appearance.visually_significant:
                continue
            path = artifacts.character_state_ref_sheet_path(project_dir, char.id, appearance.id)
            dirty = char.id in dirty_characters or not path.exists()
            if not dirty:
                spec = build_character_state_spec(config, project_dir, char, appearance, style_path=character_style_ref)
                dirty = not asset_matches_request(path, _compile_state_asset_wire(config, spec, project_dir))
            if dirty:
                missing_state_refs.append((char.id, appearance.id))
    if story_bible.locations and style_ref is not None and _location_style_board(config, project_dir) is None:
        total += estimate_non_panel_request(
            config, _location_style_board_input(config), reference_plan=style_plan,
        ).cost_usd
    for loc in story_bible.locations:
        for stem, anchor, state_id in _location_plate_jobs(loc):
            if state_id is None and not (series_root(project_dir) / "plates" / f"{stem}.png").exists():
                # The board stands in for itself before it exists: one style image either way.
                total += estimate_non_panel_request(
                    config, _location_generation_input(config, loc, anchor=anchor),
                    reference_plan=_location_plate_reference_plan(config, style_ref),
                ).cost_usd
    for prop in story_bible.props:
        if not artifacts.prop_ref_path(project_dir, prop.id).exists():
            total += estimate_non_panel_request(
                config, _prop_generation_input(config, prop), reference_plan=style_plan,
            ).cost_usd

    from novel_to_comic.state_assets import state_reference_dimensions

    model = config.effective_image_model()
    quality = getattr(config, "image_quality", None)

    def state_cost(kind: str, entity_id: str, state_id: str) -> float:
        width, height = state_reference_dimensions(config, kind)
        return estimate_image_cost(
            model, 1, quality=quality, width=width, height=height,
            ref_count=estimate_state_reference_count(config, project_dir, kind, entity_id, state_id),
        )

    for entity_id, state_id in missing_state_refs:
        total += state_cost("character", entity_id, state_id)
    for entity_id, state_id in missing_location_states:
        total += state_cost("location", entity_id, state_id)
    for prop in story_bible.props:
        for appearance in prop.appearance_states:
            if (appearance.visually_significant and not appearance.canonical_equivalent
                    and not artifacts.prop_state_ref_path(project_dir, prop.id, appearance.id).exists()):
                total += state_cost("prop", prop.id, appearance.id)
    return total


STAGE = Stage(
    name="cast",
    run=run,
    outputs=lambda d: [d / "refs"],
    clean_paths=lambda d: clean_cascade(d, "refs"),
    estimate_cost=estimate_cost,
)
