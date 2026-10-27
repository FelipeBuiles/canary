"""Stage 1: Novel → Story Bible JSON.

Extracts bounded source sections through the configured text model, retaining
completed responses and reconciling book-wide narrative arcs.
"""

import json
import re
from collections.abc import Awaitable, Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.book_map import ensure_book_map, estimate_book_map, promote_recurring_cast
from novel_to_comic.cast_roster import promote_multi_page_cast
from novel_to_comic.clients.structured_call import (
    StructuredCallError,
    generate_validated_json,
)
from novel_to_comic.clients.text import generate_json
from novel_to_comic.config import Config
from novel_to_comic.extraction_delta import compute_delta
from novel_to_comic.extraction_schema import ExtractionParticipation as _ExtractionParticipation, extraction_schema
from novel_to_comic.generation_checkpoints import checkpointed_generator
from novel_to_comic.extraction_review import ExtractionReview, SOURCE_REVIEW_INSTRUCTIONS, apply_source_review
from novel_to_comic.extraction_sections import (
    RegistryAnchorConflict, apply_exclusions, estimate_sections, extract_sections, hydrate_section, publish_opening,
    resolve_correction_references,
    validate_references,
)
from novel_to_comic.input_limits import read_source
from novel_to_comic.models.story_bible import MissingVisualAnchor, StoryBible, blank_visual_anchors
from novel_to_comic.source_extraction import (
    align_scene_anchors,
    align_scene_openings,
    produce_source_document,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.series import next_unit_ordinal, write_extraction_delta
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.text_utils import clean, has_offscreen_marker
from novel_to_comic.workspace import FIRST_PART_ID, part_ordinal, workspace_part_id
from novel_to_comic.usage import ApiResult, estimate_text_cost, estimate_token_count

console = Console()

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extraction.txt"
EXTRACT_MAX_OUTPUT_TOKENS = 65536
ESTIMATED_STORY_BIBLE_MIN_OUTPUT_TOKENS = 12000
ESTIMATED_STORY_BIBLE_MAX_OUTPUT_TOKENS = 24000

WHOLE_SOURCE_INSTRUCTIONS = """
Extract the entire supplied source from beginning to end. Infer title and author
only from the source; use Unknown when unstated. Group the narrative scenes into
ordered sequences: consecutive runs that pursue one goal, conflict or situation
and end on a turn, as many as the source supports. Each narrative scene ID occurs
exactly once, in source order; every sequence has at least one scene and a turn
(what has changed when it ends). Use char_, loc_, prop_ and
scene_ prefixes for new entities and scenes. Code supplies total_scenes.
Use audit_ as review_id_prefix for source_review additions.
""" + SOURCE_REVIEW_INSTRUCTIONS


class _ParticipationQuoteMismatch(ValueError):
    """A participation quote differs from the source beyond whitespace."""

    def __init__(self, mismatches: list[tuple[tuple[str, str], str, str | None]]) -> None:
        self.mismatches = tuple(mismatches)
        self.pair, self.source_quote, _ = self.mismatches[0]
        if len(self.mismatches) == 1:
            message = (
                "Participation quote must occur verbatim in the source "
                f"(ignoring whitespace): {self.pair}"
            )
        else:
            pairs = ", ".join(str(pair) for pair, _, _ in self.mismatches)
            message = (
                "Participation quotes must occur verbatim in the source "
                f"(ignoring whitespace): {pairs}"
            )
        super().__init__(message)


class _UnresolvedSceneOpenings(ValueError):
    """Scene openings that do not resolve, in order, within the extracted source."""

    def __init__(self, openings: list[tuple[str, str, str | None]]) -> None:
        self.openings = tuple(openings)
        super().__init__(
            "Scene source_start_quote values must be copied verbatim, in order, from the "
            "source text being extracted. Unresolved scene IDs: "
            + ", ".join(scene_id for scene_id, _, _ in self.openings)
        )


class _UnclassifiedCharacters(ValueError):
    """Candidate definitions with neither a scene roster nor participation evidence."""

    def __init__(self, characters: list[dict]) -> None:
        self.characters = tuple(
            (character["id"], character.get("name"), character.get("first_appearance_scene"))
            for character in characters
        )
        super().__init__(
            "Every candidate character requires participation evidence. "
            "Candidates absent from every scene roster and participation entry: "
            + ", ".join(f"{cid} ({name!r})" for cid, name, _ in self.characters)
        )


def _participation_quote_correction(error: Exception) -> str:
    """Return targeted repair guidance without exposing source text in stage errors."""
    if isinstance(error, _UnclassifiedCharacters):
        candidates = "\n".join(
            f"- character_id={cid!r}, name={name!r}, first_appearance_scene={scene!r}"
            for cid, name, scene in error.characters
        )
        return (
            "\nThe candidates below have definitions but occur in no scene roster or "
            "character_participation entry. Classify each against the supplied SOURCE SECTION "
            "(or NOVEL TEXT). For a physically staged individual, supply its local scene_id, "
            "direct_action or staged_recollection classification, and a nonempty verbatim "
            "source_quote. For a mention or background group, remove its Character entry "
            "and relationship references, keeping relevant facts in scene summaries; you may "
            "also supply background_only evidence for a mentioned individual. Never invent "
            "an action, scene, physical identity, or roster membership to justify eligibility. "
            "Keep the other entries and return the entire corrected Story Bible JSON object, "
            "including character_participation.\n"
            f"UNCLASSIFIED CHARACTERS:\n{candidates}\n"
        )
    if isinstance(error, _UnresolvedSceneOpenings):
        invalid_openings = "\n".join(
            f"- scene_id={scene_id!r}, source_start_quote={quote!r}"
            + (f", exact_source_replacement={candidate!r}" if candidate else "")
            for scene_id, quote, candidate in error.openings
        )
        return (
            "\nThe scene source_start_quote values below do not occur in the source text you were asked "
            "to extract (the SOURCE SECTION when one is supplied; never the registry or earlier text). "
            "Every scene must describe events from that source text, in order, and its source_start_quote "
            "must copy the complete first sentence of the scene character-for-character. Use "
            "exact_source_replacement verbatim when it is supplied. If a scene describes events that are "
            "not in the source text, remove it and extract the source text's actual events instead, "
            "updating character_participation to match. Return the entire corrected Story Bible JSON object.\n"
            f"UNRESOLVED SCENE OPENINGS:\n{invalid_openings}\n"
        )
    if not isinstance(error, _ParticipationQuoteMismatch):
        return ""
    invalid_evidence = "\n".join(
        f"- character_id={pair[0]!r}, scene_id={pair[1]!r}, source_quote={source_quote!r}"
        + (f", exact_source_replacement={candidate!r}" if candidate else "")
        for pair, source_quote, candidate in error.mismatches
    )
    return (
        "\nThe participation source_quote below is not an exact source substring. "
        "In the complete corrected Story Bible JSON, replace that field with a nonempty passage copied character-for-character "
        "from NOVEL TEXT (including punctuation and Unicode characters; whitespace may vary). Use a short, sufficient 2-8 word "
        "source fragment so it can be copied exactly. Use exact_source_replacement verbatim when it is supplied. "
        "Do not reconstruct, normalize, or paraphrase it. Keep every other entry from YOUR PREVIOUS JSON. "
        "Return the entire corrected Story Bible JSON object, including title, author, characters, locations, scenes, "
        "sequences, props, and character_participation; never return a character_participation entry or field by itself.\n"
        f"INVALID PARTICIPATION EVIDENCE:\n{invalid_evidence}\n"
    )


def _nearest_source_quote(novel_text: str, source_quote: str) -> str | None:
    """Find one high-confidence exact source sentence to show in repair feedback."""
    quote = clean(source_quote).casefold()
    if len(quote) < 12:
        return None
    candidates = [
        clean(sentence)
        for sentence in re.split(r"(?<=[.!?…])(?:[\"'”’»)]*)\s+|\n+", novel_text)
        if clean(sentence)
    ]
    scored = sorted(
        (
            SequenceMatcher(None, quote, candidate.casefold(), autojunk=False).ratio(),
            candidate,
        )
        for candidate in candidates
        if len(candidate) >= max(12, len(quote) // 2)
    )
    if not scored:
        return None
    score, candidate = scored[-1]
    runner_up = scored[-2][0] if len(scored) > 1 else 0.0
    if score < 0.88 or score - runner_up < 0.02:
        return None
    return candidate


class _SceneOpening(BaseModel):
    id: str
    source_start_quote: str
    source_start_offset: int | None = Field(default=None, ge=0)


def _unresolved_openings(
    openings: dict[str, str], novel_text: str,
) -> _UnresolvedSceneOpenings:
    return _UnresolvedSceneOpenings([
        (scene_id, quote, _nearest_source_quote(novel_text, quote))
        for scene_id, quote in openings.items()
    ])


def _resolved_scene_anchor_quotes(
    result: dict, novel_text: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve exact, scene-scoped source text for private evidence recovery.

    Returns resolved and unresolved openings. An unresolved opening is the
    actionable fault behind ungrounded evidence for that scene.
    """
    openings = []
    for scene in result.get("scenes", []):
        try:
            openings.append(_SceneOpening.model_validate(scene))
        except ValidationError:
            # Invalid scene fields are reported by final artifact validation;
            # they must not hide recoverable evidence in unrelated scenes.
            continue
    unresolved = set(align_scene_openings(openings, novel_text))
    quotes = {scene.id: scene.source_start_quote for scene in openings}
    return (
        {scene_id: quote for scene_id, quote in quotes.items() if scene_id not in unresolved},
        {scene_id: quote for scene_id, quote in quotes.items() if scene_id in unresolved},
    )



def estimate_story_bible_output_chars(novel_text: str | bytes | int) -> int:
    """Estimate Stage 1 JSON size without reserving the full max-token budget."""
    input_tokens = estimate_token_count(novel_text)
    output_tokens = max(
        ESTIMATED_STORY_BIBLE_MIN_OUTPUT_TOKENS,
        min(ESTIMATED_STORY_BIBLE_MAX_OUTPUT_TOKENS, input_tokens // 8),
    )
    return output_tokens * 4


def _read_novel(novel_path: Path) -> str:
    """Read a source using the same budgets enforced during upload."""
    return read_source(novel_path)


def _normalize_sequences(sequences: list[dict]) -> list[dict]:
    """Normalize sequence dicts to the StorySequence schema.

    Models sometimes rename fields ("name" for title, "scene_ids" for scenes)
    or return one scene ID as a string. Reading order is the authority, so
    numbering is assigned here.
    """
    normalized = []
    for number, sequence in enumerate(sequences, start=1):
        fixed = dict(sequence)
        if not fixed.get("title"):
            for alt in ("name", "description", "summary", "label"):
                if fixed.get(alt):
                    fixed["title"] = fixed.pop(alt)
                    break
            else:
                fixed["title"] = f"Sequence {number}"
        if not fixed.get("scenes"):
            for alt in ("scene_ids", "scene_list", "scene_id_list"):
                if fixed.get(alt):
                    fixed["scenes"] = fixed.pop(alt)
                    break
        if isinstance(fixed.get("scenes"), str):
            fixed["scenes"] = [fixed["scenes"]]
        fixed["number"] = number
        normalized.append(fixed)
    return normalized


def _check_whole_source_sequences(bible: StoryBible) -> None:
    """A whole-source extraction's sequences partition its narrative scenes."""
    from novel_to_comic.extraction_sections import check_sequences

    validate_references(bible)
    excluded = {scene.id for scene in bible.scenes if scene.scene_type == "non_narrative"}
    for sequence in bible.sequences:
        sequence.scenes = [sid for sid in sequence.scenes if sid not in excluded]
    bible.sequences = [sequence.model_copy(update={"number": number}) for number, sequence
                       in enumerate((s for s in bible.sequences if s.scenes), 1)]
    check_sequences(bible.sequences, [scene.id for scene in bible.scenes if scene.id not in excluded])


def _looks_adult(age_range: str, visual_anchor: str) -> bool:
    age = age_range.lower()
    if any(word in age for word in ("child", "girl", "boy", "teen", "adolescent")):
        return False
    ages = re.findall(r"\d+", age)
    if ages:
        return all(int(value) >= 18 for value in ages)
    text = f"{age} {visual_anchor}".lower()
    if any(word in text for word in ("adult", "mature", "middle-aged", "middle aged", "elderly")):
        return True
    # Height, weight, pet counts and clothing numbers are not ages.
    return False


def _normalize_character_anchor_tags(characters: list[dict]) -> list[dict]:
    """Fix common Danbooru age/gender tag slips before validation."""
    for character in characters:
        anchor = character.get("visual_anchor")
        if not isinstance(anchor, str):
            continue

        gender = str(character.get("gender", "")).lower()
        tags = [tag.strip() for tag in anchor.split(",")]
        age = str(character.get("age_range", "")).lower()
        ages = re.findall(r"\d+", age)
        young = bool(re.search(r"\b(?:child|girl|boy|teen(?:s|age|ager)?|adolescent)\b", age)) or (
            bool(ages) and all(int(value) < 18 for value in ages))
        if young:
            # Correct a contradictory provisional adult label from the model's
            # explicit age, without deriving age from height/weight/counts.
            replacements = {"1woman": "1girl", "woman": "girl", "adult female": "girl",
                            "1man": "1boy", "man": "boy", "adult male": "boy", "adult": "child"}
            tags = [replacements.get(tag.lower(), tag) for tag in tags]
            character["visual_anchor"] = ", ".join(tags)
        if not tags or tags[0].lower() not in {"1man", "1woman", "1boy", "1girl", "1other"}:
            continue

        is_androgynous = any(word in gender for word in ("androgyn", "non-binary", "nonbinary"))
        if is_androgynous:
            # Keep explicit ambiguity: avoid forcing binary count/gender tags for
            # characters extracted as androgynous/non-binary.
            if tags[0].lower() in {"1man", "1woman", "1boy", "1girl"}:
                tags[0] = "1other"
            tags = [
                tag for tag in tags
                if tag.lower() not in {"adult male", "adult female", "child male", "child female"}
            ]
            character["visual_anchor"] = ", ".join(tag for tag in tags if tag)
            continue

        if not _looks_adult(str(character.get("age_range", "")), anchor):
            continue

        is_female = any(word in gender for word in ("female", "woman", "girl"))
        is_male = not is_female and any(word in gender for word in ("male", "man", "boy"))

        if is_male and tags[0].lower() in {"1boy", "1girl"}:
            tags[0] = "1man"
            tags = [tag for tag in tags if tag.lower() != "adult"]
            if not any(tag.lower() == "adult male" for tag in tags):
                tags.insert(1, "adult male")
        elif is_female and tags[0].lower() in {"1boy", "1girl"}:
            tags[0] = "1woman"
            tags = [tag for tag in tags if tag.lower() != "adult"]
            if not any(tag.lower() == "adult female" for tag in tags):
                tags.insert(1, "adult female")

        character["visual_anchor"] = ", ".join(tag for tag in tags if tag)
    return characters


def _is_offscreen_character(character: dict) -> bool:
    """Return True for voice-only entities that should not become visual subjects."""
    features = character.get("distinguishing_features", [])
    if isinstance(features, list):
        features_text = " ".join(str(feature) for feature in features)
    else:
        features_text = str(features)
    text = " ".join(
        str(character.get(field, ""))
        for field in ("name", "visual_anchor", "default_outfit", "age_range", "gender")
    )
    return has_offscreen_marker(f"{text} {features_text}")


def _remove_offscreen_characters(result: dict, excluded_ids: set[str] | None = None, *,
                                preserved_ids: frozenset[str] = frozenset()) -> dict:
    """Drop excluded visual subjects and clean their roster/relationship references."""
    characters = result.get("characters")
    if not isinstance(characters, list):
        return result

    removed_ids = (excluded_ids or set()) | {
        character.get("id")
        for character in characters
        if isinstance(character, dict) and _is_offscreen_character(character)
    }
    removed_ids.discard(None)
    removed_ids -= preserved_ids
    if not removed_ids:
        return result

    result["characters"] = [
        character
        for character in characters
        if not (isinstance(character, dict) and character.get("id") in removed_ids)
    ]

    for character in result["characters"]:
        relationships = character.get("relationships")
        if isinstance(relationships, list):
            character["relationships"] = [
                rel
                for rel in relationships
                if not (isinstance(rel, dict) and rel.get("character_id") in removed_ids)
            ]

    for scene in result.get("scenes", []):
        if isinstance(scene, dict) and isinstance(scene.get("character_ids"), list):
            scene["character_ids"] = [
                character_id
                for character_id in scene["character_ids"]
                if character_id not in removed_ids
            ]

    return result


def _normalize_result(result: dict, *, known_character_ids: frozenset[str] = frozenset()) -> dict:
    """Apply light normalization to the raw LLM output before Pydantic validation."""
    if "sequences" in result and isinstance(result["sequences"], list):
        result["sequences"] = _normalize_sequences(result["sequences"])
    result = _remove_offscreen_characters(result, preserved_ids=known_character_ids)
    if "characters" in result and isinstance(result["characters"], list):
        _normalize_character_anchor_tags([character for character in result["characters"]
                                          if character.get("id") not in known_character_ids])
    return result


_NON_NARRATIVE_SCENE_TYPES = frozenset({
    "non_narrative", "paratext", "front_matter", "back_matter",
    "promotional", "promotional_material", "promotional_front_matter", "promotional_back_matter",
    "acknowledgments", "acknowledgements", "credits", "copyright", "dedication", "table_of_contents",
})


def _normalize_non_narrative_spans(result: dict) -> None:
    """Keep explicit non-story spans without inventing physical entities.

    The model's classification is the authority. Empty rosters and transient
    objects confirm that no embodied event is being discarded. Real unknown
    location references in narrative scenes remain visible to validation.
    """
    scene_locations = set()
    cleared_locations = set()
    for scene in result.get("scenes", []):
        if not isinstance(scene, dict) or not isinstance(scene.get("scene_type"), str):
            continue
        kind = re.sub(r"[\s-]+", "_", scene["scene_type"].casefold().strip())
        if (kind in _NON_NARRATIVE_SCENE_TYPES and not scene.get("character_ids")
                and not scene.get("transient_objects")):
            cleared_locations.add(scene.get("location_id"))
            scene["location_id"] = None
            scene["scene_type"] = "non_narrative"
        else:
            scene_locations.add(scene.get("location_id"))
    # A failed correction may have supplied an empty placeholder definition.
    # Remove it only when its sole references were explicitly non-narrative;
    # never remove an established anchor, state, or narrative setting.
    locations = result.get("locations", [])
    if isinstance(locations, list):
        result["locations"] = [location for location in locations if not (
            isinstance(location, dict) and location.get("id") in cleared_locations - scene_locations
            and isinstance(location.get("visual_anchor"), str) and not location["visual_anchor"].strip()
            and not location.get("appearance_states") and not location.get("appearance_timeline")
        )]


def _parse_extraction(raw: object, novel_text: str, *, registry: StoryBible | None = None,
                      whole_source: bool = False) -> StoryBible:
    result = raw[0] if isinstance(raw, list) else raw
    participation = _ExtractionParticipation.model_validate(result).character_participation
    # Work on a separate payload so schema-correction feedback retains the evidence.
    result = json.loads(json.dumps(result))
    review = ExtractionReview.model_validate(result.pop("source_review", {}))
    known = frozenset(character.id for character in registry.characters) if registry else frozenset()
    _normalize_non_narrative_spans(result)
    defined_characters = {
        character.get("id") for character in result.get("characters", [])
        if isinstance(character, dict)
    }
    undefined_background_ids = {
        evidence.character_id for evidence in participation
        if evidence.character_id not in defined_characters
        and evidence.classification == "background_only"
    }
    # Background-only evidence for an undefined character carries no visual
    # decision: such a character would be excluded anyway. Retain its ID so
    # relationship references are removed along with that evidence. Staged
    # evidence for an undefined character still fails below.
    participation = [
        evidence for evidence in participation
        if evidence.character_id in defined_characters
        or evidence.classification != "background_only"
    ]
    if isinstance(result.get("scenes"), list):
        result["total_scenes"] = len(result["scenes"])
    for character in result.get("characters", []):
        for field in ("age_range", "gender", "default_outfit"):
            if field in character and character[field] is None:
                character[field] = ""  # explicitly unknown, never invent a visual fact
    characters = {character["id"] for character in result.get("characters", [])}
    scenes = {scene["id"]: scene for scene in result.get("scenes", [])}
    classified: set[tuple[str, str]] = set()
    visible: set[tuple[str, str]] = set()
    mismatches: list[tuple[tuple[str, str], str, str | None]] = []
    normalized_source = clean(novel_text)
    scene_anchor_quotes, unresolved_openings = _resolved_scene_anchor_quotes(result, novel_text)
    # A quote or roster entry that cannot be grounded in an unresolved scene is
    # a symptom; the opening is the fault. Report it so one repair fixes both.
    failed_openings: dict[str, str] = {}
    unknown_characters = {e.character_id for e in participation if e.character_id not in characters}
    unknown_characters.update(
        cid for scene in scenes.values() for cid in scene["character_ids"] if cid not in characters
    )
    unknown_scenes = {e.scene_id for e in participation if e.scene_id not in scenes}
    if unknown_characters or unknown_scenes:
        raise ValueError(
            "Participation evidence must reference existing characters and scenes. "
            f"Undefined character IDs: {sorted(unknown_characters)}; "
            f"scene IDs outside this section: {sorted(unknown_scenes)}. "
            "Use exact supplied registry IDs for known characters; define genuinely new "
            "characters in characters. Scene references must belong to this source section."
        )
    for evidence in participation:
        pair = (evidence.character_id, evidence.scene_id)
        # Several passages can support the same pair. Validate each passage;
        # any explicitly staged participation outweighs background mentions.
        source_quote = clean(evidence.source_quote)
        if not source_quote or source_quote not in normalized_source:
            # Participation evidence is private and discarded after this
            # boundary. When the model paraphrases a quote, retain the model's
            # classification but ground its evidence in this scene's resolved,
            # exact opening sentence rather than retrying a transcription task.
            if source_quote and evidence.scene_id in scene_anchor_quotes:
                evidence.source_quote = scene_anchor_quotes[evidence.scene_id]
            elif source_quote and evidence.scene_id in unresolved_openings:
                failed_openings[evidence.scene_id] = unresolved_openings[evidence.scene_id]
            else:
                mismatches.append((
                    pair,
                    evidence.source_quote,
                    _nearest_source_quote(novel_text, evidence.source_quote),
                ))
        classified.add(pair)
        if evidence.classification != "background_only":
            visible.add(pair)
    for scene in scenes.values():
        if scene["id"] in unresolved_openings and any(
            (character_id, scene["id"]) not in classified for character_id in scene["character_ids"]
        ):
            failed_openings[scene["id"]] = unresolved_openings[scene["id"]]
    if failed_openings:
        raise _unresolved_openings(
            {scene_id: quote for scene_id, quote in unresolved_openings.items()
             if scene_id in failed_openings},
            novel_text,
        )
    if mismatches:
        raise _ParticipationQuoteMismatch(mismatches)
    missing_evidence = []
    for scene in scenes.values():
        for character_id in scene["character_ids"]:
            if (character_id, scene["id"]) not in classified:
                # The roster is the model's other explicit visual-membership
                # signal. Complete its private evidence from this scene's
                # resolved source sentence instead of retrying redundant data.
                if scene["id"] not in scene_anchor_quotes:
                    missing_evidence.append(f"{character_id} / {scene['id']}")
                    continue
                classified.add((character_id, scene["id"]))
                visible.add((character_id, scene["id"]))
        scene["character_ids"] = [
            character_id for character_id in scene["character_ids"]
            if (character_id, scene["id"]) in visible
        ]
    if missing_evidence:
        raise ValueError(
            "Missing participation evidence: " + "; ".join(missing_evidence)
            + ". These scenes' source_start_quote values could not be resolved. "
            "Correct their source openings or supply nonempty verbatim participation evidence."
        )
    for character_id, scene_id in sorted(visible):
        if character_id not in scenes[scene_id]["character_ids"]:
            # Participation is the explicit per-character/scene visual
            # classification. Make it authoritative when the model omitted a
            # directly staged participant from the redundant scene roster.
            scenes[scene_id]["character_ids"].append(character_id)
    unclassified = characters - {character_id for character_id, _ in classified} - known
    if unclassified:
        raise _UnclassifiedCharacters([
            character for character in result["characters"] if character["id"] in unclassified
        ])
    excluded = characters - {character_id for character_id, _ in visible} - known
    result = _remove_offscreen_characters(result, excluded | undefined_background_ids, preserved_ids=known)
    for character in result["characters"]:
        if character["id"] not in known:
            character["first_appearance_scene"] = next(
                scene["id"] for scene in scenes.values()
                if character["id"] in scene["character_ids"]
            )
    result.pop("character_participation", None)
    result = _normalize_result(result, known_character_ids=known)
    for kind in ("characters", "locations", "props"):
        for entity in result.get(kind, []):
            for appearance in entity.get("appearance_states", []):
                if "changed_facets" not in appearance or "replaces_identity" not in appearance:
                    raise ValueError(
                        f"Appearance state {entity['id']} / {appearance['id']} must explicitly "
                        "declare changed_facets and replaces_identity; do not infer empty defaults."
                    )
            positions = set()
            for activation in entity.get("appearance_timeline", []):
                at = activation["at"]
                position = (at["scene_id"], at.get("beat"))
                if position in positions:
                    raise ValueError(
                        f"Conflicting appearance activations for {entity['id']} at {position}; "
                        "use distinct beats or scenes so every state has a visible interval."
                    )
                positions.add(position)
    _check_character_looks(result.get("characters", []))
    bible = StoryBible.model_validate(result)
    if any(scene.scene_type == "non_narrative" and (scene.character_ids or scene.transient_objects)
           for scene in bible.scenes):
        raise ValueError("Non-narrative source spans cannot contain physically staged character participation or objects")
    if blank := blank_visual_anchors(bible):
        raise ValueError(
            "Every character, location, prop, and appearance state requires a nonempty "
            "visual_anchor. Blank visual_anchor for: " + ", ".join(blank)
        )
    return apply_source_review(bible, review, novel_text, part_id=FIRST_PART_ID,
                               protected_character_ids=known, require_end_looks=whole_source)


def _require_anchored_registry(registry: StoryBible | None) -> None:
    """Refuse a later part before any spend when a known entry has no anchor.

    Each section receives known entries verbatim and must preserve their
    anchors, so a blank one would fail every extraction attempt.
    """
    if registry is not None and (blank := blank_visual_anchors(registry)):
        raise MissingVisualAnchor(blank)


def _text_only_damage_states(bible: StoryBible) -> StoryBible:
    """Blood and wounds reuse the canonical reference instead of a state sheet.

    A generated state sheet becomes the character's identity authority in every
    panel of that state, so it also fixes pose and anything touching the body.
    Surface damage reads correctly from the canonical sheet plus the state text.
    Applied once to the merged bible: sections repeat known states verbatim.
    """
    for character in bible.characters:
        for state in character.appearance_states:
            facets = set(state.changed_facets)
            if facets and facets <= {"damage"} and not state.replaces_identity:
                state.visually_significant = False
    return bible


# An individual identity must not accidentally absorb distinct staged people.
_GROUP_NAME = re.compile(
    r"^(?:the\s+)?(?:two|three|four|five|six|several|many|both|pair\s+of|group\s+of|couple\s+of)\b"
    r"|^(?:the\s+)?(?:\w+\s+)?(?:twins|officers|policemen|guards|soldiers)$",
    re.IGNORECASE,
)
# Image providers refuse these; uncanny anatomy must be expressed non-explicitly.
_EXPLICIT_ANATOMY = re.compile(r"\b(?:genital|genitals|genitalia|nipples?|penis|vagina|vulva|pubic|areolae?)\b",
                               re.IGNORECASE)


def _tag_set(anchor: str) -> frozenset[str]:
    return frozenset(tag.strip().casefold() for tag in anchor.split(",") if tag.strip())


def _check_character_looks(characters: list[dict]) -> None:
    """Reject accidental individual merges, explicit anatomy and duplicate looks."""
    errors = []
    for character in characters:
        cid, name = character.get("id"), str(character.get("name", ""))
        if character.get("identity_kind", "individual") != "group" and _GROUP_NAME.search(name.strip()):
            errors.append(
                f"{cid} '{name}' names a group. Each character is one individual: give each "
                "individually staged member its own singular entry, or keep interchangeable "
                "human members as background figures in scene summaries. Collective acting "
                "creatures use identity_kind='group' with one shared visual design."
            )
        forms = [character.get("reference_form")] + [
            state.get("reference_form") for state in character.get("appearance_states", [])]
        if "formation" in forms and character.get("identity_kind") != "group":
            errors.append(
                f"{cid} '{name}' uses reference_form 'formation' but is not identity_kind "
                "'group'. Formation is only for a group whose members share one design; use "
                "figure or form for one entity."
            )
        base = str(character.get("visual_anchor", ""))
        looks = [("base", base, None)] + [
            (state.get("id"), str(state.get("visual_anchor", "")), state.get("continuity_guard"))
            for state in character.get("appearance_states", [])
        ]
        for look_id, anchor, guard in looks:
            if _EXPLICIT_ANATOMY.search(f"{anchor} {guard or ''}"):
                errors.append(
                    f"{cid}/{look_id} tags genitals or nipples. Remove them; describe uncanny "
                    "anatomy non-explicitly and tag only what the look visibly shows."
                )
        seen = {_tag_set(base): "base"}
        for state in character.get("appearance_states", []):
            # Demeanor-only states (no changed facets) legitimately reuse an anchor.
            if state.get("canonical_equivalent") or not state.get("changed_facets"):
                continue
            tags = _tag_set(str(state.get("visual_anchor", "")))
            if tags in seen:
                errors.append(
                    f"{cid}/{state.get('id')} declares a physical change but repeats the {seen[tags]} "
                    "look. Re-activate the existing "
                    "state (or a canonical_equivalent state for the base) instead of a duplicate."
                )
            seen.setdefault(tags, state.get("id"))
    if errors:
        raise ValueError("Character look errors: " + " ".join(errors))


def _recording_generator(config: Config, project_dir: Path, ctx: StageRuntime):
    """A checkpointed text generator that records each provider event once."""

    async def recorded(*, execution_mode, **kwargs):
        result = await generate_json(config=config, **kwargs)
        for usage in (*result.additional_usage, result.usage):
            if usage is not None:
                ctx.record_api_usage(usage)
        return result

    cached = checkpointed_generator(recorded, artifacts=TargetArtifacts(project_dir), stage="extract",
                                    model=config.effective_extraction_model())

    async def generate(*, config: Config, **kwargs):
        return await cached(execution_mode="mock" if config.mock_mode else "live", **kwargs)

    return generate


async def _extract_with_retry(
    config: Config,
    system_prompt: str,
    novel_text: str,
    max_retries: int = 2,
    *,
    user_content: str | None = None,
    generate: Callable[..., Awaitable[ApiResult[Any]]] | None = None,
    validate: Callable[[StoryBible], None] | None = None,
    prepare: Callable[[Any], Any] | None = None,
    on_validation_failure: Callable[[], None] | None = None,
    max_output_tokens: int = EXTRACT_MAX_OUTPUT_TOKENS,
    json_schema: dict | None = None,
    registry: StoryBible | None = None,
) -> ApiResult[StoryBible]:
    """Call the extraction model, normalize, validate, and retry on schema errors."""
    previous_response: object = None
    attempt = 0

    def validate_response(prepared: object) -> StoryBible:
        # Sections are prepared against a registry; only a whole source is a finished part.
        bible = _parse_extraction(prepared, novel_text, registry=registry, whole_source=prepare is None)
        aligned = bible.model_copy(deep=True)
        unresolved = set(align_scene_anchors(aligned, novel_text))
        if unresolved:
            raise _unresolved_openings(
                {scene.id: scene.source_start_quote for scene in bible.scenes if scene.id in unresolved},
                novel_text,
            )
        if validate is not None:
            validate(aligned)
        else:
            validate_references(aligned)
        return aligned

    def parse(raw: object) -> StoryBible:
        nonlocal previous_response, attempt
        attempt += 1
        prepared = prepare(raw) if prepare else hydrate_section(raw, None)
        prior = previous_response
        previous_response = json.loads(json.dumps(prepared))
        try:
            return validate_response(prepared)
        except Exception:
            # Preserve accepted responses and successful cached correction chains.
            # Only reconcile a rejected final attempt, without another submission.
            if attempt != max_retries + 1:
                raise
            reconciled = resolve_correction_references(prepared, prior)
            if reconciled is prepared:
                raise
            return validate_response(reconciled)

    def correction(raw: object, error: Exception) -> str:
        result = raw[0] if isinstance(raw, list) else raw
        quote_instruction = _participation_quote_correction(error)
        # Feed the errors back so the model can fix just the broken fields
        return (
            f"Your previous response had schema validation errors. "
            f"Here is the original novel text, followed by your previous JSON output "
            f"and the specific errors. Please output corrected JSON only.\n\n"
            f"NOVEL TEXT AND CONTEXT:\n{user_content or novel_text}\n\n"
            f"YOUR PREVIOUS JSON:\n{json.dumps(result, ensure_ascii=False)}\n\n"
            f"VALIDATION ERRORS:\n{error}\n\n"
            f"{quote_instruction}\n"
            f"Output corrected JSON only, no explanation."
        )

    try:
        outcome = await generate_validated_json(
            config,
            model=config.effective_extraction_model(),
            system_prompt=system_prompt,
            user_content=user_content or novel_text,
            parse=parse,
            correction=correction,
            label="Story Bible extraction",
            feature="extract.story_bible",
            max_output_tokens=max_output_tokens,
            json_schema=json_schema if json_schema is not None else extraction_schema(),
            generate=generate,
            retries=max_retries,
            temperatures=(0.4,),
        )
    except StructuredCallError as exc:
        if on_validation_failure is not None:
            on_validation_failure()
        if isinstance(exc.last_error, RegistryAnchorConflict):
            raise ValueError(exc.last_error.diagnostic()) from exc
        raise exc.last_error from exc

    usage = outcome.usage_records[-1] if outcome.usage_records else None
    return ApiResult(
        value=outcome.value,
        usage=usage,
        additional_usage=tuple(outcome.usage_records[:-1]),
    )


def _part_source(project_dir: Path, state) -> tuple[str | None, int, str | bytes]:
    """The part being extracted, its number, and its exact source text.

    A part workspace reads its own recorded text; a single-directory project
    reads the uploaded novel as before.
    """
    part = workspace_part_id(project_dir)
    target = TargetArtifacts(project_dir)
    if part is not None and target.part_manifest_path.exists():
        return part, part_ordinal(part), target.read_part_text(part)
    novel_path = Path(state.novel_path)
    if not novel_path.is_absolute():
        novel_path = project_dir / novel_path
    console.print(f"[bold]Reading novel:[/bold] {novel_path}")
    return part, part_ordinal(part) if part else 1, _read_novel(novel_path)


async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> StoryBible:
    """Execute Stage 1: Extract one part's Story Bible additions.

    The first part creates the Story Bible. A later part starts from the
    series Story Bible, so recurring characters, places and props keep their
    identities; its scenes, sequences and new entities are appended and recorded
    as the part's extraction delta.
    """
    with ctx.execute(total=4):
        # SSE logs are rendered directly in the production UI. Keep the
        # resolved path in server diagnostics above, but never expose the
        # host machine's filesystem layout to the user.
        ctx.log("Reading source text...")
        part, part_number, novel_text = _part_source(project_dir, ctx.state)
        part_key = part or FIRST_PART_ID
        if isinstance(novel_text, bytes):
            raise ValueError(
                "Image-based (scanned) PDFs are not supported. The LiteLLM gateway does not "
                "support raw PDF bytes. Use a text-based PDF, EPUB, or plain text file, or add "
                "OCR preprocessing before running Stage 1."
            )
        else:
            console.print(f"Novel length: {len(novel_text):,} characters (~{len(novel_text) // 4:,} tokens)")
            ctx.log(f"Novel length: {len(novel_text):,} characters", level="dim")
        ctx.progress(1, 4)

        system_prompt = PROMPT_PATH.read_text()
        content_for_cost = novel_text if isinstance(novel_text, str) else ""
        registry = artifacts.read_story_bible(project_dir) if part_number > 1 else None
        _require_anchored_registry(registry)
        first_ordinal = next_unit_ordinal(project_dir) if part_number > 1 else 1
        # A later part always extracts against the series registry.
        sectioned = registry is not None or len(novel_text) > config.extraction_chunk_chars
        estimated = estimate_sections(
            config, novel_text, system_prompt, registry=registry,
        ) if sectioned else estimate_text_cost(
            config.effective_extraction_model(),
            system_prompt + WHOLE_SOURCE_INSTRUCTIONS + "\n" + content_for_cost
            + json.dumps(extraction_schema()),
            output_chars=estimate_story_bible_output_chars(content_for_cost),
        )
        estimated += estimate_book_map(config, project_dir) if part is not None else 0.0
        ctx.set_estimated_cost(estimated)
        ctx.progress(2, 4)
        # A part of a longer book first learns where it sits in it. The map
        # is shared by the series and only rebuilt when the saved parts change.
        book_map = (await ensure_book_map(config, project_dir, ctx, generate=_recording_generator(
            config, project_dir, ctx)) if part is not None else None)

        console.print(f"[bold]Calling {config.effective_extraction_model()}...[/bold]")
        ctx.log(f"Calling {config.effective_extraction_model()}...")
        extract_result = None
        if sectioned:
            story_bible = await extract_sections(
                config, project_dir, ctx, novel_text, system_prompt,
                registry=registry, part_id=part_key, part_number=part_number,
                first_ordinal=first_ordinal,
            )
        else:
            extract_result = await _extract_with_retry(
                config, system_prompt + WHOLE_SOURCE_INSTRUCTIONS, novel_text,
                validate=_check_whole_source_sequences,
            )
            story_bible = extract_result.value
        # Only this part's scenes are anchored in this part's text.
        unresolved = align_scene_openings(
            [scene for scene in story_bible.scenes if scene.part_id == part_key], novel_text,
        )
        if sectioned and unresolved:
            raise ValueError("Section source boundaries failed validation: " + ", ".join(unresolved))
        if unresolved:
            # The scene still exists in the Story Bible; only its source
            # boundary is unknown, so its units stay with the preceding scene.
            console.print(
                "[yellow]Scene anchors not found in the source:[/yellow] "
                + ", ".join(unresolved)
            )
            ctx.log(
                f"{len(unresolved)} scene anchor(s) could not be located in the "
                "source text and were merged into the preceding scene: "
                + ", ".join(unresolved),
                level="dim",
            )
        console.print(
            f"[green]Extracted:[/green] {len(story_bible.characters)} characters, "
            f"{len(story_bible.locations)} locations, {len(story_bible.scenes)} scenes"
        )
        ctx.log(
            f"Extracted: {len(story_bible.characters)} characters, "
            f"{len(story_bible.locations)} locations, "
            f"{len(story_bible.scenes)} scenes"
        )
        if not sectioned:
            ctx.stage_state.items_done = 3
            ctx.save()
            ctx.progress(3, 4)

        story_bible, suppressed = apply_exclusions(story_bible, registry)
        if suppressed:
            ctx.log("Left out previously removed: " + ", ".join(suppressed), level="dim")
        story_bible = _text_only_damage_states(story_bible)
        if book_map is not None:
            if promoted := promote_recurring_cast(story_bible, book_map, part_key):
                ctx.log("Recurring across the book, so Cast will design: " + ", ".join(promoted), level="dim")
        if registry is not None:
            story_bible.revision = registry.revision + 1
        artifacts.write_story_bible(project_dir, story_bible)
        source = produce_source_document(
            TargetArtifacts(project_dir),
            novel_text,
            story_bible,
            part_id=part_key if part else None,
            first_ordinal=first_ordinal,
        )
        if promoted := promote_multi_page_cast(story_bible, source, part_key if part else None):
            ctx.log("On several pages, so Cast will design: " + ", ".join(promoted), level="dim")
            artifacts.write_story_bible(project_dir, story_bible)
        if part is not None:
            write_extraction_delta(project_dir, compute_delta(
                registry, story_bible, part_key, suppressed_names=suppressed,
            ))
        if not sectioned and registry is None:
            # A short book is read in one call: its opening is the whole part.
            publish_opening(ctx, project_dir, story_bible, text=novel_text, whole_source=True)

        if extract_result is not None:
            for retry_usage in extract_result.additional_usage:
                ctx.record_api_usage(retry_usage)
        ctx.record_item_done(usage=extract_result.usage if extract_result else None)
        ctx.progress(ctx.stage_state.items_total, ctx.stage_state.items_total)

        console.print("[green]Extract stage complete — starting Brief next.[/green]")
        ctx.log("Extract stage complete; Brief will start automatically.")

    return story_bible


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    try:
        _part, part_number, novel_text = _part_source(project_dir, state)
    except Exception:
        part_number, novel_text = 1, ""
    if not isinstance(novel_text, str):
        novel_text = ""
    registry = artifacts.read_story_bible_safe(project_dir) if part_number > 1 else None
    _require_anchored_registry(registry)
    book_map = estimate_book_map(config, project_dir) if workspace_part_id(project_dir) else 0.0
    if registry is not None or len(novel_text) > config.extraction_chunk_chars:
        return book_map + estimate_sections(config, novel_text, PROMPT_PATH.read_text(), registry=registry)
    input_payload: str | int = PROMPT_PATH.read_text() + "\n" + novel_text
    return book_map + estimate_text_cost(
        config.effective_extraction_model(),
        input_payload,
        output_chars=estimate_story_bible_output_chars(novel_text),
    )


def _clean_paths(directory: Path) -> list[Path]:
    # A part's Story Bible additions are withdrawn through its extraction
    # delta (see series.withdraw_for_reextraction); the series Story Bible
    # itself is never deleted from a part.
    if workspace_part_id(directory) is not None:
        return clean_cascade(directory, "source")
    return [artifacts.story_bible_path(directory), *clean_cascade(directory, "source")]


STAGE = Stage(
    name="extract",
    run=run,
    outputs=lambda d: [
        artifacts.story_bible_path(d),
        d / "source" / "source.json",
    ],
    clean_paths=_clean_paths,
    estimate_cost=estimate_cost,
)
