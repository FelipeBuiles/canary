"""Compact image prompt composition for panel generation."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.text_utils import clean, shorten


_SHOT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "close-up": (768, 1024),
    "over-shoulder": (768, 1024),
    "medium": (768, 1344),
    "wide": (768, 1344),
    "extreme-wide": (768, 1344),
}
_DEFAULT_DIMENSIONS = (768, 1344)

_SHOT_COMPOSITION: dict[str, str] = {
    "close-up": "close-up portrait, eye-level, face and shoulders filling the vertical panel",
    "medium": "medium vertical panel, full body visible, character in the lower two-thirds",
    "over-shoulder": "over-the-shoulder vertical panel, one foreground shoulder, the other face visible",
    "wide": "wide vertical panel, full bodies visible with significant surrounding environment",
    "extreme-wide": "extreme-wide establishing panel, environment dominant, characters small but readable",
}

_PROMPT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "composition": "Composition",
        "setting": "Setting",
        "key_props": "Key props",
        "expression": "expression",
        "position": "position",
        "wardrobe_override": "current wardrobe (overrides any clothing mentioned above)",
        "character": "character",
        "characters": "characters",
        "one_body": "one body per listed character",
        "no_lettering": "no text, captions, speech balloons, or lettering anywhere in the image",
        "style_authority": "Use the selected visual style above as authoritative if later prompt text conflicts.",
    },
    "es": {
        "composition": "Composición",
        "setting": "Escenario",
        "key_props": "Objetos clave",
        "expression": "expresión",
        "position": "posición",
        "wardrobe_override": "vestuario actual (sobrescribe cualquier ropa mencionada arriba)",
        "character": "personaje",
        "characters": "personajes",
        "one_body": "un cuerpo por cada personaje listado",
        "no_lettering": "sin texto, cartelas, globos ni rotulación en ninguna parte de la imagen",
        "style_authority": "Usa el estilo visual seleccionado arriba como autoridad si el texto posterior entra en conflicto.",
    },
    "fr": {
        "composition": "Composition",
        "setting": "Décor",
        "key_props": "Accessoires clés",
        "expression": "expression",
        "position": "position",
        "wardrobe_override": "tenue actuelle (remplace tout vêtement mentionné au-dessus)",
        "character": "personnage",
        "characters": "personnages",
        "one_body": "un seul corps par personnage listé",
        "no_lettering": "aucun texte, cartouche, bulle ni lettrage nulle part dans l'image",
        "style_authority": "Utilise le style visuel sélectionné ci-dessus comme référence si le texte suivant le contredit.",
    },
}


def dimensions_for_shot(shot_type: str) -> tuple[int, int]:
    return _SHOT_DIMENSIONS.get(shot_type.lower().replace(" ", "-"), _DEFAULT_DIMENSIONS)


def _labels(config: Config | None = None) -> dict[str, str]:
    code = config.language_code() if config else "en"
    return _PROMPT_LABELS.get(code, _PROMPT_LABELS["en"])


_clean = clean
_shorten = shorten
IMAGE_PROMPT_VERSION = 7


def _character_identity(
    character: Character,
    scene_appearance: str | None = None,
    labels: dict[str, str] | None = None,
) -> str:
    """Assemble the identity blob for one subject.

    Keeps the full visual_anchor verbatim — the anchor carries permanent
    identity (face, build, hair, distinguishing marks) AND the character's
    default wardrobe tags. When scene_appearance is set, we append it with
    an explicit override directive so the model knows this panel's clothing
    supersedes any wardrobe tags in the anchor, without us having to strip
    those tags and lose the richer description.
    """
    label_set = labels or _PROMPT_LABELS["en"]
    anchor = _clean(character.visual_anchor)
    default_outfit = _clean(character.default_outfit)
    scene_override = _clean(scene_appearance)

    parts: list[str] = [anchor] if anchor else []
    if scene_override:
        parts.append(f"{label_set['wardrobe_override']}: {_shorten(scene_override, 180)}")
    elif default_outfit:
        parts.append(_shorten(default_outfit, 180))

    return "; ".join(part for part in parts if part)


def _reference_paths(project_dir: Path, character_id: str, character_count: int) -> list[str]:
    """Return subject ref paths for one character, ordered by priority.

    Prefers individual pose crops (front/three_quarter/gesture) over the 2x2
    sheet composite — passing the grid directly leaks its layout into the
    model's panel compositions. Falls back to sheet.png only when crops are
    not yet available (e.g. projects generated before cropping was added).
    """
    char_ref_dir = project_dir / "refs" / character_id

    if character_count <= 1:
        views = ["front", "three_quarter", "gesture"]
    elif character_count == 2:
        views = ["front", "three_quarter"]
    else:
        views = ["front"]
    cropped = [str(p) for v in views if (p := char_ref_dir / f"{v}.png").exists()]
    if cropped:
        return cropped

    sheet = char_ref_dir / "sheet.png"
    if sheet.exists():
        return [str(sheet)]
    return []


def _panel_text_blob(panel: PanelBreakdown) -> str:
    pieces: list[str] = [
        panel.background_description,
        panel.lighting,
        panel.mood,
        panel.sfx or "",
    ]
    pieces.extend(panel.character_actions.values())
    pieces.extend(line.text for line in panel.dialogue)
    return " ".join(pieces).lower()


def _panel_props(panel: PanelBreakdown, story_bible: StoryBible) -> list[str]:
    blob = _panel_text_blob(panel)
    props: list[str] = []
    for prop in getattr(story_bible, "props", []):
        name = prop.name.lower()
        prop_id = (prop.id or "").lower()
        if name in blob or (prop_id and prop_id in blob):
            props.append(f"{prop.name}: {_shorten(prop.visual_anchor, 120)}")
    return props


def build_continuity_note(
    current_panel: PanelBreakdown,
    prev_panel: PanelBreakdown | None,
) -> str | None:
    """Build narrative chain from previous panel's state.

    Returns a string like:
    "CONTINUING FROM: Sara stands at the hospital door, hand on the frame,
    expression worried. Marcus lies in the hospital bed, eyes closed, IV drip nearby.
    TRANSITION: fade. Now: Close-up on Sara's face, tears in her eyes."
    """
    if not prev_panel:
        return None

    prev_state_parts: list[str] = []
    for char_id in prev_panel.characters_present:
        action = prev_panel.character_actions.get(char_id, "")
        expression = prev_panel.character_expressions.get(char_id, "")
        position = prev_panel.character_positions.get(char_id, "")
        parts = [p for p in [action, expression, position] if p]
        if parts:
            prev_state_parts.append(f"{char_id}: {', '.join(parts)}")

    prev_state_str = "; ".join(prev_state_parts) if prev_state_parts else "scene continues"

    curr_action_parts: list[str] = []
    for char_id in current_panel.characters_present:
        action = current_panel.character_actions.get(char_id, "")
        expression = current_panel.character_expressions.get(char_id, "")
        parts = [p for p in [action, expression] if p]
        if parts:
            curr_action_parts.append(f"{char_id}: {', '.join(parts)}")

    curr_str = "; ".join(curr_action_parts) if curr_action_parts else "scene continues"

    parts: list[str] = [f"CONTINUING FROM: {prev_state_str}."]
    if prev_panel.transition_note:
        parts.append(f"TRANSITION: {prev_panel.transition_note}.")
    parts.append(f"Now: {curr_str}.")
    return " ".join(parts)


def build_image_prompt_spec(
    config: Config,
    project_dir: Path,
    panel: PanelBreakdown,
    story_bible: StoryBible,
    prev_panel: PanelBreakdown | None = None,
) -> ImagePrompt:
    character_count = len(panel.characters_present)
    subjects: list[PromptSubject] = []
    ref_paths: list[str] = []
    labels = _labels(config)

    scene = next((s for s in story_bible.scenes if s.id == panel.scene_id), None)

    for character_id in panel.characters_present:
        character = next((c for c in story_bible.characters if c.id == character_id), None)
        if not character:
            continue
        scene_appearance = None
        if scene:
            scene_appearance = scene.character_appearances.get(character_id)
        subjects.append(
            PromptSubject(
                character_id=character_id,
                name=character.name,
                identity=_character_identity(character, scene_appearance, labels),
                action=_clean(panel.character_actions.get(character_id, "")),
                expression=_clean(panel.character_expressions.get(character_id, "")),
                position=_clean(panel.character_positions.get(character_id, "")),
            )
        )
        ref_paths.extend(_reference_paths(project_dir, character_id, character_count))

    location = None
    if scene:
        location = next((loc for loc in story_bible.locations if loc.id == scene.location_id), None)

    shot_key = panel.shot_type.lower().replace(" ", "-")
    composition = _SHOT_COMPOSITION.get(
        shot_key,
        f"{_clean(panel.shot_type)} panel, {_clean(panel.camera_angle)} camera",
    )
    if panel.camera_angle:
        composition = f"{composition}, {_clean(panel.camera_angle)} camera"

    setting_parts = []
    if location and location.visual_anchor:
        setting_parts.append(_shorten(location.visual_anchor, 180))
    if panel.background_description:
        setting_parts.append(_shorten(panel.background_description, 160))

    width, height = dimensions_for_shot(panel.shot_type)
    setting = "; ".join(setting_parts)
    lighting = _clean(panel.lighting)
    mood = _clean(panel.mood)
    props = _panel_props(panel, story_bible)
    character_label = labels["character"] if character_count == 1 else labels["characters"]
    constraints = (
        f"exactly {character_count} {character_label}; "
        f"{labels['one_body']}; {labels['no_lettering']}"
    )
    full_prompt = _render_panel_prompt_body_parts(
        labels=labels,
        subjects=subjects,
        composition=composition,
        setting=setting,
        lighting=lighting,
        mood=mood,
        props=props,
        constraints=constraints,
    )

    prompt = ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
        scene_id=panel.scene_id,
        panel_number=panel.panel_number,
        full_prompt=full_prompt,
        style=config.style_template,
        composition=composition,
        setting=setting,
        lighting=lighting,
        mood=mood,
        subjects=subjects,
        props=props,
        constraints=constraints,
        reference_image_paths=ref_paths,
        negative_prompt=None,
        width=width,
        height=height,
        steps=config.effective_image_steps(),
        guidance_scale=config.flux_guidance_scale,
        continuity_note=build_continuity_note(panel, prev_panel),
    )
    return prompt


def _render_panel_prompt_body_parts(
    *,
    labels: dict[str, str] | None = None,
    subjects: list[PromptSubject],
    composition: str | None,
    setting: str | None,
    lighting: str | None,
    mood: str | None,
    props: list[str],
    constraints: str | None,
) -> str:
    label_set = labels or _PROMPT_LABELS["en"]
    sentences: list[str] = []

    if subjects:
        rendered_subjects = []
        for subject in subjects:
            details = [
                subject.name,
                subject.identity,
                subject.action,
                f"{label_set['expression']}: {subject.expression}" if subject.expression else "",
                f"{label_set['position']}: {subject.position}" if subject.position else "",
            ]
            rendered_subjects.append(", ".join(_clean(part) for part in details if _clean(part)))
        sentences.append("; ".join(rendered_subjects))

    if composition:
        sentences.append(f"{label_set['composition']}: {_clean(composition)}")

    setting_line_parts = [_clean(setting), _clean(lighting), _clean(mood)]
    setting_line = "; ".join(part for part in setting_line_parts if part)
    if setting_line:
        sentences.append(f"{label_set['setting']}: {setting_line}")

    if props:
        sentences.append(f"{label_set['key_props']}: {'; '.join(_clean(prop) for prop in props)}")

    if constraints:
        sentences.append(_clean(constraints))

    body = ". ".join(sentence.rstrip(" .") for sentence in sentences if sentence).strip()
    return f"{body}." if body else ""


def render_panel_prompt_body(prompt: ImagePrompt) -> str:
    """Render the compact panel-specific prompt body, excluding global style."""
    return _render_panel_prompt_body_parts(
        subjects=getattr(prompt, "subjects", []) or [],
        composition=getattr(prompt, "composition", None),
        setting=getattr(prompt, "setting", None),
        lighting=getattr(prompt, "lighting", None),
        mood=getattr(prompt, "mood", None),
        props=getattr(prompt, "props", []) or [],
        constraints=getattr(prompt, "constraints", None),
    )


def render_generation_prompt(prompt: ImagePrompt, style_template: str) -> str:
    style = _clean(style_template or getattr(prompt, "style", None))

    if getattr(prompt, "prompt_version", 1) >= 2:
        body = _clean(getattr(prompt, "full_prompt", "")) or render_panel_prompt_body(prompt)
        output = f"{style}\n\n{body}" if style else body
    else:
        output = f"{style}\n\n{_PROMPT_LABELS['en']['style_authority']}\n\n{prompt.full_prompt}" if style else getattr(prompt, "full_prompt", "")

    if getattr(prompt, "continuity_note", None):
        output = f"{output}\n\n{prompt.continuity_note}"

    return output
