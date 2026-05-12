"""Compact image prompt composition for panel generation."""

from __future__ import annotations

import re
from pathlib import Path

from novel_to_comic.config import Config, is_gpt_image_2
from novel_to_comic.models.layout_plan import PlannedPanel
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
    "close-up": "close-up portrait, face and shoulders filling the vertical panel",
    "medium": "medium vertical panel, full body visible, character in the lower two-thirds",
    "over-shoulder": "over-the-shoulder vertical panel, one foreground shoulder, the other face visible",
    "wide": "wide vertical panel, full bodies visible with significant surrounding environment",
    "extreme-wide": "extreme-wide establishing panel, environment dominant, characters small but readable",
}

_SHOT_COMPOSITION_EMPTY: dict[str, str] = {
    "close-up": "close-up detail shot, environment or object filling the panel",
    "medium": "medium vertical panel, full environment visible",
    "over-shoulder": "environment panel from an over-shoulder camera angle",
    "wide": "wide vertical panel, environment dominant",
    "extreme-wide": "extreme-wide establishing panel, environment dominant",
}

_PROMPT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "composition": "Composition",
        "setting": "Setting",
        "lighting": "Lighting",
        "mood": "Mood",
        "key_props": "Key props",
        "key_objects": "Key objects",
        "must_show": "Must show",
        "expression": "expression",
        "position": "position",
        "wardrobe_override": "current wardrobe (overrides any clothing mentioned above)",
        "character": "character",
        "characters": "characters",
        "one_body": "one body per listed character",
        "single_instant": "single frozen instant, not a sequence or split-screen",
        "no_lettering": "no text, captions, speech balloons, or lettering anywhere in the image",
        "style_authority": "Use the selected visual style above as authoritative if later prompt text conflicts.",
    },
    "es": {
        "composition": "Composición",
        "setting": "Escenario",
        "lighting": "Iluminación",
        "mood": "Estado de ánimo",
        "key_props": "Objetos clave",
        "key_objects": "Objetos visibles",
        "must_show": "Debe mostrar",
        "expression": "expresión",
        "position": "posición",
        "wardrobe_override": "vestuario actual (sobrescribe cualquier ropa mencionada arriba)",
        "character": "personaje",
        "characters": "personajes",
        "one_body": "un cuerpo por cada personaje listado",
        "single_instant": "un instante congelado, no una secuencia ni pantalla dividida",
        "no_lettering": "sin texto, cartelas, globos ni rotulación en ninguna parte de la imagen",
        "style_authority": "Usa el estilo visual seleccionado arriba como autoridad si el texto posterior entra en conflicto.",
    },
    "fr": {
        "composition": "Composition",
        "setting": "Décor",
        "lighting": "Éclairage",
        "mood": "Ambiance",
        "key_props": "Accessoires clés",
        "key_objects": "Objets visibles",
        "must_show": "À montrer",
        "expression": "expression",
        "position": "position",
        "wardrobe_override": "tenue actuelle (remplace tout vêtement mentionné au-dessus)",
        "character": "personnage",
        "characters": "personnages",
        "one_body": "un seul corps par personnage listé",
        "single_instant": "un seul instant figé, pas une séquence ni un écran divisé",
        "no_lettering": "aucun texte, cartouche, bulle ni lettrage nulle part dans l'image",
        "style_authority": "Utilise le style visuel sélectionné ci-dessus comme référence si le texte suivant le contredit.",
    },
}


def dimensions_for_shot(shot_type: str) -> tuple[int, int]:
    return _SHOT_DIMENSIONS.get(shot_type.lower().replace(" ", "-"), _DEFAULT_DIMENSIONS)


def dimensions_for_panel(panel: PlannedPanel) -> tuple[int, int]:
    shape_intent = getattr(panel, "shape_intent", None)
    generation_mode = getattr(panel, "generation_mode", None)
    if shape_intent in {"wide", "panorama", "bleed"}:
        return (1344, 768) if generation_mode == "exact" else (1536, 1024)
    if shape_intent == "tall":
        return (768, 1536) if generation_mode == "exact" else (1024, 1536)
    return dimensions_for_shot(panel.shot_type)


def _single_instant_direction(text: str) -> str:
    """Collapse sequential same-character action into the final drawable instant."""
    cleaned = _clean(text)
    if not cleaned:
        return ""
    parts = [
        part.strip(" ,;.")
        for part in _SEQUENTIAL_THEN_RE.split(cleaned)
        if part.strip(" ,;.")
    ]
    if len(parts) < 2:
        return cleaned
    return _LEADING_TRANSITION_ACTION_RE.sub("", parts[-1]).strip(" ,;.")


def _labels(config: Config | None = None) -> dict[str, str]:
    code = config.language_code() if config else "en"
    return _PROMPT_LABELS.get(code, _PROMPT_LABELS["en"])


_clean = clean
_shorten = shorten
IMAGE_PROMPT_VERSION = 15
_SOFT_CONTINUITY = {"smooth_continuation", "match_cut"}
_SEQUENTIAL_THEN_RE = re.compile(r"(?<=[,;.!?])\s+then\s+", re.IGNORECASE)
_LEADING_TRANSITION_ACTION_RE = re.compile(
    r"^(?:rises?|stands?|turns?|moves?|steps?|walks?|bends?|leans?)"
    r"(?:\s+\w+)?\s+and\s+",
    re.IGNORECASE,
)

# Keywords that indicate a direction is describing on-screen text/lettering — always
# strip these before they enter the prompt, since text is composed in Stage 8 and the
# no-lettering constraint forbids it in the generated image.
_TEXT_RENDER_TOKENS = (
    "lettering", "subtitle", "caption", "speech balloon", "word balloon",
    "text crawl", "floating text", "scrolling text", "on-screen text",
    "bold text", "glowing text", "burning text", "corrupted text",
)


def _strip_text_render_sentences(text: str) -> str:
    """Remove sentences that instruct the model to render on-screen text/lettering."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [
        s for s in sentences
        if not any(tok in s.lower() for tok in _TEXT_RENDER_TOKENS)
    ]
    return " ".join(kept).strip()


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

    _NULL_OUTFIT = {"none", "n/a", "-", "null", ""}
    parts: list[str] = [anchor] if anchor else []
    if scene_override and scene_override.lower() not in _NULL_OUTFIT:
        parts.append(f"{label_set['wardrobe_override']}: {_shorten(scene_override, 180)}")
    elif default_outfit and default_outfit.lower() not in _NULL_OUTFIT:
        parts.append(_shorten(default_outfit, 180))

    return "; ".join(part for part in parts if part)


def _reference_paths(project_dir: Path, character_id: str, character_count: int) -> list[str]:
    """Return subject ref paths for one character as project-relative paths.

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
    cropped = [
        str((char_ref_dir / f"{v}.png").relative_to(project_dir))
        for v in views
        if (char_ref_dir / f"{v}.png").exists()
    ]
    if cropped:
        return cropped

    sheet = char_ref_dir / "sheet.png"
    if sheet.exists():
        return [str(sheet.relative_to(project_dir))]
    return []


_PROP_CONTEXT_CUE_RE = re.compile(
    r"\b("
    r"hold|holds|holding|held|carry|carries|carrying|carried|"
    r"clutch|clutches|clutching|grip|grips|gripping|gripped|"
    r"cradle|cradles|cradling|gather|gathers|gathering|gathered|"
    r"collect|collects|collecting|collected|reach|reaches|reaching|"
    r"touch|touches|touching|touched|set|sets|setting|lay|lays|laying|"
    r"lower|lowers|lowering|hang|hangs|hanging|wear|wears|wearing|"
    r"use|uses|using|used|armful|crook|chest|hand|hands|feet"
    r")\b",
    re.IGNORECASE,
)


def _story_prop_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 3 and token not in {"with", "from", "that", "this", "they", "their"}
    }


def _planned_panel_text_pieces(
    panel: PlannedPanel,
    *,
    extra_text: list[str] | None = None,
    include_key_objects: bool = False,
) -> list[str]:
    pieces: list[str] = [
        panel.background_description,
        panel.lighting,
        panel.mood,
    ]
    pieces.extend(s.text for s in panel.sfx)
    pieces.extend(panel.character_actions.values())
    if include_key_objects:
        pieces.extend(getattr(panel, "key_objects", []) or [])
    pieces.extend(getattr(panel, "visual_requirements", []) or [])
    pieces.extend(str(line.get("text", "")) for line in panel.dialogue)
    pieces.extend(extra_text or [])
    return [_clean(piece).lower() for piece in pieces if _clean(piece)]


def _planned_panel_text_blob(
    panel: PlannedPanel,
    *,
    extra_text: list[str] | None = None,
    include_key_objects: bool = False,
) -> str:
    return " ".join(
        _planned_panel_text_pieces(
            panel,
            extra_text=extra_text,
            include_key_objects=include_key_objects,
        )
    )


def _prop_matches_context(prop, blob: str, pieces: list[str]) -> bool:
    """Return True when a story prop appears as an active panel object."""
    name = (prop.name or "").lower()
    prop_id = (prop.id or "").lower()
    if (name and name in blob) or (prop_id and prop_id in blob):
        return True

    tokens = _story_prop_tokens(prop.name or "")
    if not tokens:
        return False
    return any(
        any(token in piece for token in tokens) and _PROP_CONTEXT_CUE_RE.search(piece)
        for piece in pieces
    )


def _props_present_in_panel(panel: PlannedPanel, story_bible: StoryBible, scene=None) -> list:
    """Return story props that are actively used, carried, touched, or shown."""
    scene_appearance_text: list[str] = []
    if scene is not None:
        appearances = getattr(scene, "character_appearances", {}) or {}
        scene_appearance_text = [
            appearances.get(character_id, "")
            for character_id in getattr(panel, "characters_present", []) or []
        ]

    pieces = _planned_panel_text_pieces(panel, extra_text=scene_appearance_text)
    blob = " ".join(pieces)
    matched = []
    seen: set[str] = set()
    for prop in getattr(story_bible, "props", []) or []:
        if _prop_matches_context(prop, blob, pieces):
            if prop.id and prop.id not in seen:
                matched.append(prop)
                seen.add(prop.id)
    return matched


def _filtered_key_objects(key_objects: list[str], story_bible: StoryBible, matched_props: list) -> list[str]:
    """Drop unmatched story-prop names/ids from key objects.

    Layout planning can confuse ambient materials with carried props: for
    example, wild flowers by a stream are not the carried Bundle of Flowers.
    Keep literal prop labels only when the surrounding panel context confirms
    that prop is active.
    """
    matched_ids = {(prop.id or "").lower() for prop in matched_props}
    matched_names = {(prop.name or "").lower() for prop in matched_props}
    props_by_label: dict[str, str] = {}
    for prop in getattr(story_bible, "props", []) or []:
        if prop.id:
            props_by_label[prop.id.lower()] = prop.id.lower()
        if prop.name:
            props_by_label[prop.name.lower()] = (prop.id or prop.name).lower()

    filtered: list[str] = []
    for item in key_objects:
        cleaned = _clean(item)
        label = cleaned.lower()
        prop_key = props_by_label.get(label)
        if prop_key and prop_key not in matched_ids and label not in matched_names:
            continue
        filtered.append(cleaned)
    return filtered


def _prop_reference_paths(project_dir: Path, prop_ids: list[str]) -> list[str]:
    """Return project-relative paths to prop ref images that exist on disk."""
    paths: list[str] = []
    for prop_id in prop_ids:
        ref = project_dir / "refs" / "props" / prop_id / "ref.png"
        if ref.exists():
            paths.append(str(ref.relative_to(project_dir)))
    return paths


def _clean_list(values: list[str] | None, limit: int = 10) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = _shorten(_clean(value), 180)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        cleaned.append(text)
        seen.add(key)
        if len(cleaned) >= limit:
            break
    return cleaned


def _planned_panel_state_summary(
    panel: PlannedPanel,
    character_names: dict[str, str] | None = None,
) -> str:
    names = character_names or {}
    parts: list[str] = []
    for char_id in panel.characters_present:
        action = _single_instant_direction(panel.character_actions.get(char_id, ""))
        expression = panel.character_expressions.get(char_id, "")
        position = panel.character_positions.get(char_id, "")
        state_bits = [bit for bit in (action, expression, position) if bit]
        if state_bits:
            label = names.get(char_id, char_id)
            parts.append(f"{label}: {', '.join(state_bits)}")
    return "; ".join(parts) if parts else "scene continues"


def build_planned_panel_continuity_note(
    current_panel: PlannedPanel,
    prev_panel: PlannedPanel | None,
    story_bible: StoryBible | None = None,
) -> str | None:
    if not prev_panel:
        return None

    transition_type = (prev_panel.transition_out or "").strip().lower()
    if transition_type not in _SOFT_CONTINUITY:
        return None

    character_names = (
        {c.id: c.name for c in story_bible.characters} if story_bible else {}
    )
    prev_state_str = _shorten(_planned_panel_state_summary(prev_panel, character_names), 120)
    curr_state_str = _shorten(_planned_panel_state_summary(current_panel, character_names), 120)

    if prev_state_str == "scene continues" and curr_state_str == "scene continues":
        return None

    parts: list[str] = [f"CONTINUING FROM: {prev_state_str}."]
    parts.append(f"TRANSITION TYPE: {transition_type}.")
    parts.append(f"Now: {curr_state_str}.")
    return " ".join(parts)


def build_planned_panel_prompt_spec(
    config: Config,
    project_dir: Path,
    panel: PlannedPanel,
    story_bible: StoryBible,
    prev_panel: PlannedPanel | None = None,
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
                action=_single_instant_direction(
                    panel.character_actions.get(character_id, "")
                ),
                expression=_clean(panel.character_expressions.get(character_id, "")),
                position=_clean(panel.character_positions.get(character_id, "")),
            )
        )
        ref_paths.extend(_reference_paths(project_dir, character_id, character_count))

    location = None
    if scene:
        location = next((loc for loc in story_bible.locations if loc.id == scene.location_id), None)

    shot_key = panel.shot_type.lower().replace(" ", "-")
    composition_map = _SHOT_COMPOSITION_EMPTY if character_count == 0 else _SHOT_COMPOSITION
    composition = composition_map.get(
        shot_key,
        f"{_clean(panel.shot_type)} panel, {_clean(panel.camera_angle)} camera",
    )
    camera_angle = _single_instant_direction(panel.camera_angle)
    if camera_angle and camera_angle.lower() not in composition.lower():
        composition = f"{composition}, {camera_angle} camera"
    if panel.shape_intent in {"wide", "panorama"} and "wide" not in composition.lower():
        composition = f"{composition}, wide horizontal framing"
    if panel.shape_intent == "tall" and "vertical" not in composition.lower():
        composition = f"{composition}, tall vertical framing"
    if panel.generation_mode == "master":
        composition = f"{composition}, extra environmental margin for flexible crop"
    if panel.has_narration_caption:
        zone = panel.preferred_caption_zone or "top"
        if zone != "none":
            composition = (
                f"{composition}, leave quiet negative space near the {zone.replace('_', ' ')} "
                "for a narration caption added later"
            )
    camera_note = _strip_text_render_sentences(
        _single_instant_direction(getattr(panel, "camera_note", ""))
    )
    if camera_note and character_count == 0:
        # Remove character name tokens so the framing direction survives but the
        # name reference doesn't contradict the zero-character constraint.
        # "Low angle showing Carl's bare legs" → "Low angle showing bare legs"
        for char in story_bible.characters:
            name = re.escape(char.name)
            camera_note = re.sub(rf"\b{name}'s\s+", "", camera_note, flags=re.IGNORECASE)
            camera_note = re.sub(rf"\b{name}\b,?\s*", "", camera_note, flags=re.IGNORECASE)
        camera_note = re.sub(r"  +", " ", camera_note).strip(" ,.")
    if camera_note:
        composition = f"{composition}. {camera_note}"

    setting_parts = []
    if location and location.visual_anchor:
        setting_parts.append(_shorten(location.visual_anchor, 180).rstrip(" .,;"))
    if panel.background_description:
        setting_parts.append(_shorten(panel.background_description, 160).rstrip(" .,;"))

    width, height = dimensions_for_panel(panel)
    setting = "; ".join(setting_parts)
    lighting = _strip_text_render_sentences(_clean(panel.lighting))
    mood = _clean(panel.mood)
    visual_requirements = _clean_list(getattr(panel, "visual_requirements", []) or [], limit=12)
    matched_props = _props_present_in_panel(panel, story_bible, scene=scene)
    key_objects = _clean_list(
        _filtered_key_objects(
            getattr(panel, "key_objects", []) or [],
            story_bible,
            matched_props,
        )
    )
    props = [
        f"{prop.name}: {_shorten(prop.visual_anchor, 120)}"
        for prop in matched_props
    ]
    ref_paths.extend(_prop_reference_paths(project_dir, [p.id for p in matched_props if p.id]))
    character_label = labels["character"] if character_count == 1 else labels["characters"]
    constraints = (
        f"exactly {character_count} {character_label}; "
        f"{labels['one_body']}; {labels['single_instant']}; {labels['no_lettering']}"
    )
    if panel.has_narration_caption:
        constraints = (
            f"{constraints}; narration caption will be lettered in post-production only; "
            "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
        )
    if panel.crop_policy:
        constraints = f"{constraints}; crop policy: {panel.crop_policy}"

    full_prompt = _render_panel_prompt_body_parts(
        labels=labels,
        subjects=subjects,
        composition=composition,
        setting=setting,
        lighting=lighting,
        mood=mood,
        key_objects=key_objects,
        visual_requirements=visual_requirements,
        props=props,
        constraints=constraints,
    )

    return ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
        planned_panel_id=panel.panel_id,
        scene_id=panel.scene_id,
        panel_number=panel.panel_number,
        generation_mode=panel.generation_mode,
        shape_intent=panel.shape_intent,
        crop_policy=panel.crop_policy,
        transition_in=panel.transition_in,
        transition_out=panel.transition_out,
        has_narration_caption=panel.has_narration_caption,
        narration_mode=panel.narration_mode,
        preferred_caption_zone=panel.preferred_caption_zone,
        full_prompt=full_prompt,
        style=config.style_template,
        composition=composition,
        setting=setting,
        lighting=lighting,
        mood=mood,
        key_objects=key_objects,
        visual_requirements=visual_requirements,
        subjects=subjects,
        props=props,
        constraints=constraints,
        reference_image_paths=ref_paths,
        width=width,
        height=height,
        steps=config.effective_image_steps(),
        continuity_note=(
            build_planned_panel_continuity_note(panel, prev_panel, story_bible)
            if getattr(config, "continuity_mode", "hybrid") in {"text_only", "hybrid"}
            else None
        ),
    )


def _render_panel_prompt_body_parts(
    *,
    labels: dict[str, str] | None = None,
    subjects: list[PromptSubject],
    composition: str | None,
    setting: str | None,
    lighting: str | None,
    mood: str | None,
    key_objects: list[str] | None = None,
    visual_requirements: list[str] | None = None,
    props: list[str] | None = None,
    constraints: str | None = None,
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

    setting_text = _clean(setting)
    if setting_text:
        sentences.append(f"{label_set['setting']}: {setting_text}")

    lighting_text = _clean(lighting)
    if lighting_text:
        sentences.append(f"{label_set['lighting']}: {lighting_text}")

    mood_text = _clean(mood)
    if mood_text:
        sentences.append(f"{label_set['mood']}: {mood_text}")

    if props:
        sentences.append(f"{label_set['key_props']}: {'; '.join(_clean(prop) for prop in props)}")

    object_text = [_clean(value) for value in (key_objects or []) if _clean(value)]
    if object_text:
        sentences.append(f"{label_set['key_objects']}: {'; '.join(object_text)}")

    requirement_text = [_clean(value) for value in (visual_requirements or []) if _clean(value)]
    if requirement_text:
        sentences.append(f"{label_set['must_show']}: {'; '.join(requirement_text)}")

    if constraints:
        sentences.append(_clean(constraints))

    body = ". ".join(sentence.rstrip(" .") for sentence in sentences if sentence).strip()
    return f"{body}." if body else ""


def render_panel_prompt_body(prompt: ImagePrompt) -> str:
    """Render the compact panel-specific prompt body, excluding global style."""
    constraints = getattr(prompt, "constraints", None)
    if getattr(prompt, "has_narration_caption", False):
        note = (
            "narration caption will be lettered in post-production only; "
            "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
        )
        constraints = f"{constraints}; {note}" if constraints else note
    return _render_panel_prompt_body_parts(
        subjects=getattr(prompt, "subjects", []) or [],
        composition=getattr(prompt, "composition", None),
        setting=getattr(prompt, "setting", None),
        lighting=getattr(prompt, "lighting", None),
        mood=getattr(prompt, "mood", None),
        key_objects=getattr(prompt, "key_objects", []) or [],
        visual_requirements=getattr(prompt, "visual_requirements", []) or [],
        props=getattr(prompt, "props", []) or [],
        constraints=constraints,
    )


_GENERATION_RENDERING_CONSTRAINTS = (
    "Render clean, coherent surfaces with readable forms. Avoid stochastic grain, "
    "speckled dappling, repeated brush dabs, tiled patterns, JPEG artifacts, noisy "
    "micro-detail, and muddy over-texturing. If the selected style mentions "
    "brushwork, hatching, weave, or texture, interpret it as broad intentional "
    "structure rather than all-over noise."
)

_GPT_IMAGE_2_RENDERING_DISCIPLINE = (
    "GPT-image-2 material discipline: simplify repeated physical materials into "
    "large readable shapes with a few deliberate accents. If the panel mentions "
    "dirt, soil, leaf mold, fallen leaves, debris, bark, cloth weave, denim, "
    "corrosion, bone, cracks, rot, gravel, grass, or ferns, do not cover surfaces "
    "with many similar flecks, holes, chips, threads, dabs, leaf shapes, or tile-like "
    "marks. Keep quiet planes on bone, fabric, metal, skin, water, shadow, and ground; "
    "show only the story-critical cracks, tears, stains, and corrosion accents."
)

_REFERENCE_CONSTRAINTS = (
    "Use reference images only for identity, continuity, palette, and broad style. "
    "Do not copy sample-image artifacts, borders, layout grids, repeated texture "
    "fields, background patterns, or incidental noise."
)


def _render_subject_lines(prompt: ImagePrompt) -> list[str]:
    subjects = getattr(prompt, "subjects", []) or []
    lines: list[str] = []
    for subject in subjects:
        details = [
            subject.name,
            subject.identity,
            subject.action,
            f"expression: {subject.expression}" if subject.expression else "",
            f"position: {subject.position}" if subject.position else "",
        ]
        line = ", ".join(_clean(part) for part in details if _clean(part))
        if line:
            lines.append(f"- {line}")
    return lines


def _append_section(sections: list[str], title: str, content: str | list[str] | None) -> None:
    if isinstance(content, list):
        cleaned = [line for line in content if _clean(line)]
        if cleaned:
            sections.append(f"{title}:\n" + "\n".join(cleaned))
        return
    text = _clean(content or "")
    if text:
        sections.append(f"{title}:\n{text}")


def render_generation_prompt(
    prompt: ImagePrompt,
    style_template: str,
    image_model: str | None = None,
) -> str:
    style = _clean(style_template or getattr(prompt, "style", None))
    body = _clean(getattr(prompt, "full_prompt", "")) or render_panel_prompt_body(prompt)
    has_structured_fields = any([
        getattr(prompt, "subjects", None),
        getattr(prompt, "composition", None),
        getattr(prompt, "setting", None),
        getattr(prompt, "lighting", None),
        getattr(prompt, "mood", None),
        getattr(prompt, "key_objects", None),
        getattr(prompt, "visual_requirements", None),
        getattr(prompt, "props", None),
        getattr(prompt, "constraints", None),
    ])
    sections: list[str] = ["Create one finished comic panel image."]

    _append_section(sections, "Style", style)
    if image_model and is_gpt_image_2(image_model):
        _append_section(sections, "Rendering discipline", _GPT_IMAGE_2_RENDERING_DISCIPLINE)
    _append_section(sections, "Characters", _render_subject_lines(prompt))
    _append_section(sections, "Composition", getattr(prompt, "composition", None))
    _append_section(sections, "Setting", getattr(prompt, "setting", None))
    _append_section(sections, "Lighting", getattr(prompt, "lighting", None))
    _append_section(sections, "Mood", getattr(prompt, "mood", None))
    _append_section(
        sections,
        "Key objects",
        [f"- {_clean(obj)}" for obj in (getattr(prompt, "key_objects", []) or [])],
    )
    _append_section(
        sections,
        "Must show",
        [f"- {_clean(req)}" for req in (getattr(prompt, "visual_requirements", []) or [])],
    )
    _append_section(
        sections,
        "Key props",
        [f"- {_clean(prop)}" for prop in (getattr(prompt, "props", []) or [])],
    )

    constraints = _clean(getattr(prompt, "constraints", None))
    if getattr(prompt, "has_narration_caption", False):
        note = (
            "narration caption will be lettered in post-production only; "
            "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
        )
        constraints = f"{constraints}; {note}" if constraints else note
    constraint_lines = [
        f"- {part.strip()}"
        for part in constraints.split(";")
        if part.strip()
    ]
    constraint_lines.extend([
        f"- {_GENERATION_RENDERING_CONSTRAINTS}",
        f"- {_REFERENCE_CONSTRAINTS}",
    ])
    _append_section(sections, "Constraints", constraint_lines)

    if body and not has_structured_fields:
        _append_section(sections, "Panel brief", body)

    output = "\n\n".join(sections)

    if getattr(prompt, "continuity_note", None):
        output = f"{output}\n\nContinuity:\n{prompt.continuity_note}"

    return output


def build_style_sample_prompt(config: Config, story_bible: StoryBible) -> str:
    """Render a compact style-evaluation prompt shared by CLI and API routes."""
    first_char = story_bible.characters[0] if story_bible.characters else None
    first_loc = story_bible.locations[0] if story_bible.locations else None
    char_desc = _shorten(
        (first_char.visual_anchor if first_char else "") or (first_char.name if first_char else ""),
        200,
    ) or "a mysterious cloaked figure"
    loc_desc = _shorten(
        (first_loc.visual_anchor if first_loc else "") or (first_loc.name if first_loc else ""),
        200,
    ) or "a dramatic atmospheric setting"
    return (
        "Create one style proof image for evaluating this comic's art direction. "
        f"Subject: {char_desc}. Setting: {loc_desc}. "
        "Use a single portrait 4:5 panel, filled edge to edge with no letterboxing, "
        "pillarboxing, border margins, text, speech bubbles, or captions. "
        "The selected visual medium must be obvious at first glance: emphasize its "
        "materials, mark-making, color handling, rendering conventions, lighting "
        "language, and composition choices while keeping surfaces clean and readable.\n\n"
        "STYLE AUTHORITY - demonstrate this exactly:\n"
        f"{config.style_template}\n\n"
        "Every visible choice should support the style authority above. Do not fall "
        "back to generic cinematic, comic, or digital illustration defaults unless "
        "they are explicitly part of that style. Avoid stochastic grain, speckled "
        "dappling, repeated texture fields, pattern tiling, compression artifacts, "
        "and muddy micro-detail."
    )
