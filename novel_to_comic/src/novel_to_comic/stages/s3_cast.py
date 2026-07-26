"""Stage 3: character reference images + location plates.

Part A: Generate character reference sheets
Part B: Generate location background plates
"""

import asyncio
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_ref_strategy import RefStrategy
from novel_to_comic.events import make_progress
from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.generation import PromptAnchor, PromptSubject
from novel_to_comic.models.story_bible import Character, Prop, StoryBible
from novel_to_comic.asset_versions import record_asset_version
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state_assets import (
    StateAssetGenerationSpec,
    build_character_state_spec,
    build_location_state_spec,
    mark_dependent_states_stale,
)
from novel_to_comic.asset_generation import (
    AbstractStyleProofInput,
    CanonicalCharacterReferenceInput,
    CanonicalLocationPlateInput,
    CharacterStateReferenceInput,
    LocationStatePlateInput,
    PropReferenceInput,
    asset_matches_request,
    compile_non_panel_request,
    style_reference_plan,
    submit_non_panel_request,
)
from novel_to_comic.text_utils import clean, shorten
from novel_to_comic.usage import ApiResult

console = Console()


_clean = clean
_shorten = shorten

def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in {"the", "and", "with", "his", "her"}
    }


def _character_signature(char: Character) -> str:
    features = ", ".join(_clean(f) for f in char.distinguishing_features[:4])
    pieces = [
        f"{char.name}: {_clean(char.age_range)} {_clean(char.gender)}".strip(),
        features,
        _clean(char.default_outfit),
    ]
    return _shorten("; ".join(piece for piece in pieces if piece), 220)


def _similar_cast_members(char: Character, story_bible: StoryBible) -> list[Character]:
    char_outfit_tokens = _tokens(char.default_outfit)
    matches = []
    for other in story_bible.characters:
        if other.id == char.id:
            continue
        other_outfit_tokens = _tokens(other.default_outfit)
        outfit_overlap = len(char_outfit_tokens & other_outfit_tokens)
        if outfit_overlap >= 1:
            matches.append((outfit_overlap, other))
    return [other for _overlap, other in sorted(matches, key=lambda item: item[0], reverse=True)[:3]]


def _cast_identity_lock(char: Character, story_bible: StoryBible) -> str:
    similar = _similar_cast_members(char, story_bible)
    if not similar:
        return (
            f"CAST IDENTITY LOCK: Only {char.name} appears in this reference sheet. "
            f"Preserve these unique traits: {_character_signature(char)}."
        )

    comparisons = []
    own_features = _character_signature(char)
    for other in similar:
        comparisons.append(
            f"distinct from {other.name}, who is {_character_signature(other)}"
        )
    return (
        f"CAST IDENTITY LOCK: Only {char.name} appears in this reference sheet. "
        f"{char.name} must be immediately recognizable as {_shorten(own_features, 180)}. "
        f"Keep this face, hairline, build, posture, and silhouette visually "
        f"{'; '.join(comparisons)}. Do not merge cast members into one generic person."
    )


_SHEET_POSE_BOXES: dict[str, tuple[float, float, float, float]] = {
    # Two-view sheet produced by the character prompt: a large facial-identity
    # crop and a large body/proportion crop. Fractions are (x0, y0, x1, y1).
    "portrait":  (0.0, 0.0, 0.5, 1.0),
    "full_body": (0.5, 0.0, 1.0, 1.0),
}


def _crop_sheet_to_poses(sheet_path: Path) -> None:
    """Crop a two-view character reference sheet into reusable reference PNGs.

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
        return str(path.relative_to(project_dir))
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




def _find_style_ref(project_dir: Path, style_template: str) -> Path | None:
    """Return the sample image that matches the active style template.

    Tries to match by comparing the template text against saved suggestions.
    Returns None if no exact sample exists. This avoids conditioning refs and
    panels on a sample from a different active style.
    """
    suggestions_path = artifacts.style_suggestions_path(project_dir)
    if suggestions_path.exists():
        try:
            data = json.loads(suggestions_path.read_text())
            suggestions = data.get("suggestions", [])
            for i, s in enumerate(suggestions, 1):
                if isinstance(s, dict) and s.get("template", "").strip() == style_template.strip():
                    candidate = artifacts.style_sample_path(project_dir, i)
                    if candidate.exists():
                        return candidate
        except Exception:
            pass

    return None


def _cast_asset_style_ref(config: Config, style_ref: Path | None) -> Path | None:
    return RefStrategy.for_config(config).cast_style_ref(style_ref)


def _style_authority_block(asset_kind: str) -> str:
    return (
        "STYLE AUTHORITY:\n"
        f"- The selected style above is mandatory for this {asset_kind}, not decorative.\n"
        "- Preserve the style's medium, mark-making, palette, lighting language, edge quality, "
        "shape design, and rendering density.\n"
        "- Layout or reference-format constraints below describe composition only; do not let "
        "them flatten the image into generic clean concept art, photorealism, anime, or default "
        "digital illustration.\n"
        "- If a style reference image is provided, treat it as the visual authority for how "
        "surfaces are painted, lit, simplified, and finished."
    )


def _state_anatomy_directive(char_name: str, state: AppearanceState) -> str:
    """Force a state sheet to depict the altered body consistently.

    The two-view sheet renders the figure twice, so a changed body part (lost
    hands, prosthetics) must remain consistent between the portrait and the
    full-body view. State-agnostic: this pins whatever the anchor describes,
    sharpened by the authored continuity_guard when present.
    """
    lines = [
        f"APPEARANCE STATE — this sheet depicts {char_name} in a specific altered state: {state.label}.",
        "The altered body (hands, limbs, or other changed features) MUST look identical in both "
        "views and match the description above exactly — never show a different version of it in "
        "either view, and never blend in the character's other appearance states.",
    ]
    guard = (state.continuity_guard or "").strip()
    if guard:
        lines.append(f"Continuity rule: {guard}.")
    return " ".join(lines)


def _character_ref_prompt(
    config: Config,
    story_bible: StoryBible,
    char: Character,
    addendum: str = "",
    state: AppearanceState | None = None,
) -> str:
    # Both views in one image keep facial identity and body design coherent.
    identity_lock = _cast_identity_lock(char, story_bible)
    addendum_block = f"\nUSER FIX NOTE: {addendum.strip()}\n" if addendum.strip() else ""
    state_block = f"\n{_state_anatomy_directive(char.name, state)}\n" if state is not None else ""
    return (
        f"{config.style_template}\n\n"
        f"{_style_authority_block('character reference sheet')}\n\n"
        f"CHARACTER REFERENCE SHEET - {char.name}, {char.gender}.\n"
        f"{identity_lock}\n"
        f"{char.visual_anchor}\n"
        f"{addendum_block}"
        f"{state_block}\n"
        f"One square image divided into two equal vertical panels: "
        f"left: head-and-shoulders three-quarter portrait with a restrained neutral expression; "
        f"right: neutral full-body three-quarter standing view with relaxed arms and anatomy-compatible hands. "
        f"Both depictions are the SAME character - identical face, hair, build, proportions, and clothing. "
        f"Use believable adult anatomy and a natural head-to-body ratio appropriate to the described build. "
        f"Never chibi, super-deformed, big-headed, doll-like, toy-like, mascot-like, or caricatured. "
        f"Each depiction is fully contained within its half with white space around it. "
        f"Plain uncluttered reference background; a subtle style-colored studio wash or cast light is allowed, but no scenery. "
        f"The right figure is full body, head to toe, with no cropping. No text, labels, or divider line. "
        f"Clean controlled surfaces; no noisy grain, speckled dappling, repeated texture fields, or muddy micro-detail.\n\n"
        f"Render every figure in the style described above."
    )



def _character_ref_clean_text_prompt(
    config: Config,
    char: Character,
    addendum: str = "",
    state: AppearanceState | None = None,
) -> str:
    style = config.style_template.strip()
    name = char.name
    gender = char.gender
    anchor = char.visual_anchor.strip()
    outfit = char.default_outfit.strip()

    style = RefStrategy.for_config(config).clamp_style_text(style)

    parts = [
        style,
        f"CHARACTER REFERENCE SHEET - {name}, {gender}.",
        anchor,
    ]
    if outfit:
        parts.append(f"Default clothing: {outfit}")
    if addendum.strip():
        parts.append(f"USER FIX NOTE: {addendum.strip()}")
    if state is not None:
        parts.append(_state_anatomy_directive(name, state))

    grid_desc = (
        "One square image divided into two equal vertical panels showing the SAME character: "
        "left: head-and-shoulders three-quarter portrait; right: neutral full-body "
        "three-quarter standing view with relaxed arms and anatomy-compatible hands. "
        "Identical face, hair, build, natural adult proportions, and clothing in both panels. "
        "Never chibi, super-deformed, big-headed, doll-like, toy-like, mascot-like, or "
        "caricatured. Plain neutral background. No text, labels, or divider line."
    )
    parts.append(grid_desc)

    return "\n\n".join(parts)


def _character_sheet_prompt(
    config: Config,
    story_bible: StoryBible,
    char: Character,
    addendum: str = "",
    state: AppearanceState | None = None,
) -> str:
    if RefStrategy.for_config(config).use_clean_text_character_prompt():
        return _character_ref_clean_text_prompt(config, char, addendum, state)
    return _character_ref_prompt(config, story_bible, char, addendum, state)


def _location_plate_prompt(config: Config, loc, addendum: str = "", anchor: str | None = None) -> str:
    plate_anchor = anchor or loc.visual_anchor
    addendum_text = addendum.strip()
    if RefStrategy.for_config(config).use_structured_location_plate_prompt():
        addendum_block = f"\nUSER FIX NOTE: {addendum_text}\n" if addendum_text else ""
        return (
            f"{config.style_template.strip()}\n\n"
            f"{_style_authority_block('location design plate')}\n\n"
            f"LOCATION DESIGN PLATE\n"
            f"{plate_anchor}\n"
            f"{addendum_block}\n"
            f"Create a clean wide environment design plate, not a texture study. "
            f"No characters present. No text. "
            f"Build the image from large simple readable masses and clear silhouettes. "
            f"Use only the setting elements from the anchor, grouped into major shapes such as "
            f"tree masses, ground plane, path, water, building, fence, sky, or shadow when they apply. "
            f"If the setting contains dense woods, underbrush, leaves, ferns, grass, debris, or bark, "
            f"summarize them as a few grouped shapes with calm gaps between them. "
            f"Leave broad quiet areas of sky, ground, water, or shadow; do not fill every surface. "
            f"Render with clean edges and minimal surface texture in the selected medium. "
            f"Do not render leaf-by-leaf, grass-blade-by-grass-blade, bark-chip-by-bark-chip, "
            f"or fern-frond-by-fern-frond. "
            f"No repeated stamps, pattern tiling, wallpaper texture, speckled dappling, "
            f"noisy grain, muddy micro-detail, or fractal foliage."
        )
    addendum_block = f" USER FIX NOTE: {addendum_text}." if addendum_text else ""
    return (
        f"{config.style_template}\n\n"
        f"{_style_authority_block('location design plate')}\n\n"
        f"{plate_anchor}{addendum_block} "
        f"Wide establishing shot, no characters present, clean readable background, "
        f"cinematic composition. No text. No noisy grain, speckled dappling, "
        f"repeated texture fields, pattern tiling, or muddy micro-detail."
    )


def _location_plate_dimensions(config: Config) -> tuple[int | None, int | None]:
    return RefStrategy.for_config(config).location_plate_dimensions()


def _location_plate_jobs(loc) -> list[tuple[str, str, str | None]]:
    """(plate_stem, anchor, state_id) tuples: the default plate plus one per state.

    Locations with states (pre/post collapse, day/night) need a plate per
    state — otherwise panels in a non-default state get an image reference
    that contradicts their text anchor. State ids extend the parent location
    id, so plates/{stem}.png never collides.
    """
    jobs: list[tuple[str, str, str | None]] = [(loc.id, loc.visual_anchor, None)]
    for state in loc.appearance_states or []:
        jobs.append((state.id, state.visual_anchor, state.id))
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


def _prop_ref_prompt(config: Config, prop: Prop, addendum: str = "") -> str:
    addendum_block = f" USER FIX NOTE: {addendum.strip()}." if addendum.strip() else ""
    return (
        f"{config.style_template}\n\n"
        f"{_style_authority_block('prop reference')}\n\n"
        f"PROP REFERENCE - {prop.name}.\n"
        f"{prop.visual_anchor}{addendum_block}\n\n"
        f"Single object, isolated on a plain neutral mid-grey background. "
        f"Three-quarter view, evenly lit, the object centered and fully visible "
        f"with generous margin on all sides — nothing crops the silhouette. "
        f"No characters, no hands, no scenery, no other objects. "
        f"No text, no labels, no captions. "
        f"Render the object's material, color, condition, and distinctive features "
        f"clearly so it can be matched in later panels. "
        f"Clean controlled surfaces; no noisy grain, speckled dappling, "
        f"repeated texture fields, pattern tiling, or muddy micro-detail."
    )


def _character_generation_input(
    config: Config, story_bible: StoryBible, char: Character, addendum: str = "",
) -> CanonicalCharacterReferenceInput:
    direction = (
        "Square two-view reference sheet: a head-and-shoulders three-quarter portrait on "
        "the left and a neutral full-body three-quarter standing view on the right. Keep "
        "the full-body figure visible head to toe on a plain uncluttered background."
    )
    if addendum.strip():
        direction += f" User fix note: {addendum.strip()}"
    return CanonicalCharacterReferenceInput(
        asset_identity=f"character_ref:{char.id}",
        prompt=GenerationPromptInput(
            subjects=(PromptSubject(
                character_id=char.id, name=char.name, identity=char.visual_anchor,
                baseline_affect=char.baseline_affect,
            ),),
            visual_brief=direction,
            composition="Square two-view character reference sheet, portrait left and full body right.",
            constraints=(
                "Natural adult head-to-body ratio; no chibi, super-deformed, big-headed, "
                "doll-like, toy-like, mascot-like, or caricatured proportions; no text, "
                "labels, divider lines, scenery, or other characters."
            ),
            width=1024,
            height=1024,
            generation_width=1024,
            generation_height=1024,
            generation_shape="square",
        ),
        selected_style_text=config.style_template,
        selected_style_source_hash=hashlib.sha256(config.style_template.encode()).hexdigest(),
    )


def _character_style_board_path(project_dir: Path) -> Path:
    return project_dir / "refs" / "character_style_board.png"


def _character_style_reference(project_dir: Path, fallback: Path | None) -> Path | None:
    """Return the character-domain style authority when it has been generated."""
    board = _character_style_board_path(project_dir)
    return board if board.exists() else fallback


def _character_style_calibration_input(config: Config) -> AbstractStyleProofInput:
    """Build a subject-diverse style board that de-entangles style from identity.

    The approved scene proof often contains one specific person. Character-sheet
    calls can mistake that person's age/build for part of the style, then drift
    toward stereotypes for other bodies. This single calibration image shows
    several unrelated adults under one artistic hand and becomes the style-only
    reference for every canonical and alternate character sheet.
    """
    subjects = (
        PromptSubject(
            name="slim adult", identity="an unrelated slim adult with natural proportions",
        ),
        PromptSubject(
            name="stout adult", identity="an unrelated stout adult with natural proportions",
        ),
        PromptSubject(
            name="older adult", identity="an unrelated older adult with natural proportions",
        ),
    )
    return AbstractStyleProofInput(
        asset_identity="cast:character_style_board",
        prompt=GenerationPromptInput(
            subjects=subjects,
            visual_brief=(
                "Character-rendering calibration board. Show three clearly unrelated adults "
                "standing side by side at the same scale: one slim, one stout, and one older. "
                "Use one shared artistic hand, identical facial-modeling depth, line weight, "
                "mark-making, shadow density, rendering density, and degree of simplification."
            ),
            composition="Landscape three-person character calibration lineup, full body, neutral poses.",
            constraints=(
                "Natural anatomically believable adult head-to-body ratios appropriate to each "
                "build; no chibi, super-deformed, big-headed, doll-like, toy-like, mascot-like, "
                "or caricatured proportions; plain quiet background; no text or labels."
            ),
            width=1344,
            height=768,
            generation_width=1344,
            generation_height=768,
            generation_shape="landscape",
        ),
        selected_style_text=config.style_template,
        selected_style_source_hash=hashlib.sha256(config.style_template.encode()).hexdigest(),
    )


def _location_generation_input(
    config: Config, loc, addendum: str = "", anchor: str | None = None,
) -> CanonicalLocationPlateInput:
    direction = (
        "Clean wide environment design plate with large readable masses, clear silhouettes, "
        "quiet areas of sky, ground, water, or shadow, and no characters."
    )
    if addendum.strip():
        direction += f" User fix note: {addendum.strip()}"
    return CanonicalLocationPlateInput(
        asset_identity=f"location_plate:{loc.id}",
        prompt=GenerationPromptInput(
            anchors=(PromptAnchor(
                kind="location", entity_id=loc.id, name=loc.name,
                text=anchor or loc.visual_anchor,
            ),),
            visual_brief=direction,
            composition="Wide environment design plate with no characters or text.",
            constraints="No text, noisy grain, repeated texture fields, or muddy micro-detail.",
            width=1344,
            height=768,
            generation_width=1344,
            generation_height=768,
            generation_shape="landscape",
        ),
        selected_style_text=config.style_template,
        selected_style_source_hash=hashlib.sha256(config.style_template.encode()).hexdigest(),
    )


def _prop_generation_input(
    config: Config, prop: Prop, addendum: str = "",
) -> PropReferenceInput:
    direction = (
        "Single object isolated on a neutral mid-grey background, three-quarter view, evenly lit, "
        "centered and fully visible with generous margin."
    )
    if addendum.strip():
        direction += f" User fix note: {addendum.strip()}"
    return PropReferenceInput(
        asset_identity=f"prop_ref:{prop.id}",
        prompt=GenerationPromptInput(
            anchors=(PromptAnchor(
                kind="prop", entity_id=prop.id, name=prop.name, text=prop.visual_anchor,
            ),),
            visual_brief=direction,
            composition="Single centered prop reference, no cropping.",
            constraints="No characters, hands, scenery, other objects, text, labels, or captions.",
            width=1024,
            height=1024,
            generation_width=1024,
            generation_height=1024,
            generation_shape="square",
        ),
        selected_style_text=config.style_template,
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
        )]
        anchors = []
        composition = (
            "Square two-view reference sheet with a head-and-shoulders three-quarter "
            "portrait on the left and an anatomy-compatible neutral full-body "
            "three-quarter view on the right; no text or labels."
        )
    else:
        subjects = []
        anchors = [PromptAnchor(
            kind="location", entity_id=spec.entity_id, name=spec.entity_id,
            appearance_state_id=spec.state_id, text=spec.active_state_anchor,
        )]
        composition = "Wide environment design plate with no characters or text."
    return GenerationPromptInput(
        anchors=tuple(anchors), subjects=tuple(subjects), composition=composition,
        visual_brief=spec.state_direction or None,
        constraints=(
            "The active-state anchor wins over canonical mutable facts; preserve the "
            "canonical parent's head-to-body ratio, silhouette, facial modeling, degree "
            "of simplification, line weight, and rendering density; never chibi, "
            "super-deformed, big-headed, doll-like, toy-like, mascot-like, or caricatured."
        ),
        width=spec.effective_width, height=spec.effective_height,
        generation_width=spec.effective_width, generation_height=spec.effective_height,
        generation_shape=spec.requested_shape,
    )


def _compile_state_asset_wire(
    config: Config,
    spec: StateAssetGenerationSpec,
    project_dir: Path,
):
    """Compile one state request and update metadata before transport/cache checks."""
    from novel_to_comic.state_assets import build_state_reference_plan

    prompt = _state_asset_prompt(spec)
    from novel_to_comic.image_models import image_model_profile_for_config

    profile = image_model_profile_for_config(config)
    plan = build_state_reference_plan(spec, project_dir, route_profile=profile)
    input_data = (
        CharacterStateReferenceInput if spec.asset_kind == "character_state_ref"
        else LocationStatePlateInput
    )(
        asset_identity=f"{spec.entity_id}:{spec.state_id}",
        prompt=prompt,
        selected_style_text=config.style_template,
        selected_style_source_hash=spec.style_sha256,
        lineage=spec.lineage_metadata(),
    )
    request = compile_non_panel_request(config, input_data, reference_plan=plan)
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
    submission = await submit_non_panel_request(
        config=config, project_dir=project_dir, request=request,
        output_path=output_path, feature=feature, kind="state_asset_regen",
    )
    return submission.result


async def regenerate_character_ref(
    config: Config,
    project_dir: Path,
    char_id: str,
    semaphore: asyncio.Semaphore | None = None,
) -> ApiResult[Path]:
    story_bible = artifacts.read_story_bible(project_dir)
    char = next((candidate for candidate in story_bible.characters if candidate.id == char_id), None)
    if char is None:
        raise ValueError(f"Character not found: {char_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = project_dir / "refs" / char.id / "sheet.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    approved_style_ref = _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    style_ref = _character_style_reference(project_dir, approved_style_ref)
    addendum = _read_character_ref_addendum(project_dir, char.id)
    input_data = _character_generation_input(config, story_bible, char, addendum)
    request = compile_non_panel_request(
        config, input_data, reference_plan=style_reference_plan(config, style_ref)
    )

    record_asset_version(output_path, project_dir, reason="before_regenerate")
    async with sem:
        submission = await submit_non_panel_request(
            config=config, project_dir=project_dir, request=request,
            output_path=output_path, feature="cast.character_ref",
            kind="character_ref_regen",
        )
    result = submission.result
    assert result is not None
    await asyncio.to_thread(_crop_sheet_to_poses, output_path)
    mark_dependent_states_stale(project_dir, "character", char.id)
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
    story_bible = artifacts.read_story_bible(project_dir)
    char = next((c for c in story_bible.characters if c.id == char_id), None)
    if char is None:
        raise ValueError(f"Character not found: {char_id}")
    state = next((s for s in char.appearance_states or [] if s.id == state_id), None)
    if state is None:
        raise ValueError(f"Appearance state not found: {char_id}/{state_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = project_dir / "refs" / char.id / "states" / state.id / "sheet.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    approved_style_ref = _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    style_ref = _character_style_reference(project_dir, approved_style_ref)
    spec = build_character_state_spec(config, project_dir, char, state, style_path=style_ref)

    record_asset_version(output_path, project_dir, reason="before_regenerate")
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
    story_bible = artifacts.read_story_bible(project_dir)
    prop = next((p for p in story_bible.props if p.id == prop_id), None)
    if prop is None:
        raise ValueError(f"Prop not found: {prop_id}")

    sem = semaphore or asyncio.Semaphore(1)
    output_path = artifacts.prop_ref_path(project_dir, prop.id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    addendum = _read_prop_ref_addendum(project_dir, prop.id)
    input_data = _prop_generation_input(config, prop, addendum)
    request = compile_non_panel_request(
        config, input_data, reference_plan=style_reference_plan(config, style_ref)
    )

    async with sem:
        submission = await submit_non_panel_request(
            config=config, project_dir=project_dir, request=request,
            output_path=output_path, feature="cast.prop_ref", kind="prop_ref_regen",
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
    story_bible = artifacts.read_story_bible(project_dir)
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
        plate_stem = state.id

    sem = semaphore or asyncio.Semaphore(1)
    output_path = project_dir / "plates" / f"{plate_stem}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    if state_id:
        spec = build_location_state_spec(config, project_dir, loc, state, style_path=style_ref)
        request = _compile_state_asset_wire(config, spec, project_dir)
    else:
        addendum = _read_location_plate_addendum(project_dir, loc.id)
        input_data = _location_generation_input(config, loc, addendum, anchor=anchor)
        request = compile_non_panel_request(
            config, input_data, reference_plan=style_reference_plan(config, style_ref)
        )
        spec = None

    record_asset_version(output_path, project_dir, reason="before_regenerate")
    async with sem:
        submission = await submit_non_panel_request(
            config=config, project_dir=project_dir, request=request,
            output_path=output_path,
            feature=("cast.location_state_plate" if state_id else "cast.location_plate"),
            kind="location_plate_regen",
        )
    result = submission.result
    assert result is not None
    if not state_id:
        mark_dependent_states_stale(project_dir, "location", loc.id)
    return result


async def _generate_character_style_board(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
) -> Path | None:
    """Generate the shared character-domain style authority once per cast run."""
    output_path = _character_style_board_path(project_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    approved_style_ref = _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    input_data = _character_style_calibration_input(config)
    request = compile_non_panel_request(
        config,
        input_data,
        reference_plan=style_reference_plan(config, approved_style_ref),
    )

    if asset_matches_request(output_path, request):
        ctx.record_item_done(cost=0.0)
        ctx.log("Using existing character style calibration board", level="dim")
        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
        return output_path

    ctx.log("Generating shared character style calibration board")
    try:
        semaphore = _cast_semaphore(config)
        async with semaphore:
            submission = await submit_non_panel_request(
                config=config,
                project_dir=project_dir,
                request=request,
                output_path=output_path,
                feature="cast.character_style_board",
                kind="character_style_board",
            )
        result = submission.result
        assert result is not None
        ctx.record_item_done(usage=result.usage)
        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
        return output_path
    except Exception as error:
        cause = error.last_attempt.exception() if hasattr(error, "last_attempt") else error
        ctx.record_item_failed("character_style_board")
        ctx.log(
            f"Character style calibration failed; using approved scene proof: {cause}",
            level="error",
        )
        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
        return approved_style_ref


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
    console.print("[bold]Generating character reference images...[/bold]")
    ctx.log("Generating character reference sheets...")
    refs_dir = project_dir / "refs"

    # A visual style reference image is far stronger than text for locking style.
    # Without it, the model applies different stylistic conventions per character
    # type (human → concept art, cat → anime, creature → dark fantasy).
    candidate_style_ref = _find_style_ref(project_dir, config.style_template)
    style_ref = style_ref or _cast_asset_style_ref(config, candidate_style_ref)
    if style_ref:
        console.print(f"[dim]Using style reference: {style_ref.name}[/dim]")
    elif candidate_style_ref:
        console.print(
            "[dim]Skipping style image reference for gpt-image-2 cast refs "
            "to avoid copied subject details and texture artifacts.[/dim]"
        )
    else:
        console.print(
            "[yellow]No style sample found — run `pipeline style` and generate a sample "
            "before indexing for tighter style consistency across character sheets.[/yellow]"
        )

    chars_to_gen = [c for c in story_bible.characters if not char_ids or c.id in char_ids]
    semaphore = _cast_semaphore(config)

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Character refs", total=len(chars_to_gen))

        async def _one_character(char: Character) -> None:
            char_dir = refs_dir / char.id
            char_dir.mkdir(parents=True, exist_ok=True)
            output_path = char_dir / "sheet.png"
            addendum = _read_character_ref_addendum(project_dir, char.id)
            input_data = _character_generation_input(config, story_bible, char, addendum)
            request = compile_non_panel_request(
                config, input_data, reference_plan=style_reference_plan(config, style_ref)
            )

            if asset_matches_request(output_path, request):
                # Migrate older sheets that pre-date cropped-pose references.
                if not (char_dir / "portrait.png").exists():
                    try:
                        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    except Exception:
                        pass
                ctx.record_item_done(cost=0.0)
                ctx.log(f"Using existing ref sheet for {char.name}", level="dim")
            else:
                try:
                    ctx.log(f"Generating ref sheet for {char.name}")
                    # The shared two-view sheet provides both facial identity
                    # and body proportions for framing-aware conditioning.
                    # Pass the style sample when the active image model handles
                    # references reliably; gpt-image-2 cast refs stay text-driven.
                    async with semaphore:
                        submission = await submit_non_panel_request(
                            config=config, project_dir=project_dir, request=request,
                            output_path=output_path, feature="cast.character_ref",
                            kind="character_ref", semaphore=semaphore,
                        )
                    flux_result = submission.result
                    assert flux_result is not None
                    await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    mark_dependent_states_stale(project_dir, "character", char.id)
                    ctx.record_item_done(usage=flux_result.usage)
                except Exception as e:
                    cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                    console.print(f"[red]Failed ref sheet for {char.name}: {cause}[/red]")
                    ctx.record_item_failed(char.id)
                    ctx.log(f"Failed ref sheet for {char.name}: {cause}", level="error")
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
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
    identity lock and two-view layout stay consistent. Output lives under
    refs/<char>/states/<state_id>/ and is selected by prompting.py when that
    state is active for a panel.
    """
    chars = [c for c in story_bible.characters if not char_ids or c.id in char_ids]
    jobs = [(c, sid, anchor) for c in chars for sid, anchor in _character_state_jobs(c)]
    if not jobs:
        return

    console.print("[bold]Generating character appearance-state refs...[/bold]")
    ctx.log("Generating character appearance-state refs...")
    style_ref = style_ref or _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    semaphore = _cast_semaphore(config)

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("State refs", total=len(jobs))

        async def _one_state(char: Character, state_id: str, anchor: str) -> None:
            state_obj = next((s for s in char.appearance_states or [] if s.id == state_id), None)
            out_dir = project_dir / "refs" / char.id / "states" / state_id
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / "sheet.png"
            parent_path = artifacts.character_ref_sheet_path(project_dir, char.id)
            if not parent_path.exists():
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

            if asset_matches_request(output_path, wire):
                if not (out_dir / "portrait.png").exists():
                    try:
                        await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    except Exception:
                        pass
                ctx.record_item_done(cost=0.0)
                ctx.log(f"Using existing {state_id} ref for {char.name}", level="dim")
            else:
                try:
                    ctx.log(f"Generating {state_id} ref for {char.name}")
                    async with semaphore:
                        flux_result = await _generate_state_asset_wire(
                            config, spec, output_path, project_dir,
                            feature="cast.character_state_ref", request=wire,
                        )
                    await asyncio.to_thread(_crop_sheet_to_poses, output_path)
                    ctx.record_item_done(usage=flux_result.usage)
                except Exception as e:
                    cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                    console.print(f"[red]Failed {state_id} ref for {char.name}: {cause}[/red]")
                    ctx.record_item_failed(f"{char.id}:{state_id}")
                    ctx.log(f"Failed {state_id} ref for {char.name}: {cause}", level="error")
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
            if task is not None:
                progress.advance(task)

        await asyncio.gather(*(_one_state(*job) for job in jobs))


async def _generate_location_plates(
    config: Config, project_dir: Path, story_bible: StoryBible, ctx: StageRuntime,
    loc_ids: list[str] | None = None,
) -> None:
    """Part C: Generate location background plates — one per location state."""
    console.print("[bold]Generating location plates...[/bold]")
    ctx.log("Generating location plates...")
    plates_dir = project_dir / "plates"
    plates_dir.mkdir(parents=True, exist_ok=True)

    locs_to_gen = [loc for loc in story_bible.locations if not loc_ids or loc.id in loc_ids]
    plate_jobs = [
        (loc, stem, anchor, state_id)
        for loc in locs_to_gen
        for stem, anchor, state_id in _location_plate_jobs(loc)
    ]
    style_ref = _cast_asset_style_ref(
        config,
        _find_style_ref(project_dir, config.style_template),
    )
    semaphore = _cast_semaphore(config)

    with make_progress(ctx.on_event) as progress:
        task = progress.add_task("Location plates", total=len(plate_jobs))

        async def _one_plate(loc, stem: str, anchor: str, state_id: str | None) -> None:
            label = f"{loc.name} ({state_id})" if state_id else loc.name
            output_path = plates_dir / f"{stem}.png"
            if state_id:
                state = next(s for s in loc.appearance_states if s.id == state_id)
                spec = build_location_state_spec(
                    config, project_dir, loc, state, style_path=style_ref
                )
                # Build the conditioning plan up front so lineage metadata is
                # (including request hashes) is available for the cache check.
                # Canonical-first scheduling guarantees the parent plate exists
                # here, and the exact compiled wire is reused on a miss.
                wire = _compile_state_asset_wire(config, spec, project_dir)
            else:
                addendum = _read_location_plate_addendum(project_dir, loc.id)
                input_data = _location_generation_input(config, loc, addendum, anchor=anchor)
                wire = compile_non_panel_request(
                    config, input_data, reference_plan=style_reference_plan(config, style_ref)
                )
                spec = None
            if asset_matches_request(output_path, wire):
                ctx.record_item_done(cost=0.0)
                ctx.log(f"Using existing location plate for {label}", level="dim")
            else:
                try:
                    ctx.log(f"Generating location plate for {label}")
                    async with semaphore:
                        if state_id:
                            flux_result = await _generate_state_asset_wire(
                                config, spec, output_path, project_dir,
                                feature="cast.location_state_plate", request=wire,
                            )
                        else:
                            submission = await submit_non_panel_request(
                                config=config, project_dir=project_dir, request=wire,
                                output_path=output_path, feature="cast.location_plate",
                                kind="location_plate",
                            )
                            flux_result = submission.result
                            assert flux_result is not None
                    if state_id is None:
                        mark_dependent_states_stale(project_dir, "location", loc.id)
                    ctx.record_item_done(usage=flux_result.usage)
                except Exception as e:
                    cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                    console.print(f"[red]Failed plate for {label}: {cause}[/red]")
                    ctx.record_item_failed(stem)
                    ctx.log(f"Failed plate for {label}: {cause}", level="error")
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
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
    so every prop in the bible gets a ref sheet. For models that handle visual
    references reliably, the image is conditioned on the active style sample so
    prop refs share the panel art style. For gpt-image-2, style stays text-only
    to avoid edit-reference texture artifacts.
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
            request = compile_non_panel_request(
                config, input_data, reference_plan=style_reference_plan(config, style_ref)
            )

            if asset_matches_request(output_path, request):
                ctx.record_item_done(cost=0.0)
                ctx.log(f"Using existing prop ref for {prop.name}", level="dim")
            else:
                try:
                    ctx.log(f"Generating prop ref for {prop.name}")
                    async with semaphore:
                        submission = await submit_non_panel_request(
                            config=config, project_dir=project_dir, request=request,
                            output_path=output_path, feature="cast.prop_ref",
                            kind="prop_ref",
                        )
                    flux_result = submission.result
                    assert flux_result is not None
                    ctx.record_item_done(usage=flux_result.usage)
                except Exception as e:
                    cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
                    console.print(f"[red]Failed prop ref for {prop.name}: {cause}[/red]")
                    ctx.record_item_failed(prop.id)
                    ctx.log(f"Failed prop ref for {prop.name}: {cause}", level="error")
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
            if task is not None:
                progress.advance(task)

        await asyncio.gather(*(_one_prop(prop) for prop in props_to_gen))


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    char_ids: list[str] | None = None,
    loc_ids: list[str] | None = None,
    prop_ids: list[str] | None = None,
) -> None:
    """Execute Stage 3: generate character refs, location plates, and prop refs."""
    story_bible = artifacts.read_story_bible(project_dir)

    is_partial = bool(char_ids or loc_ids or prop_ids)
    should_generate_refs = not is_partial or char_ids is not None
    should_generate_plates = not is_partial or loc_ids is not None
    should_generate_prop_refs = not is_partial or prop_ids is not None

    total_items = 0
    if should_generate_refs:
        chars_for_count = [c for c in story_bible.characters if not char_ids or c.id in char_ids]
        if chars_for_count:
            total_items += 1  # shared character style calibration board
        total_items += len(chars_for_count)
        total_items += sum(len(_character_state_jobs(c)) for c in chars_for_count)
    if should_generate_plates:
        total_items += sum(
            len(_location_plate_jobs(loc))
            for loc in story_bible.locations
            if not loc_ids or loc.id in loc_ids
        )
    if should_generate_prop_refs:
        total_items += len([p for p in story_bible.props if not prop_ids or p.id in prop_ids])

    with ctx.execute(total=total_items):
        if should_generate_refs:
            character_style_ref = (
                await _generate_character_style_board(config, project_dir, ctx)
                if chars_for_count else None
            )
            await _generate_character_refs(
                config, project_dir, story_bible, ctx, char_ids, character_style_ref
            )
            await _generate_character_state_refs(
                config, project_dir, story_bible, ctx, char_ids, character_style_ref
            )
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)

        if should_generate_plates:
            await _generate_location_plates(config, project_dir, story_bible, ctx, loc_ids)

        if should_generate_prop_refs:
            await _generate_prop_refs(config, project_dir, story_bible, ctx, prop_ids)

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
            console.print("Run [bold]pipeline approve --project . --stage cast[/bold] to continue.")


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
        build_state_reference_plan,
        state_is_total_transformation,
    )

    story_bible = artifacts.read_story_bible(project_dir)
    approved_style_ref = _cast_asset_style_ref(
        config, _find_style_ref(project_dir, config.style_template)
    )
    style_ref = (
        _character_style_reference(project_dir, approved_style_ref)
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


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.usage import estimate_image_cost
    from novel_to_comic.asset_generation import estimate_non_panel_request

    story_bible = artifacts.read_story_bible_safe(project_dir)
    if story_bible is None:
        return 0.0

    missing_state_refs = [
        (char.id, state_id)
        for char in story_bible.characters
        for state_id, _anchor in _character_state_jobs(char)
        if not (project_dir / "refs" / char.id / "states" / state_id / "sheet.png").exists()
    ]
    missing_location_states: list[tuple[str, str]] = []
    for loc in story_bible.locations:
        for stem, _anchor, state_id in _location_plate_jobs(loc):
            if (project_dir / "plates" / f"{stem}.png").exists():
                continue
            if state_id:
                missing_location_states.append((loc.id, state_id))
    style_ref = _cast_asset_style_ref(config, _find_style_ref(project_dir, config.style_template))
    style_plan = style_reference_plan(config, style_ref)
    total = 0.0
    character_style_ref = _character_style_reference(project_dir, style_ref)
    character_style_plan = style_reference_plan(config, character_style_ref)
    if story_bible.characters and not _character_style_board_path(project_dir).exists():
        total += estimate_non_panel_request(
            config,
            _character_style_calibration_input(config),
            reference_plan=style_plan,
        ).cost_usd
    for char in story_bible.characters:
        if not (project_dir / "refs" / char.id / "sheet.png").exists():
            total += estimate_non_panel_request(
                config, _character_generation_input(config, story_bible, char),
                reference_plan=character_style_plan,
            ).cost_usd
    for loc in story_bible.locations:
        for stem, anchor, state_id in _location_plate_jobs(loc):
            if state_id is None and not (project_dir / "plates" / f"{stem}.png").exists():
                total += estimate_non_panel_request(
                    config, _location_generation_input(config, loc, anchor=anchor),
                    reference_plan=style_plan,
                ).cost_usd
    for prop in story_bible.props:
        if not artifacts.prop_ref_path(project_dir, prop.id).exists():
            total += estimate_non_panel_request(
                config, _prop_generation_input(config, prop), reference_plan=style_plan,
            ).cost_usd

    model = config.effective_image_model()
    quality = getattr(config, "image_quality", None)
    for entity_id, state_id in missing_state_refs:
        total += estimate_image_cost(
            model, 1, quality=quality,
            ref_count=estimate_state_reference_count(
                config, project_dir, "character", entity_id, state_id,
            ),
        )
    for entity_id, state_id in missing_location_states:
        total += estimate_image_cost(
            model, 1, quality=quality,
            ref_count=estimate_state_reference_count(
                config, project_dir, "location", entity_id, state_id,
            ),
        )
    return total


STAGE = Stage(
    name="cast",
    run=run,
    outputs=lambda d: [d / "refs"],
    clean_paths=lambda d: clean_cascade(d, "refs"),
    estimate_cost=estimate_cost,
)
