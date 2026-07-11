"""Compact image prompt composition for panel generation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from novel_to_comic.appearance import ResolvedAppearance, active_state, panel_position
from novel_to_comic.config import Config
from novel_to_comic.image_ref_strategy import RefStrategy
from novel_to_comic.models.appearance import StoryPosition
from novel_to_comic.models.layout_plan import PlannedPanel
from novel_to_comic.models.prompt import ImagePrompt, PromptAnchor, PromptSubject
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.panel_aspect import dimensions_for_generation_shape, frame_phrase
from novel_to_comic.text_utils import clean, shorten
from novel_to_comic.ai.providers.base import RefImage


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
    if getattr(panel, "generation_width", None) and getattr(panel, "generation_height", None):
        return int(panel.generation_width or 0), int(panel.generation_height or 0)
    if getattr(panel, "generation_shape", None):
        return dimensions_for_generation_shape(panel.generation_shape)
    shape_intent = getattr(panel, "shape_intent", None)
    generation_mode = getattr(panel, "generation_mode", None)
    if shape_intent in {"wide", "panorama", "bleed"}:
        return (1344, 768) if generation_mode == "exact" else (1536, 1024)
    if shape_intent == "tall":
        return (768, 1536) if generation_mode == "exact" else (1024, 1536)
    return dimensions_for_shot(panel.shot_type)


def _apply_generation_frame_to_composition(composition: str, panel: PlannedPanel) -> str:
    shape = getattr(panel, "generation_shape", None)
    if not shape:
        return composition
    phrase = frame_phrase(shape)
    updated = re.sub(
        r"\b(?:wide\s+)?vertical panel\b",
        phrase,
        composition,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        r"\bhorizontal framing\b|\btall vertical framing\b",
        phrase,
        updated,
        flags=re.IGNORECASE,
    )
    if phrase not in updated:
        updated = f"{updated}, composed for a {phrase}"
    return updated


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
IMAGE_PROMPT_VERSION = 23  # 23: semantic ReferencePlan owns all reference selection
_SOFT_CONTINUITY = {"smooth_continuation", "match_cut"}

# Generic interior/exterior vocabulary for anchor filtering. All matching is
# WORD-BOUNDARY based (see _compile_token_re) so "bed" never matches
# "riverbed" and "street" never matches "streetwise". Location *states* are
# the structural fix for indoor/outdoor anchor contamination; this layer is
# only a generic safety net and must not accumulate story-specific tokens.

# Tokens whose presence in panel.background_description signals the panel
# depicts an INTERIOR setting.
_INTERIOR_BG_HINTS = (
    "indoor", "indoors", "interior", "inside", "bedroom", "bedside",
    "rumpled", "blanket", "room", "kitchen", "hallway", "corridor",
    "tunnel", "ceiling", "doorframe", "doorway", "staircase", "stairwell",
    "cellar", "basement", "dungeon", "wallpaper",
)

# Tokens whose presence in panel.background_description signals the panel
# depicts an EXTERIOR setting.
_EXTERIOR_BG_HINTS = (
    "outdoor", "outdoors", "outside", "exterior", "sky", "street",
    "sidewalk", "rooftop", "facade", "city block", "horizon", "rubble",
    "field", "forest", "garden", "courtyard", "alley", "road",
)

# Concrete-object tokens from a location anchor that should be DROPPED when
# the panel's background_description indicates an interior. These reference
# things visible only when the camera is outdoors at that location.
_OUTDOOR_ANCHOR_TOKENS = (
    "outdoors", "outside", "street", "sidewalk", "sky", "rooftop",
    "facade", "bicycle rack", "bike rack", "moped", "stop sign",
    "street lamp", "streetlamp", "parked car", "parked cars", "rubble",
    "debris", "ruins", "traffic", "pavement", "horizon",
)

# Concrete-object tokens from a location anchor that should be DROPPED when
# the panel's background_description indicates an exterior.
_INTERIOR_ANCHOR_TOKENS = (
    "indoors", "indoor", "interior", "bedroom", "bedside", "rumpled bed",
    "hallway", "corridor", "tunnel", "ceiling", "wallpaper", "furniture",
    "staircase", "stairwell", "marble floor", "marble wall",
    "double doors", "wooden door", "bedside lamp",
)


def _compile_token_re(tokens: tuple[str, ...]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(token) for token in tokens)
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


_INTERIOR_BG_RE = _compile_token_re(_INTERIOR_BG_HINTS)
_EXTERIOR_BG_RE = _compile_token_re(_EXTERIOR_BG_HINTS)
_OUTDOOR_ANCHOR_RE = _compile_token_re(_OUTDOOR_ANCHOR_TOKENS)
_INTERIOR_ANCHOR_RE = _compile_token_re(_INTERIOR_ANCHOR_TOKENS)
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


def _detect_bg_context(background: str) -> str:
    """Return 'interior', 'exterior', or 'ambiguous' for a panel background."""
    if not background:
        return "ambiguous"
    interior_hit = bool(_INTERIOR_BG_RE.search(background))
    exterior_hit = bool(_EXTERIOR_BG_RE.search(background))
    if interior_hit and not exterior_hit:
        return "interior"
    if exterior_hit and not interior_hit:
        return "exterior"
    return "ambiguous"


def _filter_location_anchor_for_panel(anchor: str, background: str) -> str:
    """Drop concrete-object tokens from a location anchor that contradict
    the panel's background_description.

    The location anchor carries two kinds of signal: atmospheric/style tags
    (night, winter, cold, dark, overcast — useful in every panel of the
    scene) and concrete-object tags (bike rack, moped, parked cars,
    rumpled bed — only valid when the camera is actually at that location
    state). The latter pollute flashback/transition panels with persistent
    scene-wide objects. Drop them when the background says otherwise.
    """
    if not anchor or not background:
        return anchor
    context = _detect_bg_context(background)
    if context == "ambiguous":
        return anchor
    block_re = _OUTDOOR_ANCHOR_RE if context == "interior" else _INTERIOR_ANCHOR_RE
    tags = [t.strip() for t in anchor.split(",") if t.strip()]
    kept = [t for t in tags if not block_re.search(t)]
    return ", ".join(kept)


def _appearance_lock_clause(name: str, guard: str | None) -> str:
    """A hard-constraint clause that elevates an active altered appearance state.

    Generic across entities (character, location, world): tell the model to keep
    the entity exactly as described/referenced and NOT revert to its default
    prior. The authored ``continuity_guard`` (if any) sharpens it with the
    case-specific rule, but the clause works without one.
    """
    clause = (
        f"{name} is shown in a fixed altered appearance — render {name} EXACTLY as described "
        f"and as the reference image; do not restore {name}'s default look or add features not shown"
    )
    note = (guard or "").strip().rstrip(".")
    if note:
        clause += f" ({note})"
    return clause


def _character_identity(character: Character, resolved: ResolvedAppearance) -> str:
    """Resolve exactly one self-contained appearance anchor for a subject.

    Slice 02: returns the verbatim visual_anchor — the base anchor when no
    state is active, or the active state's self-contained anchor otherwise.
    Never concatenated, never shortened, never cleaned: this is immutable
    source material. The ``default_outfit`` is no longer injected beside an
    active state, and is folded into the identity only for the base look when
    the Story Bible anchor omits it.

    Before Slice 02 this ran anchors through ``_clean``/``_shorten`` (220/180
    caps), which amputated long sentinel anchors and leaked base clothing
    beside an active state. Both are gone.
    """
    if resolved.state is not None:
        return resolved.anchor
    return character.visual_anchor


def _pose_crops_in(ref_dir: Path, project_dir: Path, character_count: int) -> list[str]:
    """Project-relative pose crops from a ref directory.

    Prefers individual pose crops (front/three_quarter/gesture) over the 2x2
    sheet composite — passing the grid directly leaks its layout into the
    model's panel compositions. Falls back to sheet.png only when crops are
    not yet available. Returns [] when the directory has no usable refs.
    """
    if character_count <= 1:
        views = ["front", "three_quarter", "gesture"]
    elif character_count == 2:
        views = ["front", "three_quarter"]
    else:
        views = ["front"]
    cropped = [
        str((ref_dir / f"{v}.png").relative_to(project_dir))
        for v in views
        if (ref_dir / f"{v}.png").exists()
    ]
    if cropped:
        return cropped
    sheet = ref_dir / "sheet.png"
    if sheet.exists():
        return [str(sheet.relative_to(project_dir))]
    return []


def _reference_paths(project_dir: Path, character_id: str, character_count: int) -> list[str]:
    """Canonical (base-look) ref paths for one character."""
    return _pose_crops_in(project_dir / "refs" / character_id, project_dir, character_count)


def _state_reference_paths(
    project_dir: Path, character_id: str, state_id: str, character_count: int
) -> list[str]:
    """Refs for a character's flagged appearance state, if generated.

    Reads refs/<char>/states/<state>/. Returns [] when the state's dedicated
    refs were not generated (e.g. cast not re-run), so the caller can fall back
    to the canonical refs while still applying the state's anchor text.
    """
    state_dir = project_dir / "refs" / character_id / "states" / state_id
    return _pose_crops_in(state_dir, project_dir, character_count)


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


# Verbs/positions that signal a prop is actively present (held, carried, worn,
# set down). Deliberately EXCLUDES body-part words ("hand/hands/feet"): a panel
# that merely mentions a body part is not a prop-context cue. Including "hands"
# here is exactly what let the "Silver Hands" prop match "washing her hands".
_PROP_CONTEXT_CUE_RE = re.compile(
    r"\b("
    r"hold|holds|holding|held|carry|carries|carrying|carried|"
    r"clutch|clutches|clutching|grip|grips|gripping|gripped|"
    r"cradle|cradles|cradling|gather|gathers|gathering|gathered|"
    r"collect|collects|collecting|collected|reach|reaches|reaching|"
    r"touch|touches|touching|touched|set|sets|setting|lay|lays|laying|"
    r"lower|lowers|lowering|hang|hangs|hanging|wear|wears|wearing|"
    r"use|uses|using|used|armful|crook|chest"
    r")\b",
    re.IGNORECASE,
)


def _story_prop_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 3 and token not in {"with", "from", "that", "this", "they", "their"}
    }


def _prop_matches_context(prop, blob: str, pieces: list[str]) -> bool:
    """Return True when a story prop appears as an active panel object.

    Exact full-name / id match anywhere, OR a distinctive name token co-located
    with an active-handling cue in the same piece. The cue requirement is what
    distinguishes a carried Bundle of Flowers ("cradles an armful … to her
    chest") from ambient wildflowers ("wild flowers crowd the water's edge").
    """
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


def _prop_has_debuted(
    prop, position: StoryPosition | None, scene_order: Sequence[str] | None
) -> bool:
    """Gate a prop by its debut scene: it never appears before
    first_appearance_scene. No debut set, or no position → always allowed."""
    debut = getattr(prop, "first_appearance_scene", None)
    if not debut or position is None or not scene_order:
        return True
    order = list(scene_order)
    try:
        return order.index(position.scene_id) >= order.index(debut)
    except ValueError:
        return True


def _props_present_in_panel(
    panel: PlannedPanel,
    story_bible: StoryBible,
    position: StoryPosition | None = None,
    scene_order: Sequence[str] | None = None,
) -> list:
    """Return story props actively shown in this panel.

    A prop matches only when it is named/handled in the panel's DESCRIPTIVE
    text (not the planner's over-eager key_objects list, which _filtered_key_objects
    prunes against this result) AND the panel is at or after the prop's debut
    scene. Body modifications are character appearance states, never props, so
    this matcher never sees them.
    """
    pieces = _planned_panel_text_pieces(panel)
    blob = " ".join(pieces)
    matched = []
    seen: set[str] = set()
    for prop in getattr(story_bible, "props", []) or []:
        if not _prop_has_debuted(prop, position, scene_order):
            continue
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
        text = _shorten(_clean(value), 300)
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
    # Hard-constraint clauses for any entity in a non-base, visually-significant
    # appearance state (characters and the location). These flow into both the
    # image prompt and the brief pass (visual_brief_source_spec reads constraints).
    appearance_locks: list[str] = []
    labels = _labels(config)

    scene = next((s for s in story_bible.scenes if s.id == panel.scene_id), None)
    scene_order = [s.id for s in story_bible.scenes]
    position = panel_position(panel, scene_order)

    for character_id in panel.characters_present:
        character = next((c for c in story_bible.characters if c.id == character_id), None)
        if not character:
            continue
        resolved = active_state(
            character.visual_anchor,
            character.appearance_states,
            character.appearance_timeline,
            position,
            scene_order,
        )
        # A non-base, visually-significant state is a fixed altered look the
        # model's prior tends to revert (stumps → hands). Lock it: brief stages
        # around it, and a hard constraint forbids reverting.
        locked = resolved.state is not None and resolved.state.visually_significant
        guard = resolved.state.continuity_guard if resolved.state is not None else None
        subjects.append(
            PromptSubject(
                character_id=character_id,
                name=character.name,
                identity=_character_identity(character, resolved),
                action=_single_instant_direction(
                    panel.character_actions.get(character_id, "")
                ),
                expression=_clean(panel.character_expressions.get(character_id, "")),
                position=_clean(panel.character_positions.get(character_id, "")),
                appearance_state_id=(resolved.state_id if resolved.state is not None else None),
                appearance_state_canonical_equivalent=(
                    resolved.state.canonical_equivalent
                    if resolved.state is not None
                    else False
                ),
                appearance_locked=locked,
                appearance_guard=(guard or None),
            )
        )
        if locked:
            appearance_locks.append(_appearance_lock_clause(character.name, guard))

    location = None
    if scene:
        location = next((loc for loc in story_bible.locations if loc.id == scene.location_id), None)

    # Resolve the active location state from the location's own timeline (same
    # resolver as characters). The resolved state id flows to the ImagePrompt so
    # the draw stage selects the matching per-state plate.
    active_state_anchor = None
    location_state_id = None
    if location:
        loc_resolved = active_state(
            location.visual_anchor,
            location.appearance_states,
            location.appearance_timeline,
            position,
            scene_order,
        )
        if loc_resolved.state is not None:
            active_state_anchor = loc_resolved.anchor
            location_state_id = loc_resolved.state_id
            if loc_resolved.state.visually_significant:
                appearance_locks.append(
                    _appearance_lock_clause(location.name, loc_resolved.state.continuity_guard)
                )

    shot_key = panel.shot_type.lower().replace(" ", "-")
    composition_map = _SHOT_COMPOSITION_EMPTY if character_count == 0 else _SHOT_COMPOSITION
    composition = composition_map.get(
        shot_key,
        f"{_clean(panel.shot_type)} panel, {_clean(panel.camera_angle)} camera",
    )
    camera_angle = _single_instant_direction(panel.camera_angle)
    if camera_angle and camera_angle.lower() not in composition.lower():
        composition = f"{composition}, {camera_angle} camera"
    composition = _apply_generation_frame_to_composition(composition, panel)
    if (
        not getattr(panel, "generation_shape", None)
        and panel.shape_intent in {"wide", "panorama"}
        and "wide" not in composition.lower()
    ):
        composition = f"{composition}, wide horizontal framing"
    if (
        not getattr(panel, "generation_shape", None)
        and panel.shape_intent == "tall"
        and "vertical" not in composition.lower()
    ):
        composition = f"{composition}, tall vertical framing"
    if panel.generation_mode == "master":
        shape = getattr(panel, "generation_shape", None)
        if shape:
            composition = f"{composition}, extra environmental margin for flexible crop within a {frame_phrase(shape)}"
        else:
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

    # ── Protected anchors (Slice 02) ─────────────────────────────────────────
    # Location and prop anchors are verbatim immutable source material. They
    # live in ``anchors`` and reach the canonical projection unchanged — never
    # in the editable ``setting`` (which is now background_description only).
    anchors: list[PromptAnchor] = []
    bg_description = _clean(panel.background_description)
    if location:
        anchor_text = active_state_anchor or location.visual_anchor
        if anchor_text:
            anchors.append(
                PromptAnchor(
                    kind="location",
                    entity_id=location.id,
                    name=location.name,
                    appearance_state_id=location_state_id,
                    text=anchor_text,
                )
            )

    matched_props = _props_present_in_panel(
        panel, story_bible, position=position, scene_order=scene_order
    )
    for prop in matched_props:
        anchors.append(
            PromptAnchor(
                kind="prop",
                entity_id=prop.id,
                name=prop.name,
                text=prop.visual_anchor,
            )
        )

    # Character anchors are carried verbatim on subjects[].identity; the
    # canonical projection (generation_prompt.py) emits them from there.

    width, height = dimensions_for_panel(panel)
    # ``setting`` is now background_description only — the location anchor moved
    # to ``anchors``. It is editable scene direction (background delta).
    setting = bg_description
    lighting = _strip_text_render_sentences(_clean(panel.lighting))
    mood = _clean(panel.mood)
    visual_requirements = _clean_list(getattr(panel, "visual_requirements", []) or [], limit=12)
    key_objects = _clean_list(
        _filtered_key_objects(
            getattr(panel, "key_objects", []) or [],
            story_bible,
            matched_props,
        )
    )
    # ``props`` display list kept for backward-compat full_prompt rendering;
    # canonical projection uses the verbatim ``anchors`` entries instead.
    props = [prop.name for prop in matched_props]

    # System constraints (count, one-body, single-instant, no-lettering, crop
    # policy, appearance locks) are generated at render time by
    # generation_prompt.py — they are NOT stored in ``constraints``. The stored
    # ``constraints`` field is now user addenda only (None on a fresh build).
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
        anchors=anchors,
        constraints=None,
    )

    return ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
        planned_panel_id=panel.panel_id,
        scene_id=panel.scene_id,
        panel_number=panel.panel_number,
        generation_mode=panel.generation_mode,
        shape_intent=panel.shape_intent,
        generation_aspect_ratio=panel.generation_aspect_ratio,
        generation_width=panel.generation_width,
        generation_height=panel.generation_height,
        generation_shape=panel.generation_shape,
        generation_aspect_source=panel.generation_aspect_source,
        crop_policy=panel.crop_policy,
        transition_in=panel.transition_in,
        transition_out=panel.transition_out,
        location_id=(location.id if location else None),
        location_state_id=location_state_id,
        anchors=anchors,
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
        constraints=None,
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
    anchors: list[PromptAnchor] | None = None,
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
            rendered_subjects.append(", ".join(part for part in details if part))
        sentences.append("; ".join(rendered_subjects))

    # Protected anchors (location, prop) emitted verbatim — no _clean, no shorten.
    if anchors:
        anchor_parts = [f"{a.name}: {a.text}" for a in anchors if a.text]
        if anchor_parts:
            sentences.append("; ".join(anchor_parts))

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
    """Render the compact panel-specific prompt body from structured fields.

    Slice 02: emits protected anchors verbatim and the stored user-addenda
    constraints. System constraints (count, one-body, single-instant,
    no-lettering, crop policy, appearance locks) are generated by
    ``generation_prompt.render_canonical_body`` and are NOT part of this
    structured-field rendering.
    """
    return _render_panel_prompt_body_parts(
        subjects=getattr(prompt, "subjects", []) or [],
        composition=getattr(prompt, "composition", None),
        setting=getattr(prompt, "setting", None),
        lighting=getattr(prompt, "lighting", None),
        mood=getattr(prompt, "mood", None),
        key_objects=getattr(prompt, "key_objects", []) or [],
        visual_requirements=getattr(prompt, "visual_requirements", []) or [],
        props=getattr(prompt, "props", []) or [],
        anchors=getattr(prompt, "anchors", []) or [],
        constraints=getattr(prompt, "constraints", None),
    )


def _sentence(text: str) -> str:
    text = _clean(text).strip(" .")
    return f"{text}." if text else ""


_DANGLING_DISTILLED_END_RE = re.compile(
    r"\b(?:a|an|and|at|for|from|in|near|of|on|or|the|to|with|without)$",
    re.IGNORECASE,
)

_CAPTION_SPACE_RE = re.compile(
    r"(?:,\s*)?leave quiet negative space near the\b[^.]*"
    r"(?:for a narration caption added later)?",
    re.IGNORECASE,
)


def _readable_prompt_text(value: str | None) -> str:
    return _clean(value).replace("_", " ")


def _strip_distilled_composition_noise(value: str | None) -> str:
    text = _readable_prompt_text(value)
    text = _CAPTION_SPACE_RE.sub("", text)
    text = _clean(text).strip(" ,.;")
    parts = [part.strip(" ,.;") for part in text.split(",")]
    if parts and _DANGLING_DISTILLED_END_RE.search(parts[-1]):
        parts = parts[:-1]
    return _clean(", ".join(part for part in parts if part)).strip(" ,.;")


def _shorten_distilled(value: str | None, limit: int) -> str:
    """Shorten prompt text without leaving half-finished instructions."""
    text = _readable_prompt_text(value)
    if len(text) <= limit:
        prefix = text
        while _DANGLING_DISTILLED_END_RE.search(prefix):
            prefix = prefix.rsplit(" ", 1)[0].rstrip(" ,.;:")
        return prefix
    prefix = text[:limit].rstrip()
    for separator in (".", ";", ","):
        idx = prefix.rfind(separator)
        if idx >= max(32, limit // 3):
            prefix = prefix[:idx]
            break
    else:
        prefix = prefix.rsplit(" ", 1)[0]
    prefix = prefix.rstrip(" ,.;:")
    while _DANGLING_DISTILLED_END_RE.search(prefix):
        prefix = prefix.rsplit(" ", 1)[0].rstrip(" ,.;:")
    return prefix


def _join_phrase(parts: list[str]) -> str:
    cleaned = [_readable_prompt_text(part).strip(" ,;.") for part in parts if _readable_prompt_text(part)]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return ", ".join(cleaned[:-1]) + f", {cleaned[-1]}"


def _distilled_subject_clause(subject: PromptSubject, *, identity_limit: int) -> str:
    action = _readable_prompt_text(subject.action)
    expression = _readable_prompt_text(subject.expression)
    position = _readable_prompt_text(subject.position)
    identity = _shorten_distilled(subject.identity, identity_limit)
    # Identity (appearance) immediately follows the name so attributes bind to
    # the right character — trailing identity after action/position weakens the
    # binding and invites attribute bleed in multi-subject panels.
    details = [subject.name, identity, action, expression, position]
    return _join_phrase(details)


def _distilled_subject_sentence(prompt: ImagePrompt) -> str:
    subjects = getattr(prompt, "subjects", []) or []
    composition = _strip_distilled_composition_noise(getattr(prompt, "composition", None))
    # 200 chars keeps the S5 camera_note (appended to composition after the
    # shot phrase) — the old 100-char cap amputated it on most panels.
    shot = _shorten_distilled(composition, 200) if composition else "single scene image"
    if subjects:
        identity_limit = 450 if len(subjects) <= 2 else 300
        clauses = [
            _distilled_subject_clause(subject, identity_limit=identity_limit)
            for subject in subjects[:3]
        ]
        subject_text = "; ".join(clause for clause in clauses if clause)
        if len(subjects) > 3:
            subject_text = f"{subject_text}; additional figures remain secondary"
        return _sentence(f"{shot} of {subject_text}")

    object_text = [_readable_prompt_text(value) for value in _clean_list(getattr(prompt, "key_objects", []) or [], limit=2)]
    if object_text:
        return _sentence(f"{shot} of {' and '.join(object_text)}")

    props = [_readable_prompt_text(value) for value in _clean_list(getattr(prompt, "props", []) or [], limit=1)]
    if props:
        return _sentence(f"{shot} of {props[0]}")

    setting = _readable_prompt_text(getattr(prompt, "setting", None))
    if setting:
        return _sentence(shot)
    return _sentence(shot)


def _distilled_setting_sentence(prompt: ImagePrompt) -> str:
    setting = _readable_prompt_text(getattr(prompt, "setting", None))
    if not setting:
        return ""
    return _sentence(_shorten_distilled(setting, 220))


def _distilled_light_mood_sentence(prompt: ImagePrompt) -> str:
    lighting = _readable_prompt_text(getattr(prompt, "lighting", None))
    mood = _readable_prompt_text(getattr(prompt, "mood", None))
    if lighting and mood:
        return _sentence(f"{_shorten_distilled(lighting, 120)}, {mood} mood")
    return _sentence(_shorten_distilled(lighting or mood, 140))


def _distilled_props_sentence(prompt: ImagePrompt) -> str:
    """Emit a compact 'with' clause naming the props in the panel.

    Props (story-bible-defined recurring objects) carry their own
    visual_anchor identity and must reach the image model. Key_objects
    are now folded into the subject/setting clauses, so this clause
    surfaces props only.
    """
    props = [
        _shorten_distilled(value, 120)
        for value in _clean_list(getattr(prompt, "props", []) or [], limit=2)
    ]
    props = [p for p in props if p]
    if not props:
        return ""
    return _sentence(f"With {'; '.join(props)}")


def _distilled_must_show_sentence(prompt: ImagePrompt) -> str:
    requirements = [
        _readable_prompt_text(req).strip(" .")
        for req in _clean_list(getattr(prompt, "visual_requirements", []) or [], limit=6)
    ]
    if not requirements:
        return ""
    return _sentence(f"Must show {' and '.join(req.strip(' .') for req in requirements)}")


_DISTILLED_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for", "from",
    "with", "without", "near", "by", "as", "is", "are", "was", "were", "be",
    "been", "being", "this", "that", "these", "those", "it", "its", "her",
    "his", "their", "them", "they", "he", "she", "we", "us", "you", "your",
    "panel", "vertical", "horizontal", "shot", "of", "camera",
    "wide", "medium", "close-up", "close", "establishing", "low", "high",
    "angle", "long", "extreme", "over-shoulder", "portrait", "full", "body",
    "visible", "frame", "scene", "mood", "lighting", "show", "must",
    "key", "objects", "visible", "background", "foreground",
})


def _distilled_significant_tokens(text: str) -> set[str]:
    if not text:
        return set()
    normalized = text.lower().replace("_", " ")
    raw = re.split(r"[^a-z0-9]+", normalized)
    return {
        tok for tok in raw
        if tok and len(tok) > 2 and tok not in _DISTILLED_STOPWORDS
    }


_DISTILLED_PHRASE_SPLIT_RE = re.compile(r",| and ", re.IGNORECASE)


def _distilled_strip_known_tokens(text: str, known: set[str]) -> str:
    """Drop phrases whose meaningful tokens are already in `known`.

    Splits on commas and "and" so the must-show clause ("Must show X and Y")
    can shed Y when Y's significant tokens were already surfaced upstream.
    A phrase survives only if it contributes at least one new significant
    token.
    """
    if not text or not known:
        return text
    parts = [p.strip() for p in _DISTILLED_PHRASE_SPLIT_RE.split(text) if p.strip()]
    if len(parts) <= 1:
        # Single-phrase clause — keep as-is rather than nuking entire sentences.
        return text
    kept: list[str] = []
    for part in parts:
        tokens = _distilled_significant_tokens(part)
        if not tokens or (tokens - known):
            kept.append(part)
    return ", ".join(kept)


def _distilled_caption_space_sentence(prompt: ImagePrompt) -> str:
    """Re-surface the narration-caption negative-space directive.

    The caption cue is stripped out of the composition phrase by
    ``_strip_distilled_composition_noise`` to keep the shot phrase compact, so
    it must be re-emitted as its own sentence — otherwise panels flagged for
    narration never ask the model for caption room and S8 letters over busy art.
    """
    if not getattr(prompt, "has_narration_caption", False):
        return ""
    zone = (getattr(prompt, "preferred_caption_zone", None) or "top").replace("_", " ")
    if zone == "none":
        return ""
    return _sentence(
        f"Keep quiet, uncluttered negative space near the {zone} for a narration caption added later"
    )


def _distilled_continuity_sentence(prompt: ImagePrompt) -> str:
    """Surface one short transition / continuity directive when available.

    The image model otherwise sees each panel in isolation. A one-line cue
    like "Match-cut from prior panel: Carl smoking on bed" anchors pose and
    framing decisions across adjacent panels.
    """
    note = _clean(getattr(prompt, "continuity_note", None))
    transition_in = _clean(getattr(prompt, "transition_in", None))
    transition_out = _clean(getattr(prompt, "transition_out", None))
    if note:
        return _sentence(_shorten_distilled(note, 200))
    if transition_in and transition_in.lower() not in {"none", "scene_change"}:
        return _sentence(f"Transition in: {transition_in.replace('_', ' ')}")
    if transition_out and transition_out.lower() not in {"none", "scene_change"}:
        return _sentence(f"Transition out: {transition_out.replace('_', ' ')}")
    return ""


def generate_distilled_prompt(prompt: ImagePrompt) -> str:
    """Compile a short, deterministic visual brief from structured prompt fields.

    Sentence order is fixed and each later sentence is filtered against the
    union of significant tokens already emitted, so a noun mentioned in the
    subject clause does not get repeated in the setting clause or in the
    must-show clause. The standalone "Key visible objects" sentence has been
    folded into the subject/setting clauses to eliminate triple-duplication.
    """
    has_structured_visual_fields = any([
        getattr(prompt, "subjects", None),
        getattr(prompt, "composition", None),
        getattr(prompt, "setting", None),
        getattr(prompt, "lighting", None),
        getattr(prompt, "mood", None),
        getattr(prompt, "key_objects", None),
        getattr(prompt, "visual_requirements", None),
        getattr(prompt, "props", None),
    ])
    if not has_structured_visual_fields:
        return _clean(getattr(prompt, "full_prompt", "")) or render_panel_prompt_body(prompt)

    sentences: list[str] = []
    seen: set[str] = set()

    subject = _distilled_subject_sentence(prompt)
    if subject:
        sentences.append(subject)
        seen |= _distilled_significant_tokens(subject)

    setting = _distilled_setting_sentence(prompt)
    if setting:
        deduped = _distilled_strip_known_tokens(setting, seen)
        # _distilled_strip_known_tokens may have removed the trailing period.
        deduped = _sentence(deduped) if deduped else ""
        if deduped:
            sentences.append(deduped)
            seen |= _distilled_significant_tokens(deduped)

    # Lighting/mood and must-show sentences are exempt from token dedup:
    # bag-of-words overlap is not semantic redundancy ("light from a window"
    # in the setting does not make "low warm light, deep shadows" redundant),
    # and these two clauses carry the highest visual-quality leverage.
    light_mood = _distilled_light_mood_sentence(prompt)
    if light_mood:
        sentences.append(light_mood)
        seen |= _distilled_significant_tokens(light_mood)

    props_clause = _distilled_props_sentence(prompt)
    if props_clause:
        sentences.append(props_clause)
        seen |= _distilled_significant_tokens(props_clause)

    must_show = _distilled_must_show_sentence(prompt)
    if must_show:
        sentences.append(must_show)
        seen |= _distilled_significant_tokens(must_show)

    caption_space = _distilled_caption_space_sentence(prompt)
    if caption_space:
        sentences.append(caption_space)

    continuity = _distilled_continuity_sentence(prompt)
    if continuity:
        sentences.append(continuity)

    text = " ".join(sentence for sentence in sentences if sentence).strip()
    return text or _clean(getattr(prompt, "full_prompt", "")) or render_panel_prompt_body(prompt)


def ensure_distilled_prompt(config: Config, prompt: ImagePrompt) -> ImagePrompt:  # noqa: ARG001
    """Return a copy of prompt with distilled_prompt populated."""
    if _clean(getattr(prompt, "distilled_prompt", None)):
        return prompt
    updated = prompt.model_copy(deep=True)
    updated.distilled_prompt = generate_distilled_prompt(updated)
    return updated


def visual_brief_source_spec(prompt: ImagePrompt) -> str:
    """Render the scene-direction spec for the LLM visual-brief pass.

    Slice 02: the LLM owns ONLY scene direction — framing, action, expression,
    position, panel-specific setting delta, lighting, mood, spatial
    relationships, caption-space composition. Protected anchors (character,
    location, prop ``visual_anchor`` text), reference instructions, and
    generated system constraints are EXCLUDED: the canonical projection
    (``generation_prompt.render_canonical_body``) emits them verbatim from the
    owned sections, so the brief cannot rewrite or drop them.
    """
    lines: list[str] = []

    framing = _strip_distilled_composition_noise(getattr(prompt, "composition", None))
    if framing:
        lines.append(f"Framing: {framing}")

    for subject in getattr(prompt, "subjects", []) or []:
        # Scene direction per subject: action, expression, position. The
        # verbatim identity anchor is NOT included — it is protected source
        # material owned by the canonical IR.
        action = _readable_prompt_text(subject.action)
        expression = _readable_prompt_text(subject.expression)
        position = _readable_prompt_text(subject.position)
        tail_bits: list[str] = []
        if action:
            tail_bits.append(f"action: {action}")
        if expression:
            tail_bits.append(f"expression: {expression}")
        if position:
            tail_bits.append(f"position: {position}")

        if getattr(subject, "appearance_locked", False):
            # A locked appearance is fixed for this panel. The brief must stage
            # actions around it, but it never sees the verbatim anchor text —
            # the canonical projection carries that. The continuity guard tells
            # the brief what the look forbids (staging, not identity).
            head = f"Character — {subject.name} [APPEARANCE LOCKED — fixed for this panel]"
            guard = (getattr(subject, "appearance_guard", None) or "").strip().rstrip(".")
            if guard:
                head += f". Continuity rule: {guard}"
            head += (
                f". Describe every action so it stays consistent with this locked look; "
                f"never write {subject.name} doing anything that requires features they do "
                f"not have"
            )
            tail = ("; " + "; ".join(tail_bits)) if tail_bits else ""
            lines.append(head + tail)
        else:
            tail = ("; " + "; ".join(tail_bits)) if tail_bits else ""
            presence = tail[2:] if tail else "present"
            lines.append(f"Character — {subject.name}: {presence}")

    setting = _readable_prompt_text(getattr(prompt, "setting", None))
    if setting:
        lines.append(f"Setting: {setting}")
    lighting = _readable_prompt_text(getattr(prompt, "lighting", None))
    if lighting:
        lines.append(f"Lighting: {lighting}")
    mood = _readable_prompt_text(getattr(prompt, "mood", None))
    if mood:
        lines.append(f"Mood: {mood}")

    key_objects = [_readable_prompt_text(value) for value in getattr(prompt, "key_objects", []) or []]
    key_objects = [o for o in key_objects if o]
    if key_objects:
        lines.append(f"Other visible objects: {'; '.join(key_objects)}")
    requirements = [
        _readable_prompt_text(value)
        for value in getattr(prompt, "visual_requirements", []) or []
    ]
    requirements = [r for r in requirements if r]
    if requirements:
        lines.append(f"Must clearly show: {'; '.join(requirements)}")

    if getattr(prompt, "has_narration_caption", False):
        zone = (getattr(prompt, "preferred_caption_zone", None) or "top").replace("_", " ")
        if zone != "none":
            lines.append(
                f"Caption space: keep quiet, uncluttered negative space near the {zone} "
                "for a narration caption added later"
            )

    continuity_note = _clean(getattr(prompt, "continuity_note", None))
    if continuity_note:
        lines.append(f"Continuity with previous panel: {continuity_note}")

    # User-authored constraint addenda are editable scene direction (e.g.
    # "non-graphic implied action"). Generated system constraints (count,
    # one-body, no-lettering, crop policy, appearance locks) are NOT emitted
    # here — the canonical projection generates them from typed fields.
    user_constraints = _clean(getattr(prompt, "constraints", None))
    if user_constraints:
        lines.append(f"User constraint notes: {user_constraints}")

    return "\n".join(lines)


# Positive surface-discipline line appended to the Style section (not the
# constraints) when the style template invokes texture-heavy media. Phrased as
# direction rather than a list of failure modes: enumerating artifact
# vocabulary ("grain", "JPEG artifacts", "speckled dappling") in every prompt
# both dilutes attention on the actual scene and seeds the very concepts we
# want to avoid.
_STYLE_SURFACE_DISCIPLINE = (
    "Render clean, coherent surfaces with readable forms; interpret brushwork, "
    "hatching, weave, or texture as broad intentional structure applied to large "
    "shapes, with quiet planes between accents."
)

_TEXTURE_STYLE_RE = re.compile(
    r"\b(brush|hatch|stipple|weave|texture|grain|impasto|gouache|watercolou?r|"
    r"woodcut|linocut|etch|crosshatch|charcoal|pastel|oil paint)\w*",
    re.IGNORECASE,
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

_LAYOUT_CONSTRAINT_LINE = (
    "One unified scene filling the entire canvas — no sub-panels, gutters, "
    "internal borders, page layouts, or split-screen compositions."
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
    refs: list[RefImage] | None = None,
    *,
    reference_instructions: tuple | None = None,
) -> str:
    """Render the final provider-bound generation prompt.

    Slice 05: per-reference instructions are owned by the compiled request
    (:func:`novel_to_comic.compiled_request.compile_generation_request`).
    When ``reference_instructions`` (compiled
    ``CompiledReferenceInstruction`` objects) are supplied, they are
    serialized here in the final plan order — this layer does NOT re-derive
    compatibility, select references, or re-cap. When they are absent (direct
    callers without a compiled request), the provider-tagged fallback block
    below renders from the ``refs`` list.
    """
    style = _clean(style_template or getattr(prompt, "style", None))
    # Prefer the LLM-composed prose brief; fall back to the deterministic
    # distilled brief for prompts generated before the brief existed.
    body = (
        _clean(getattr(prompt, "visual_brief", None))
        or _clean(getattr(prompt, "distilled_prompt", None))
        or generate_distilled_prompt(prompt)
    )
    sections: list[str] = ["Create one finished scene image using the selected style."]

    if style and _TEXTURE_STYLE_RE.search(style):
        style = f"{style}\n{_STYLE_SURFACE_DISCIPLINE}"
    _append_section(sections, "Style", style)
    strategy = RefStrategy(image_model or "")
    if strategy.include_rendering_discipline():
        _append_section(sections, "Rendering discipline", _GPT_IMAGE_2_RENDERING_DISCIPLINE)
    _append_section(sections, "Visual brief", body)

    # Continuity sits with the visual content, not below the constraint
    # boilerplate — it directly informs pose and framing.
    if getattr(prompt, "continuity_note", None):
        _append_section(sections, "Continuity", prompt.continuity_note)

    # ── Reference instructions (Slice 05) ──────────────────────────────────
    # The compiled request owns the semantic per-reference instruction text
    # (role-aware, facet-precise). This layer serializes it into the
    # provider-tagged wire format (Reve ``<img>N</img>``) without re-selecting
    # references or re-capping. No generic "ignore all backgrounds" guard is
    # emitted — each instruction names its exact preserved/ignored facets.
    use_indexed = strategy.use_indexed_ref_instructions()
    if reference_instructions and use_indexed:
        lines = []
        for instr in reference_instructions:
            idx = instr.index
            marker = f"<img>{idx}</img>"
            lines.append(f"Use {marker} as {instr.semantic_instruction}.")
        if lines:
            _append_section(sections, "Reference images", "\n".join(lines))
    elif reference_instructions and not use_indexed:
        # Non-indexed routes (Gemini/GPT Image 2): emit the semantic
        # instructions without positional tags so the provider still sees the
        # role-aware facet guidance.
        lines = [
            f"Reference: {instr.semantic_instruction}."
            for instr in reference_instructions
        ]
        if lines:
            _append_section(sections, "Reference images", "\n".join(lines))
    elif refs and use_indexed:
        # Fallback: direct caller without a compiled request. Render the
        # legacy provider-tagged instructions from the refs list.
        ref_lines = []
        for idx, ref in enumerate(refs):
            role = ref.role
            label = ref.label
            if role == "subject":
                instr_line = (
                    f"Use <img>{idx}</img> as the identity reference for {label} — match face, hair, build, and wardrobe; do not copy its pose or background."
                    if label
                    else f"Use <img>{idx}</img> as the character identity reference; do not copy its pose or background."
                )
            elif role == "style":
                instr_line = f"Use <img>{idx}</img> as the style reference for {label}." if label else f"Use <img>{idx}</img> as the style reference."
            elif role == "location_plate":
                instr_line = f"Use <img>{idx}</img> as the location reference for {label}." if label else f"Use <img>{idx}</img> as the location reference."
            elif role == "prop":
                instr_line = f"Use <img>{idx}</img> as the object reference for {label}." if label else f"Use <img>{idx}</img> as the object reference."
            elif role == "continuity":
                instr_line = f"Use <img>{idx}</img> for visual continuity."
            else:
                instr_line = f"Use <img>{idx}</img> as a reference."
            ref_lines.append(instr_line)
        if ref_lines:
            _append_section(sections, "Reference images", "\n".join(ref_lines))

    # System constraints are generated from typed fields; user addenda come from
    # the stored ``constraints`` field. The canonical constraint surface
    # combines both (see generation_prompt.generate_system_constraints).
    from novel_to_comic.generation_prompt import generate_system_constraints

    system_lines = generate_system_constraints(prompt)
    user_addenda = _clean(getattr(prompt, "constraints", None))
    # Build the constraint bullet list: system constraints first (generated,
    # non-editable), then user addenda.
    constraint_lines: list[str] = []
    for line in system_lines:
        constraint_lines.append(f"- {line.strip()}")
    if user_addenda:
        for part in user_addenda.split(";"):
            part = part.strip()
            if part:
                constraint_lines.append(f"- {part}")
    _append_section(sections, "Constraints", constraint_lines)

    return "\n\n".join(sections)


def style_sample_fallback_brief(story_bible: StoryBible) -> str:
    """Deterministic style-sample body used when the LLM brief is unavailable."""
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
        f"A three-quarter view of one figure — {char_desc} — in {loc_desc}. "
        "One frozen instant with the figure as the clear focal point and the setting "
        "giving depth behind them. Directional light models the face and figure, with "
        "bright accents and deep shadow both in frame so the style's full range shows."
    )


def build_style_sample_prompt(
    config: Config,
    story_bible: StoryBible,
    *,
    brief: str | None = None,
) -> str:
    """Render the style proof-image prompt shared by CLI and API routes.

    *brief* is the LLM-composed subject/setting prose from
    ``ensure_style_sample_brief``; when absent the deterministic
    first-character/first-location body is used instead.
    """
    style = _clean(config.style_template)
    if style and _TEXTURE_STYLE_RE.search(style):
        style = f"{style}\n{_STYLE_SURFACE_DISCIPLINE}"
    body = _clean(brief or "") or style_sample_fallback_brief(story_bible)

    sections: list[str] = [
        "Create one style proof image for evaluating the project's art direction — "
        "demonstrate the selected style at full strength."
    ]
    _append_section(sections, "Style", style)
    _append_section(sections, "Visual brief", body)
    _append_section(sections, "Constraints", [
        f"- {_LAYOUT_CONSTRAINT_LINE}",
        "- Portrait 4:5 frame, filled edge to edge.",
        "- Wordless artwork: all storytelling through imagery alone, with no lettering or borders.",
    ])
    return "\n\n".join(sections)
