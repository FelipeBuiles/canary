"""Book-level Adapt production for the full-page pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from novel_to_comic.ai.context import stream_observer
from novel_to_comic.briefing import require_approved_brief
from novel_to_comic.model_costs import get_pricing_resolver
from novel_to_comic.models.adaptation import (
    AdaptationBrief,
    AdaptationLedgerEntry,
    AdaptedBeat,
    AppearanceChange,
    BookAdaptation,
    ContinuityTransition,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.editorial import story_instruction_section
from novel_to_comic.models.validation import (
    EditorialIssue,
    InvariantFailure,
    StageValidation,
    ValidationAttempt,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.paid_shards import run_paid_shards
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.text_utils import normalize_display_text
from novel_to_comic.usage import ApiResult, estimate_text_cost


_MAX_ADAPT_ATTEMPTS = 2
_ADAPT_SHARD_MAX_UNITS = 180
_ADAPT_MAX_CONCURRENCY = 4
_ADAPT_OUTPUT_BUDGET_RATIO = 0.65
# Beats plus compact ledger exceptions are materially smaller than the source;
# the canonical per-unit ledger is expanded locally after generation.
_ADAPT_OUTPUT_TOKENS_PER_SOURCE_CHAR = 0.5
_MISSING_LEDGER_EXCEPTION = "missing_model_authored_omission_exception"
_ADAPT_CHECKPOINT_VERSION = 2


def _requirement_registry(brief: AdaptationBrief) -> dict[str, str]:
    return {
        **{
            f"essential_event_{index:03d}": requirement
            for index, requirement in enumerate(brief.essential_events, 1)
        },
        **{
            f"character_turn_{index:03d}": requirement
            for index, requirement in enumerate(brief.character_turns, 1)
        },
    }


def _as_contract_strings(value: Any) -> tuple[str, ...]:
    """Coerce one treatment field into the tuple of strings the contract wants.

    A writer asked for a list of strings routinely returns one string, a list of
    small objects, or an object keyed by name. Those carry the same content in a
    different container, so they are reshaped rather than rejected — flattening
    an object into "key: value" keeps the writer's own words.
    """

    def _one(item: Any) -> str:
        if isinstance(item, Mapping):
            return "; ".join(
                f"{key}: {inner}" for key, inner in item.items() if str(inner).strip()
            )
        return str(item).strip()

    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Mapping):
        return tuple(
            filter(
                None, (f"{key}: {_one(inner)}".strip() for key, inner in value.items())
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(filter(None, (_one(item) for item in value)))
    return (str(value),)


def normalize_treatment(content: Mapping[str, Any], /) -> dict[str, Any]:
    """Repair container slips in an inferred treatment without inventing content.

    Unknown keys are dropped because the contract forbids extras; the retry that
    follows a validation failure is what recovers content the writer put under a
    name of its own invention.
    """

    return {
        field: _as_contract_strings(content[field])
        for field in NarrativeTreatment.model_fields
        if field in content
    }


class AdaptationValidation(BaseModel):
    """Adapt-owned blocking failures and reviewable creative concerns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invariant_failures: tuple[InvariantFailure, ...] = ()
    editorial_issues: tuple[EditorialIssue, ...] = ()


class _LedgerException(BaseModel):
    """Only source-accounting decisions that cannot be derived from beats."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_unit_ids: tuple[str, ...] = Field(min_length=1)
    disposition: Literal[
        "visual_motif",
        "compressed_into",
        "intentionally_omitted",
    ]
    adapted_beat_ids: tuple[str, ...] = ()
    reason: str | None = None
    preserved_function: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_exception(self) -> "_LedgerException":
        if self.disposition in {"compressed_into", "intentionally_omitted"}:
            if not self.reason:
                raise ValueError(f"{self.disposition} requires a reason")
        if self.disposition == "intentionally_omitted" and self.adapted_beat_ids:
            raise ValueError(
                "intentionally_omitted cannot have an adapted-beat destination"
            )
        if self.disposition != "intentionally_omitted" and not self.adapted_beat_ids:
            raise ValueError(f"{self.disposition} requires an adapted beat")
        return self


class _BookDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    beats: tuple[AdaptedBeat, ...]
    # ``ledger`` remains accepted internally while tests and failed paid
    # candidates migrate. Production prompts request only compact exceptions;
    # code expands them into the canonical one-entry-per-source-unit ledger.
    ledger: tuple[AdaptationLedgerEntry, ...] = ()
    ledger_exceptions: tuple[_LedgerException, ...] = ()


class _BlueprintBeat(BaseModel):
    """A locked story decision, deliberately excluding final lettering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    summary: str = Field(min_length=1)
    narrative_function: Literal[
        "establisher",
        "initial",
        "prolongation",
        "peak",
        "release",
        "transition",
    ]
    story_functions: tuple[
        Literal[
            "causal_event",
            "reveal",
            "reaction",
            "consequence",
            "transition",
            "aftermath",
            "character_turn",
        ],
        ...,
    ] = ()
    brief_requirement_ids: tuple[str, ...] = ()
    source_unit_ids: tuple[str, ...] = Field(min_length=1)
    entity_ids: tuple[str, ...] = ()
    transitions: tuple[ContinuityTransition, ...] = ()
    appearance_changes: tuple[AppearanceChange, ...] = ()

    def to_adapted_beat(self) -> AdaptedBeat:
        return AdaptedBeat(
            **self.model_dump(mode="python"),
            lettering=(),
        )


class _BlueprintDraft(BaseModel):
    """The model-facing structural contract; canonical ledger is not exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    beats: tuple[_BlueprintBeat, ...] = Field(min_length=1)
    ledger_exceptions: tuple[_LedgerException, ...] = ()


class _BeatLettering(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    beat_id: str = Field(min_length=1)
    lettering: tuple[LetteringItem, ...] = ()


class _LetteringDraft(BaseModel):
    """Final words keyed to immutable blueprint beats."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    beats: tuple[_BeatLettering, ...]


class _AdaptCheckpoint(BaseModel):
    """Hash-keyed cache entry for one paid Adapt response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    input_sha256: str
    payload: dict[str, Any]


def _checkpoint_key(*, model: str, feature: str, prompt: str) -> str:
    encoded = json.dumps(
        {
            "version": _ADAPT_CHECKPOINT_VERSION,
            "model": model,
            "feature": feature,
            "prompt": prompt,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_checkpoint(
    artifacts: TargetArtifacts,
    *,
    name: str,
    input_sha256: str,
    model_type: type[BaseModel],
) -> BaseModel | None:
    checkpoint = artifacts.read_adapt_checkpoint(name, _AdaptCheckpoint)
    if (
        checkpoint is None
        or checkpoint.version != _ADAPT_CHECKPOINT_VERSION
        or checkpoint.input_sha256 != input_sha256
    ):
        return None
    try:
        return model_type.model_validate(checkpoint.payload)
    except ValidationError:
        return None


def _write_checkpoint(
    artifacts: TargetArtifacts,
    *,
    name: str,
    input_sha256: str,
    payload: BaseModel,
) -> None:
    artifacts.write_adapt_checkpoint(
        name,
        _AdaptCheckpoint(
            version=_ADAPT_CHECKPOINT_VERSION,
            input_sha256=input_sha256,
            payload=payload.model_dump(mode="json"),
        ),
    )


def _canonicalize_treatment_requirements(
    treatment: NarrativeTreatment,
    brief: AdaptationBrief,
) -> NarrativeTreatment:
    """Make approved requirement identity deterministic rather than model-authored."""

    return treatment.model_copy(
        update={
            "essential_events": brief.essential_events,
            "essential_event_ids": tuple(
                f"essential_event_{index:03d}"
                for index, _ in enumerate(brief.essential_events, 1)
            ),
            "character_turns": brief.character_turns,
            "character_turn_ids": tuple(
                f"character_turn_{index:03d}"
                for index, _ in enumerate(brief.character_turns, 1)
            ),
        }
    )


def _canonicalize_draft_requirements(
    draft: _BookDraft,
    brief: AdaptationBrief,
) -> _BookDraft:
    """Keep one stable requirement citation per beat; text lives in the Brief."""
    return draft.model_copy(update={"beats": tuple(
        beat.model_copy(update={"brief_requirement_ids": tuple(dict.fromkeys(beat.brief_requirement_ids))})
        for beat in draft.beats
    )})


def _canonicalize_candidate_requirements(
    candidate: BookAdaptation,
    source: SourceDocument,
    brief: AdaptationBrief,
) -> BookAdaptation:
    retained_exceptions = tuple(
        _LedgerException(
            source_unit_ids=(entry.source_unit_id,),
            disposition=entry.disposition,
            adapted_beat_ids=entry.adapted_beat_ids,
            reason=entry.reason,
            preserved_function=entry.preserved_function,
        )
        for entry in candidate.ledger
        if entry.disposition
        in {"visual_motif", "compressed_into", "intentionally_omitted"}
    )
    materialized = _materialize_draft_ledger(
        _BookDraft(
            beats=candidate.beats,
            ledger_exceptions=retained_exceptions,
        ),
        tuple(unit.id for unit in source.units),
    )
    persisted_by_source = {
        entry.source_unit_id: entry for entry in candidate.ledger
    }
    materialized = materialized.model_copy(
        update={
            "ledger": tuple(
                persisted_by_source.get(entry.source_unit_id, entry)
                for entry in materialized.ledger
            )
        }
    )
    draft = _canonicalize_draft_requirements(
        materialized,
        brief,
    )
    beats = list(draft.beats)
    # Missing requirement citations are validation failures. Word overlap is not
    # evidence that a story requirement was actually realized.
    canonical = BookAdaptation.model_validate(
        {
            **candidate.model_dump(mode="json"),
            "content_sha256": "",
            "treatment": _canonicalize_treatment_requirements(
                candidate.treatment,
                brief,
            ).model_dump(mode="json"),
            "beats": [
                beat.model_dump(mode="json")
                for beat in _canonicalize_prior_states(beats)
            ],
            "ledger": [entry.model_dump(mode="json") for entry in draft.ledger],
        }
    )
    return _materialize_protected_lettering(canonical, source, brief)


def _canonicalize_prior_states(beats: list[AdaptedBeat]) -> list[AdaptedBeat]:
    """Fill each transition's origin from the last state authored in its scope.

    A transition's ``from_state`` is not the writer's to choose: it is whatever
    the previous transition in the same scope ended on, which this code already
    tracks. Asking for it back invited paraphrase — "1925" for "March 23rd -
    April 2nd, 1925" — which reads as a continuity error while meaning the same
    thing. Deriving it makes continuity a property of the artifact instead of a
    string-equality check the writer has to win. Same for appearance changes,
    where the equivalent mismatch is a *blocking* failure and so costs a repair
    round. The first state in a scope has no predecessor and is left as authored.
    """

    continuity_states: dict[tuple[str, str], str] = {}
    appearance_states: dict[str, str] = {}
    canonical: list[AdaptedBeat] = []
    # Sequence order, matching how validate_book_adaptation walks beats — a
    # different traversal here could derive a state it then rejects.
    for beat in beats:
        transitions = []
        for transition in beat.transitions:
            key = (transition.dimension, transition.scope_id)
            previous = continuity_states.get(key)
            if previous == transition.to_state:
                # Parallel shards can independently restate the destination
                # already established by the preceding shard. Once the true
                # origin is derived this is not a transition at all; retaining
                # it would manufacture an invalid "Oslo -> Oslo" record and
                # crash before normal adaptation validation can repair the
                # surrounding beat when necessary.
                continue
            transitions.append(
                transition
                if previous is None
                else transition.model_copy(update={"from_state": previous})
            )
            continuity_states[key] = transition.to_state
        changes = []
        for change in beat.appearance_changes:
            previous_state = appearance_states.get(change.entity_id)
            changes.append(
                change
                if previous_state is None
                else change.model_copy(update={"from_state_id": previous_state})
            )
            appearance_states[change.entity_id] = change.to_state_id
        canonical.append(
            beat.model_copy(
                update={
                    "transitions": tuple(transitions),
                    "appearance_changes": tuple(changes),
                }
            )
        )
    return canonical


_REQUIREMENT_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "his",
    "in",
    "into",
    "of",
    "on",
    "the",
    "to",
    "who",
    "with",
}


def _requirement_words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"\w+", text.casefold())
        if len(word) > 2 and word not in _REQUIREMENT_STOP_WORDS
    }


def _closest_requirement_beat(
    candidates: list[AdaptedBeat],
    *,
    requirement: str,
    story_function: str,
) -> tuple[AdaptedBeat | None, int]:
    wanted = _requirement_words(requirement)
    if story_function == "character_turn":
        subject = re.split(
            r"\b(?:shifts|transforms|transitions)\s+from\b",
            requirement,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        subject_words = _requirement_words(subject)
        subject_candidates = [
            beat
            for beat in candidates
            if subject_words.intersection(
                _requirement_words(
                    " ".join(
                        (
                            beat.summary,
                            *(item.text for item in beat.lettering),
                        )
                    )
                )
            )
        ]
        if subject_candidates:
            candidates = subject_candidates
    endpoint = (
        _requirement_words(requirement.rsplit(" into ", 1)[1])
        if story_function == "character_turn" and " into " in requirement
        else set()
    )

    def score(beat: AdaptedBeat) -> tuple[int, int, int, int]:
        searchable = " ".join(
            (
                beat.summary,
                *(item.text for item in beat.lettering),
            )
        )
        searchable_words = _requirement_words(searchable)
        overlap = len(wanted.intersection(searchable_words))
        endpoint_overlap = len(endpoint.intersection(searchable_words))
        weighted_overlap = overlap + (endpoint_overlap * 3)
        function_match = int(story_function in beat.story_functions)
        return (
            function_match if story_function == "character_turn" else weighted_overlap,
            weighted_overlap if story_function == "character_turn" else function_match,
            int(
                story_function == "character_turn"
                and (
                    beat.narrative_function == "release"
                    or "consequence" in beat.story_functions
                    or "aftermath" in beat.story_functions
                )
            ),
            -beat.order,
        )

    if not candidates:
        return None, 0
    best = max(candidates, key=score)
    best_score = score(best)
    return best, (
        best_score[1] if story_function == "character_turn" else best_score[0]
    )


def _protected_language_key(text: str) -> str:
    return re.sub(
        r"\s+/\s+",
        " ",
        normalize_display_text(text),
    )


def _quoted_source_wording(text: str) -> tuple[str, ...]:
    """Return publishable wording enclosed in straight or curly double quotes."""

    return tuple(
        wording
        for match in re.finditer(r'[“"]\s*(.+?)\s*[”"]', text, flags=re.DOTALL)
        if (wording := re.sub(r"\s+", " ", match.group(1)).strip())
    )


def _materialize_protected_lettering(
    candidate: BookAdaptation,
    source: SourceDocument,
    brief: AdaptationBrief,
) -> BookAdaptation:
    """Realize protected wording and ledgered speech as canonical lettering."""

    beats = list(candidate.beats)
    ledger = list(candidate.ledger)
    existing_keys = {
        _protected_language_key(item.text) for beat in beats for item in beat.lettering
    }
    source_by_id = {unit.id: unit for unit in source.units}
    ledger_index_by_source = {
        entry.source_unit_id: index for index, entry in enumerate(ledger)
    }
    next_lettering_number = (
        max(
            (
                int(match.group(1))
                for beat in beats
                for item in beat.lettering
                if (match := re.fullmatch(r"lettering_(\d+)", item.id))
            ),
            default=0,
        )
        + 1
    )
    kind_by_disposition = {
        "dialogue": "dialogue",
        "thought": "thought",
        "caption": "caption",
    }
    for phrase in brief.protected_language:
        phrase_key = _protected_language_key(phrase)
        if any(phrase_key in existing for existing in existing_keys):
            continue
        source_unit = next(
            (
                unit
                for unit in source.units
                if phrase in unit.text
                or phrase_key in _protected_language_key(unit.text)
            ),
            None,
        )
        if source_unit is None:
            continue
        ledger_index = ledger_index_by_source.get(source_unit.id)
        entry = ledger[ledger_index] if ledger_index is not None else None
        if (
            entry is not None
            and entry.disposition not in kind_by_disposition
            and entry.adapted_beat_ids
        ):
            entry = entry.model_copy(update={"disposition": "caption", "reason": None})
            ledger[ledger_index] = entry
        kind = kind_by_disposition.get(entry.disposition) if entry else None
        destination = (
            entry.adapted_beat_ids[0] if entry and entry.adapted_beat_ids else None
        )
        if kind is None or destination is None:
            continue
        beat_index = next(
            (index for index, beat in enumerate(beats) if beat.id == destination),
            None,
        )
        if beat_index is None:
            continue
        lettering = LetteringItem(
            id=f"lettering_{next_lettering_number:04d}",
            kind=kind,
            text=phrase,
            source_unit_ids=(source_unit.id,),
        )
        next_lettering_number += 1
        beat = beats[beat_index]
        beats[beat_index] = beat.model_copy(
            update={"lettering": (*beat.lettering, lettering)}
        )
        existing_keys.add(phrase_key)

    realized_dispositions = {
        (source_unit_id, item.kind)
        for beat in beats
        for item in beat.lettering
        for source_unit_id in item.source_unit_ids
    }
    for entry in ledger:
        kind = kind_by_disposition.get(entry.disposition)
        if (
            kind not in {"dialogue", "thought"}
            or (entry.source_unit_id, kind) in realized_dispositions
            or not entry.adapted_beat_ids
        ):
            continue
        source_unit = source_by_id.get(entry.source_unit_id)
        if source_unit is None:
            continue
        quoted_wording = _quoted_source_wording(source_unit.text)
        if not quoted_wording:
            continue
        destination = entry.adapted_beat_ids[0]
        beat_index = next(
            (index for index, beat in enumerate(beats) if beat.id == destination),
            None,
        )
        if beat_index is None:
            continue
        beat = beats[beat_index]
        additions = []
        for wording in quoted_wording:
            additions.append(
                LetteringItem(
                    id=f"lettering_{next_lettering_number:04d}",
                    kind=kind,
                    text=wording,
                    source_unit_ids=(entry.source_unit_id,),
                )
            )
            next_lettering_number += 1
        beats[beat_index] = beat.model_copy(
            update={"lettering": (*beat.lettering, *additions)}
        )
        realized_dispositions.add((entry.source_unit_id, kind))

    return BookAdaptation.model_validate(
        {
            **candidate.model_dump(mode="json"),
            "content_sha256": "",
            "beats": [beat.model_dump(mode="json") for beat in beats],
            "ledger": [entry.model_dump(mode="json") for entry in ledger],
        }
    )


class AdaptationInvariantError(ValueError):
    """Raised when model output violates a blocking Adapt invariant."""

    def __init__(self, validation: AdaptationValidation) -> None:
        codes = ", ".join(failure.code for failure in validation.invariant_failures)
        super().__init__(f"Book adaptation has invariant failures: {codes}")
        self.validation = validation


StructuredGenerator = Callable[
    ...,
    Awaitable[ApiResult[Mapping[str, Any]]],
]


def _record_result_usage(ctx: StageRuntime, result: ApiResult[Any]) -> None:
    for usage in (result.usage, *result.additional_usage):
        if usage is not None:
            ctx.record_api_usage(usage)


def _brief_view(brief: AdaptationBrief) -> dict[str, Any]:
    """Project only authorial constraints; revision metadata has no model value."""

    return brief.model_dump(
        mode="json",
        exclude={"revision", "content_sha256", "status"},
    )


def _source_units_view(
    source: SourceDocument,
    source_unit_ids: Iterable[str],
) -> list[dict[str, str]]:
    """Compact source provenance without offsets and duplicated ordinals."""

    wanted = set(source_unit_ids)
    return [
        {"id": unit.id, "text": unit.text} for unit in source.units if unit.id in wanted
    ]


def _story_bible_view(
    story_bible: StoryBible,
    *,
    scene_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return Adapt's semantic Story Bible projection, excluding visual prose."""

    scenes = [
        scene
        for scene in story_bible.scenes
        if scene_ids is None or scene.id in scene_ids
    ]
    character_ids = {
        character_id for scene in scenes for character_id in scene.character_ids
    }
    location_ids = {scene.location_id for scene in scenes}
    return {
        "title": story_bible.title,
        "author": story_bible.author,
        "characters": [
            {
                "id": character.id,
                "name": character.name,
                "relationships": [
                    relationship.model_dump(mode="json")
                    for relationship in character.relationships
                ],
                "appearance_state_ids": [
                    state.id for state in character.appearance_states
                ],
                "appearance_states": [
                    {
                        "id": state.id,
                        "label": state.label,
                        "canonical_equivalent": state.canonical_equivalent,
                    }
                    for state in character.appearance_states
                ],
                "appearance_timeline": [
                    activation.model_dump(mode="json")
                    for activation in character.appearance_timeline
                ],
            }
            for character in story_bible.characters
            if scene_ids is None or character.id in character_ids
        ],
        "locations": [
            {
                "id": location.id,
                "name": location.name,
                "appearance_state_ids": [
                    state.id for state in location.appearance_states
                ],
                "appearance_states": [
                    {
                        "id": state.id,
                        "label": state.label,
                        "canonical_equivalent": state.canonical_equivalent,
                    }
                    for state in location.appearance_states
                ],
                "appearance_timeline": [
                    activation.model_dump(mode="json")
                    for activation in location.appearance_timeline
                ],
            }
            for location in story_bible.locations
            if scene_ids is None or location.id in location_ids
        ],
        "props": [
            {"id": prop.id, "name": prop.name,
             "appearance_states": [state.model_dump(mode="json") for state in prop.appearance_states],
             "appearance_timeline": [item.model_dump(mode="json") for item in prop.appearance_timeline]}
            for prop in story_bible.props
        ],
        "scenes": [
            {
                "id": scene.id,
                "chapter": scene.chapter,
                "title": scene.title,
                "location_id": scene.location_id,
                "character_ids": scene.character_ids,
                "summary": scene.summary,
                "scene_type": scene.scene_type,
                "narrative_beat": scene.narrative_beat,
            }
            for scene in scenes
        ],
        "narrative_arcs": [
            arc.model_dump(mode="json") for arc in story_bible.narrative_arcs
        ],
    }


def _scene_obligations(
    story_bible: StoryBible,
    *,
    scene_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Derive explicit local completeness obligations before costly drafting."""

    return [
        {
            "scene_id": scene.id,
            "narrative_function": scene.narrative_beat,
            "required_reader_facts": [scene.summary],
            "required_speaker_entity_ids": scene.character_ids,
            "relative_weight": (
                "high"
                if scene.narrative_beat
                in {"inciting_incident", "climax", "resolution", "turning_point"}
                else "standard"
            ),
            "silence_policy": (
                "Silence is allowed only for self-explanatory action or reaction; "
                "testimony, deduction, chronology, and causal links require lettering."
            ),
        }
        for scene in story_bible.scenes
        if scene_ids is None or scene.id in scene_ids
    ]


def _treatment_view(treatment: NarrativeTreatment) -> dict[str, Any]:
    """Remove requirement wording already present in the approved registry."""

    return treatment.model_dump(
        mode="json",
        exclude={"essential_events", "character_turns"},
    )


def build_narrative_treatment_prompt(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
) -> str:
    """Compile the book-wide dramatic-reasoning prompt from canonical inputs."""

    context = {
        "source_units": _source_units_view(
            source,
            (unit.id for unit in source.units),
        ),
        "source_scenes": [
            {
                "id": scene.id,
                "title": scene.title,
                "first_unit_id": scene.first_unit_id,
                "last_unit_id": scene.last_unit_id,
            }
            for scene in source.scenes
        ],
        "story_bible": _story_bible_view(story_bible),
        "scene_obligations": _scene_obligations(story_bible),
        "approved_adaptation_brief": _brief_view(brief),
        "approved_requirement_registry": _requirement_registry(brief),
    }
    return (
        "Create one book-wide narrative treatment for the complete adaptation. "
        "Account for the causal spine, essential events, character turns, reveals, "
        "reactions, consequences, transitions, aftermath, motifs, narrator voice, "
        "and relative narrative emphasis. Carry every approved essential event and "
        "character turn from the brief into the matching treatment field using the "
        "brief's own wording. Copy the corresponding stable IDs from "
        "approved_requirement_registry into essential_event_ids and "
        "character_turn_ids. Use the approved target page range only "
        "to guide proportional selection. Do not allocate pages, panels, layouts, "
        "or geometry. Do not create parallel per-scene adaptations or reconciliation "
        "work. scene_obligations are mandatory local completeness constraints: "
        "preserve every required reader fact, speaker function, relative weight, "
        "and silence policy in the global treatment. Return only the "
        "narrative-treatment JSON object.\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def build_book_adaptation_prompt(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
    treatment: NarrativeTreatment,
    *,
    primary_source_unit_ids: tuple[str, ...] | None = None,
    shard_index: int = 1,
    shard_count: int = 1,
    owned_requirement_ids: tuple[str, ...] | None = None,
) -> str:
    """Compile the single ordered book-adaptation prompt contract."""

    primary_ids = primary_source_unit_ids or tuple(unit.id for unit in source.units)
    primary_id_set = set(primary_ids)
    source_units = _source_units_view(source, primary_ids)
    source_scenes = [
        {
            "id": scene.id,
            "title": scene.title,
            "first_unit_id": next(
                source_id
                for source_id in scene.unit_ids(source)
                if source_id in primary_id_set
            ),
            "last_unit_id": next(
                source_id
                for source_id in reversed(scene.unit_ids(source))
                if source_id in primary_id_set
            ),
        }
        for scene in source.scenes
        if primary_id_set.intersection(scene.unit_ids(source))
    ]
    scene_ids = {scene["id"] for scene in source_scenes}
    context = {
        "adaptation_scope": {
            "shard_index": shard_index,
            "shard_count": shard_count,
            "primary_source_unit_ids": primary_ids,
        },
        "source_units": source_units,
        "source_scenes": source_scenes,
        "story_bible": _story_bible_view(story_bible, scene_ids=scene_ids),
        "scene_obligations": _scene_obligations(
            story_bible,
            scene_ids=scene_ids,
        ),
        "approved_adaptation_brief": _brief_view(brief),
        "approved_requirement_registry": _requirement_registry(brief),
        "narrative_treatment": _treatment_view(treatment),
    }
    if owned_requirement_ids is not None:
        context["adaptation_scope"]["owned_requirement_ids"] = owned_requirement_ids
    scope_instruction = ""
    if shard_count > 1:
        scope_instruction = (
            f"This is bounded internal shard {shard_index} of {shard_count} in one "
            "globally ordered BookAdaptation. Return beats and ledger entries only "
            "for adaptation_scope.primary_source_unit_ids, in their source order. "
            "Do not account for source units outside this shard. Beat, lettering, "
            "and order identifiers may be shard-local; the deterministic merge "
            "rebases them into one global sequence. The shard is a transport "
            "boundary, never an independently authoritative adaptation. "
        )
    ownership_instruction = ""
    if owned_requirement_ids is not None and shard_count > 1:
        # Without this the shard sees all nine approved requirements and has to
        # infer which fall in its own source range.
        ownership_instruction = (
            "adaptation_scope.owned_requirement_ids lists the approved "
            "requirements whose content falls in this shard's source range; "
            "carry each one onto the beat that realizes it. Requirements outside "
            "that list belong to other shards — carry one only if this shard's "
            "own source plainly realizes it. "
        )
    faithful_instruction = ""
    if brief.transformation_level == "faithful":
        faithful_instruction = (
            "This is a faithful adaptation. Treat narrative completeness as a "
            "blocking requirement: every reveal must receive an explicit reaction "
            "or aftermath before the next transition, and do not compress a "
            "multi-step explanation into a single visual beat when separate beats "
            "would preserve the causal chain. Do not erase an extracted source "
            "scene or concentrate nearly all intentional omissions in one part of "
            "the book. Preserve the relative weight of investigation, setup, "
            "corroboration, climax, and aftermath rather than stripping early "
            "evidence to make room for later spectacle. "
        )
    return (
        scope_instruction
        + ownership_instruction
        + faithful_instruction
        + "Write the globally ordered AdaptedBeats for the supplied source scope. "
        "Assume the reader has not read the source and cannot see this JSON: "
        "beat summaries are never visible to the reader. Every causal link, motive, "
        "date or place change, deduction, testimony, and relationship between "
        "independent pieces of evidence that cannot be inferred unambiguously from "
        "a still image must appear in complete canonical lettering. Use silence "
        "deliberately for visually self-explanatory action, awe, dread, or reaction; "
        "never use silent beats as a substitute for exposition or connective logic. "
        "Own complete, publishable dialogue, thought, caption, and SFX wording; "
        "never return fragments or trailing-clipped display text. Preserve every "
        "protected-language string verbatim. Record causal events, reveals, "
        "reactions, consequences, transitions, aftermath, character turns, and "
        "appearance-state changes explicitly. Every continuity transition must "
        "set scope_id to a stable Story Bible entity ID for knowledge/emotion, or "
        "a stable narrative-thread ID for time/place. Cite each approved requirement "
        "by its stable registry key in brief_requirement_ids on the beat that "
        "actually realizes it. Do not repeat requirement text in the beat contract. "
        "The target page range is not a beat-count target: "
        "derive granularity from the story rather than producing one beat per page. "
        "Each adapted beat should carry one drawable story moment. List its visible "
        "character, location, and recurring prop IDs in entity_ids using the Story Bible; "
        "do not invent IDs or omit props whose appearance matters. Split compound "
        "action, reaction, transition, reveal, consequence, and aftermath into "
        "separate visual beats whenever each moment needs distinct visual weight; "
        "never pad by duplicating content. "
        "For every ledger entry marked dialogue, thought, or caption, cite its "
        "source unit on a matching source-linked canonical LetteringItem; a beat "
        "summary alone does not realize a lettering disposition. Cite source-unit "
        "provenance. For every LetteringItem, set delivery explicitly. On-screen "
        "dialogue or thought uses delivery='onscreen', one precise speaker name, "
        "and that Story Bible character's speaker_entity_id. Off-panel voices or "
        "choruses use delivery='offscreen' and a precise speaker label without "
        "inventing a visible character. Narration uses delivery='narration'. "
        "Quoted prose, translated inscriptions, manuscript excerpts, and phrases "
        "reported by a narrator use caption plus delivery='quoted_text'; do not "
        "misclassify quoted prose as dialogue by a present character. SFX uses "
        "delivery='display'. Never use a slash-separated or combined speaker to "
        "stand for multiple possible owners. "
        "Cite source-unit provenance. Do not restate the full source ledger: code "
        "derives depicted, dialogue, thought, and caption dispositions from beats "
        "and lettering. Return ledger=[] and author ledger_exceptions only for "
        "visual_motif, compressed_into, or intentionally_omitted source units. Group "
        "every contiguous run that shares a disposition and destination into one "
        "exception with one concise reason; never emit repetitive per-unit "
        "exceptions for the same decision. Compression "
        "requires a reason and an existing adapted-beat destination. Intentional "
        "omission requires a reason, the function intentionally removed, and no "
        "adapted-beat destination. Every source unit not cited by a beat requires "
        "an intentional-omission exception. Treat scene_obligations as mandatory "
        "local completeness and proportional-weight constraints. Use the target "
        "page range only for proportional "
        "selection. Do not allocate pages, panels, layouts, or geometry. Do not "
        "create scene-parallel screenplays or reconciliation work. Return one JSON "
        "object containing only beats, ledger=[], and ledger_exceptions.\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def build_adaptation_blueprint_prompt(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
    treatment: NarrativeTreatment,
    *,
    primary_source_unit_ids: tuple[str, ...],
    owned_requirement_ids: tuple[str, ...],
    shard_index: int,
    shard_count: int,
) -> str:
    """Ask only for story structure, before any final prose can obscure gaps."""

    primary_id_set = set(primary_source_unit_ids)
    source_scenes = [
        {
            "id": scene.id,
            "title": scene.title,
            "first_unit_id": next(
                source_id
                for source_id in scene.unit_ids(source)
                if source_id in primary_id_set
            ),
            "last_unit_id": next(
                source_id
                for source_id in reversed(scene.unit_ids(source))
                if source_id in primary_id_set
            ),
        }
        for scene in source.scenes
        if primary_id_set.intersection(scene.unit_ids(source))
    ]
    scene_ids = {scene["id"] for scene in source_scenes}
    context = {
        "adaptation_scope": {
            "shard_index": shard_index,
            "shard_count": shard_count,
            "primary_source_unit_ids": primary_source_unit_ids,
            "owned_requirement_ids": owned_requirement_ids,
        },
        "source_units": _source_units_view(source, primary_source_unit_ids),
        "source_scenes": source_scenes,
        "story_bible": _story_bible_view(story_bible, scene_ids=scene_ids),
        "scene_obligations": _scene_obligations(story_bible, scene_ids=scene_ids),
        "approved_adaptation_brief": _brief_view(brief),
        "approved_requirement_registry": _requirement_registry(brief),
        "narrative_treatment": _treatment_view(treatment),
    }
    faithful = (
        "For this faithful adaptation, preserve every causal step and each "
        "reveal's reaction or aftermath before a transition. "
        if brief.transformation_level == "faithful"
        else ""
    )
    return (
        f"Design locked story structure for internal shard {shard_index} of "
        f"{shard_count}. {faithful}"
        "Assume a reader has never read the novel. Create one drawable beat per "
        "story moment and make chronology, evidence, motives, deductions, reactions, "
        "consequences, and aftermath explicit in the beat sequence. Preserve the "
        "relative weight in scene_obligations. Carry every owned requirement onto "
        "the beat that realizes it. Record continuity and appearance changes using "
        "stable Story Bible IDs. Do not write dialogue, captions, thoughts, SFX, "
        "pages, panels, or layouts: another locked expansion pass writes the final "
        "words without changing this structure. Do not return a canonical ledger. "
        "Code derives ordinary source accounting from beat provenance. Use "
        "ledger_exceptions only for visual_motif, compressed_into, or "
        "intentionally_omitted units; every uncited source unit requires an explicit "
        "exception. Return only beats and ledger_exceptions.\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def build_locked_lettering_prompt(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
    treatment: NarrativeTreatment,
    blueprint: _BlueprintDraft,
    *,
    primary_source_unit_ids: tuple[str, ...],
    shard_index: int,
    shard_count: int,
) -> str:
    """Expand a validated blueprint without allowing story redesign."""

    scene_ids = {
        scene.id
        for scene in source.scenes
        if set(primary_source_unit_ids).intersection(scene.unit_ids(source))
    }
    context = {
        "adaptation_scope": {
            "shard_index": shard_index,
            "shard_count": shard_count,
        },
        "source_units": _source_units_view(source, primary_source_unit_ids),
        "story_bible": _story_bible_view(story_bible, scene_ids=scene_ids),
        "approved_adaptation_brief": _brief_view(brief),
        "narrative_treatment": _treatment_view(treatment),
        "locked_blueprint": blueprint.model_dump(mode="json"),
    }
    return (
        "Write complete publishable lettering for the locked blueprint. Return "
        "exactly one entry for every blueprint beat_id, in order; an entry may have "
        "empty lettering only when the beat is visually self-explanatory. Do not "
        "add, remove, reorder, summarize, merge, or redesign beats. Every causal "
        "link, motive, chronology change, deduction, testimony, and relationship "
        "between evidence that a still image cannot establish must appear in "
        "dialogue, thought, or caption. Preserve protected language verbatim. "
        "For every LetteringItem cite source_unit_ids and set delivery. On-screen "
        "dialogue/thought requires one precise speaker and its speaker_entity_id; "
        "off-panel voices use offscreen; narration uses narration; quoted prose, "
        "inscriptions, and manuscript excerpts use caption/quoted_text; SFX uses "
        "display. Never combine two speakers in one item. Return only beat_id and "
        "lettering; the application owns all structural fields and the ledger.\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _adaptation_shards(
    source: SourceDocument,
    *,
    model: str,
) -> tuple[tuple[str, ...], ...]:
    """Bound projected output while preserving one ordered book-level authority."""

    shards: list[tuple[str, ...]] = []
    current: list[str] = []
    current_chars = 0
    output_limit = get_pricing_resolver().model_output_token_limit(model)
    output_budget = max(1, int(output_limit * _ADAPT_OUTPUT_BUDGET_RATIO))
    source_char_budget = max(
        1,
        int(output_budget / _ADAPT_OUTPUT_TOKENS_PER_SOURCE_CHAR),
    )
    unit_by_id = {unit.id: unit for unit in source.units}

    for scene in source.scenes:
        for source_id in scene.unit_ids(source):
            unit_chars = len(unit_by_id[source_id].text)
            exceeds_unit_limit = len(current) >= _ADAPT_SHARD_MAX_UNITS
            exceeds_output_budget = (
                current and current_chars + unit_chars > source_char_budget
            )
            if exceeds_unit_limit or exceeds_output_budget:
                shards.append(tuple(current))
                current = []
                current_chars = 0
            current.append(source_id)
            current_chars += unit_chars
    if current:
        shards.append(tuple(current))
    return tuple(shards)


def estimate_book_adaptation_cost(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
    *,
    model: str,
    treatment: NarrativeTreatment | None = None,
    story_instruction: str = "",
) -> float:
    """Estimate one clean sharded pass plus a bounded repair allowance."""

    instruction_suffix = story_instruction_section(story_instruction, stage="adapt")
    treatment_prompt = build_narrative_treatment_prompt(
        source, story_bible, brief
    ) + instruction_suffix
    if treatment is None:
        treatment = NarrativeTreatment(
            causal_spine=("Pending book-level treatment.",),
            essential_events=brief.essential_events,
            essential_event_ids=tuple(
                f"essential_event_{index:03d}"
                for index, _ in enumerate(brief.essential_events, 1)
            ),
            character_turns=brief.character_turns,
            character_turn_ids=tuple(
                f"character_turn_{index:03d}"
                for index, _ in enumerate(brief.character_turns, 1)
            ),
        )
    shards = _adaptation_shards(source, model=model)
    unit_by_id = {unit.id: unit for unit in source.units}
    shard_requirements = partition_requirements_by_shard(source, brief, shards)
    blueprint_prompts = [
        build_adaptation_blueprint_prompt(
            source,
            story_bible,
            brief,
            treatment,
            primary_source_unit_ids=source_ids,
            owned_requirement_ids=shard_requirements[index - 1],
            shard_index=index,
            shard_count=len(shards),
        )
        + instruction_suffix
        for index, source_ids in enumerate(shards, 1)
    ]
    clean_pass = estimate_text_cost(
        model,
        treatment_prompt,
        output_chars=max(12_000, len(source.text)),
    ) + sum(
        (
            estimate_text_cost(
                model,
                prompt,
                output_chars=max(
                    4_000,
                    int(_shard_output_chars(unit_by_id, source_ids) * 0.55),
                ),
            )
            + estimate_text_cost(
                model,
                prompt,
                output_chars=max(
                    3_000,
                    int(_shard_output_chars(unit_by_id, source_ids) * 0.45),
                ),
            )
        )
        for prompt, source_ids in zip(blueprint_prompts, shards, strict=True)
    )
    return clean_pass * 1.25


def partition_requirements_by_shard(
    source: SourceDocument,
    brief: AdaptationBrief,
    shards: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Assign each approved requirement to the shard whose source realizes it.

    A shard sees the whole brief but only its own source units, so it has to
    guess which requirements are its responsibility — and a miss is a
    book-global invariant failure that costs a repair round. The assignment is
    derivable: requirements and shards are both in narrative order, so scoring
    word overlap against each shard's source text and forbidding the result from
    moving backwards recovers the intended split.

    Advisory, not authoritative: a shard is still told it may carry a
    requirement its source clearly realizes, and the existing canonicalization
    and validation remain the safety net for a misassignment.
    """

    unit_by_id = {unit.id: unit for unit in source.units}
    shard_words = [
        _requirement_words(
            " ".join(
                unit_by_id[source_id].text
                for source_id in shard
                if source_id in unit_by_id
            )
        )
        for shard in shards
    ]
    owners: list[list[str]] = [[] for _ in shards]
    if not shards:
        return ()
    # Essential events and character turns are two independent ordered
    # sequences, so each carries its own floor — sharing one would push every
    # character turn into whichever shard the last essential event reached.
    floors: dict[str, int] = {}
    for requirement_id, requirement in _requirement_registry(brief).items():
        prefix = requirement_id.rsplit("_", 1)[0]
        floor = floors.get(prefix, 0)
        wanted = _requirement_words(requirement)
        # Ties and blanks fall to `floor`, which keeps a requirement adjacent to
        # its predecessor rather than dropping it into an unrelated shard.
        best_index = floor
        best_overlap = -1
        for index in range(floor, len(shards)):
            overlap = len(wanted.intersection(shard_words[index]))
            if overlap > best_overlap:
                best_index = index
                best_overlap = overlap
        owners[best_index].append(requirement_id)
        floors[prefix] = best_index
    return tuple(tuple(ids) for ids in owners)


def _shard_output_chars(
    unit_by_id: dict[str, Any], shard_source_ids: Iterable[str]
) -> int:
    """Expected adapted-output size for one shard, in characters.

    Same basis as the cost estimate, reused to turn streamed characters into a
    progress fraction.
    """
    return max(
        8_000,
        int(
            sum(len(unit_by_id[source_id].text) for source_id in shard_source_ids)
            * _ADAPT_OUTPUT_TOKENS_PER_SOURCE_CHAR
            * 4
        ),
    )


def _normalize_blueprint(value: object) -> dict[str, Any]:
    """Discard obsolete model-authored ledger/lettering without a paid retry."""

    if not isinstance(value, Mapping):
        return {}
    beat_fields = set(_BlueprintBeat.model_fields)
    beats = []
    raw_beats = value.get("beats", ())
    if isinstance(raw_beats, (list, tuple)):
        for beat in raw_beats:
            if isinstance(beat, Mapping):
                beats.append({key: beat[key] for key in beat_fields if key in beat})
    return {
        "beats": beats,
        "ledger_exceptions": value.get("ledger_exceptions", ()),
    }


def _validate_blueprint_scope(
    blueprint: _BlueprintDraft,
    *,
    source_unit_ids: tuple[str, ...],
    owned_requirement_ids: tuple[str, ...],
) -> None:
    """Fail compact structure before paying to write its final prose."""

    allowed = set(source_unit_ids)
    beat_ids = {beat.id for beat in blueprint.beats}
    cited = {
        source_id for beat in blueprint.beats for source_id in beat.source_unit_ids
    }
    excepted = {
        source_id
        for exception in blueprint.ledger_exceptions
        for source_id in exception.source_unit_ids
    }
    unknown = sorted((cited | excepted) - allowed)
    missing = sorted(allowed - cited - excepted)
    missing_requirements = sorted(
        set(owned_requirement_ids)
        - {
            requirement_id
            for beat in blueprint.beats
            for requirement_id in beat.brief_requirement_ids
        }
    )
    bad_destinations = sorted(
        {
            beat_id
            for exception in blueprint.ledger_exceptions
            for beat_id in exception.adapted_beat_ids
            if beat_id not in beat_ids
        }
    )
    incomplete_transitions = [
        beat.id
        for beat in blueprint.beats
        if (
            beat.narrative_function == "transition"
            or "transition" in beat.story_functions
        )
        and not beat.transitions
    ]
    errors = []
    if unknown:
        errors.append(f"unknown source_unit_ids: {unknown}")
    if missing:
        errors.append(f"source units missing beats or ledger_exceptions: {missing}")
    if missing_requirements:
        errors.append(f"missing owned requirement IDs: {missing_requirements}")
    if bad_destinations:
        errors.append(f"ledger exceptions target unknown beats: {bad_destinations}")
    if incomplete_transitions:
        errors.append(
            "transition beats missing continuity transitions: "
            f"{incomplete_transitions}"
        )
    if errors:
        raise ValueError("; ".join(errors))


def _canonicalize_blueprint_requirements(
    blueprint: _BlueprintDraft,
    brief: AdaptationBrief,
) -> _BlueprintDraft:
    draft = _canonicalize_draft_requirements(
        _BookDraft(
            beats=tuple(beat.to_adapted_beat() for beat in blueprint.beats),
        ),
        brief,
    )
    return blueprint.model_copy(
        update={
            "beats": tuple(
                _BlueprintBeat.model_validate(
                    beat.model_dump(mode="python", exclude={"lettering"})
                )
                for beat in draft.beats
            )
        }
    )


async def _generate_blueprint(
    *,
    prompt: str,
    brief: AdaptationBrief,
    source_unit_ids: tuple[str, ...],
    owned_requirement_ids: tuple[str, ...],
    checkpoint_name: str,
    model: str,
    artifacts: TargetArtifacts,
    generate: StructuredGenerator,
    ctx: StageRuntime,
) -> _BlueprintDraft:
    key = _checkpoint_key(model=model, feature="adapt.blueprint", prompt=prompt)
    cached = _read_checkpoint(
        artifacts,
        name=checkpoint_name,
        input_sha256=key,
        model_type=_BlueprintDraft,
    )
    attempt_prompt = prompt
    repairing_cached_blueprint = False
    if isinstance(cached, _BlueprintDraft):
        try:
            _validate_blueprint_scope(
                cached,
                source_unit_ids=source_unit_ids,
                owned_requirement_ids=owned_requirement_ids,
            )
            return cached
        except ValueError as error:
            repairing_cached_blueprint = True
            # A validator added after the checkpoint was written can cheaply
            # repair the compact cached structure instead of discarding every
            # paid stage result or crashing before a model call.
            attempt_prompt = _schema_repair_prompt(
                prompt,
                cached.model_dump(mode="json"),
                error,
            )
    for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
        result = await generate(
            system_prompt=(
                "You are the structural architect for a graphic novel. Return "
                "compact locked story structure, not prose."
            ),
            user_content=attempt_prompt,
            feature="adapt.blueprint",
            json_schema=_BlueprintDraft.model_json_schema(),
            quality_tier=(
                "quality"
                if repairing_cached_blueprint or attempt > 1
                else None
            ),
        )
        _record_result_usage(ctx, result)
        try:
            blueprint = _BlueprintDraft.model_validate(
                _normalize_blueprint(result.value)
            )
            blueprint = _canonicalize_blueprint_requirements(blueprint, brief)
            _validate_blueprint_scope(
                blueprint,
                source_unit_ids=source_unit_ids,
                owned_requirement_ids=owned_requirement_ids,
            )
        except (ValidationError, ValueError) as error:
            if attempt == _MAX_ADAPT_ATTEMPTS:
                raise
            attempt_prompt = _schema_repair_prompt(prompt, result.value, error)
            continue
        _write_checkpoint(
            artifacts,
            name=checkpoint_name,
            input_sha256=key,
            payload=blueprint,
        )
        return blueprint
    raise AssertionError("blueprint loop must return or raise")


def _apply_locked_lettering(
    blueprint: _BlueprintDraft,
    lettering: _LetteringDraft,
) -> _BookDraft:
    by_id = {entry.beat_id: entry.lettering for entry in lettering.beats}
    expected = {beat.id for beat in blueprint.beats}
    if set(by_id) != expected or len(lettering.beats) != len(expected):
        raise ValueError(
            "lettering must contain each locked blueprint beat exactly once"
        )
    return _BookDraft(
        beats=tuple(
            beat.to_adapted_beat().model_copy(
                update={"lettering": by_id[beat.id]}
            )
            for beat in blueprint.beats
        ),
        ledger_exceptions=blueprint.ledger_exceptions,
    )


def _lettering_contract_errors(
    item: LetteringItem,
    *,
    known_speaker_ids: set[str],
) -> tuple[str, ...]:
    allowed_delivery = {
        "dialogue": {"onscreen", "offscreen"},
        "thought": {"onscreen", "offscreen"},
        "caption": {"narration", "quoted_text"},
        "sfx": {"display"},
    }
    evidence: list[str] = []
    if item.delivery not in allowed_delivery[item.kind]:
        evidence.append(
            f"{item.kind!r} lettering requires delivery in "
            f"{sorted(allowed_delivery[item.kind])!r}; found {item.delivery!r}."
        )
    if item.kind in {"dialogue", "thought"} and not item.speaker:
        evidence.append("Dialogue and thought require one precise speaker label.")
    if item.speaker is not None and "/" in item.speaker:
        evidence.append(
            "Speaker labels cannot combine multiple possible owners with '/'; "
            "author separate lettering items or one explicit chorus."
        )
    if item.delivery == "onscreen":
        if not item.speaker_entity_id:
            evidence.append("On-screen lettering requires speaker_entity_id.")
        elif item.speaker_entity_id not in known_speaker_ids:
            evidence.append(
                f"Speaker entity {item.speaker_entity_id!r} is not a "
                "Story Bible character."
            )
    elif (
        item.speaker_entity_id is not None
        and item.speaker_entity_id not in known_speaker_ids
    ):
        evidence.append(
            f"Speaker entity {item.speaker_entity_id!r} is not a "
            "Story Bible character."
        )
    return tuple(evidence)


def _validate_locked_lettering(
    lettering: _LetteringDraft,
    *,
    known_speaker_ids: set[str],
) -> None:
    _validate_lettering_items(
        (item for beat in lettering.beats for item in beat.lettering),
        known_speaker_ids=known_speaker_ids,
        error_prefix="invalid locked lettering",
    )


def _validate_lettering_items(
    items: Iterable[LetteringItem],
    *,
    known_speaker_ids: set[str],
    error_prefix: str,
) -> None:
    errors = [
        f"{item.id}: {'; '.join(evidence)}"
        for item in items
        if (
            evidence := _lettering_contract_errors(
                item,
                known_speaker_ids=known_speaker_ids,
            )
        )
    ]
    if errors:
        raise ValueError(f"{error_prefix}: " + " | ".join(errors))


def _validate_book_draft_lettering(
    draft: _BookDraft,
    *,
    known_speaker_ids: set[str],
) -> None:
    _validate_lettering_items(
        (item for beat in draft.beats for item in beat.lettering),
        known_speaker_ids=known_speaker_ids,
        error_prefix="invalid adaptation lettering",
    )


async def _generate_locked_lettering(
    *,
    prompt: str,
    blueprint: _BlueprintDraft,
    known_speaker_ids: set[str],
    checkpoint_name: str,
    model: str,
    artifacts: TargetArtifacts,
    generate: StructuredGenerator,
    ctx: StageRuntime,
) -> _BookDraft:
    key = _checkpoint_key(model=model, feature="adapt.lettering", prompt=prompt)
    cached = _read_checkpoint(
        artifacts,
        name=checkpoint_name,
        input_sha256=key,
        model_type=_LetteringDraft,
    )
    attempt_prompt = prompt
    if isinstance(cached, _LetteringDraft):
        try:
            _validate_locked_lettering(
                cached,
                known_speaker_ids=known_speaker_ids,
            )
            return _apply_locked_lettering(blueprint, cached)
        except ValueError as error:
            attempt_prompt = _schema_repair_prompt(
                prompt,
                cached.model_dump(mode="json"),
                error,
            )
    for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
        result = await generate(
            system_prompt=(
                "You are the dialogue and caption writer for a locked graphic-"
                "novel blueprint. You may write words but not redesign the story."
            ),
            user_content=attempt_prompt,
            feature="adapt.lettering",
            json_schema=_LetteringDraft.model_json_schema(),
        )
        _record_result_usage(ctx, result)
        try:
            lettering = _LetteringDraft.model_validate(result.value)
            _validate_locked_lettering(
                lettering,
                known_speaker_ids=known_speaker_ids,
            )
            draft = _apply_locked_lettering(blueprint, lettering)
        except (ValidationError, ValueError) as error:
            if attempt == _MAX_ADAPT_ATTEMPTS:
                raise
            attempt_prompt = _schema_repair_prompt(prompt, result.value, error)
            continue
        _write_checkpoint(
            artifacts,
            name=checkpoint_name,
            input_sha256=key,
            payload=lettering,
        )
        return draft
    raise AssertionError("lettering loop must return or raise")


async def _generate_book_draft(
    *,
    prompt: str,
    generate: StructuredGenerator,
    ctx: StageRuntime,
    checkpoint_name: str | None = None,
    artifacts: TargetArtifacts | None = None,
    model: str | None = None,
    known_speaker_ids: set[str],
) -> _BookDraft:
    checkpoint_key = (
        _checkpoint_key(model=model, feature="adapt.book", prompt=prompt)
        if checkpoint_name is not None and artifacts is not None and model is not None
        else None
    )
    attempt_prompt = prompt
    if (
        checkpoint_key is not None
        and checkpoint_name is not None
        and artifacts is not None
    ):
        cached = _read_checkpoint(
            artifacts,
            name=checkpoint_name,
            input_sha256=checkpoint_key,
            model_type=_BookDraft,
        )
        if isinstance(cached, _BookDraft):
            try:
                _validate_book_draft_lettering(
                    cached,
                    known_speaker_ids=known_speaker_ids,
                )
                return cached
            except ValueError as error:
                attempt_prompt = _schema_repair_prompt(
                    prompt,
                    cached.model_dump(mode="json"),
                    error,
                )

    for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
        result = await generate(
            system_prompt=(
                "You are the sole book-level Adapt writer. Return complete JSON."
            ),
            user_content=attempt_prompt,
            feature="adapt.book",
            json_schema={
                **_BookDraft.model_json_schema(),
                "properties": {
                    key: value
                    for key, value in _BookDraft.model_json_schema()[
                        "properties"
                    ].items()
                    if key != "ledger"
                },
            },
        )
        _record_result_usage(ctx, result)
        try:
            value = result.value
            if isinstance(value, Mapping):
                value = {key: inner for key, inner in value.items() if key != "ledger"}
            draft = _BookDraft.model_validate(value)
            _validate_book_draft_lettering(
                draft,
                known_speaker_ids=known_speaker_ids,
            )
        except (ValidationError, ValueError) as error:
            if attempt == _MAX_ADAPT_ATTEMPTS:
                raise
            attempt_prompt = _schema_repair_prompt(prompt, result.value, error)
            continue
        if (
            checkpoint_key is not None
            and checkpoint_name is not None
            and artifacts is not None
        ):
            _write_checkpoint(
                artifacts,
                name=checkpoint_name,
                input_sha256=checkpoint_key,
                payload=draft,
            )
        return draft
    raise AssertionError("book-draft loop must return or raise")


async def _generate_book_drafts(
    *,
    prompts: list[str],
    generate: StructuredGenerator,
    ctx: StageRuntime,
    progress_offset: int,
    progress_total: int,
    record_progress: bool,
    expected_chars: list[int] | None = None,
    detail: str = "drafting",
    checkpoint_names: list[str] | None = None,
    artifacts: TargetArtifacts | None = None,
    model: str | None = None,
    known_speaker_ids: set[str],
) -> list[_BookDraft]:
    completed = 0
    # Shards stream concurrently, so the reported fraction is how much of the
    # whole pass has arrived rather than any single shard's share of it.
    streamed = [0] * len(prompts)
    budget = sum(expected_chars) if expected_chars else 0

    def report(index: int, chars: int) -> None:
        streamed[index] = chars
        if budget <= 0:
            ctx.activity(detail=detail)
            return
        ctx.activity(fraction=sum(streamed) / budget, detail=detail)

    async def generate_one(index: int, prompt: str) -> _BookDraft:
        nonlocal completed
        with stream_observer(lambda chars: report(index, chars)):
            draft = await _generate_book_draft(
                prompt=prompt,
                generate=generate,
                ctx=ctx,
                checkpoint_name=(
                    checkpoint_names[index] if checkpoint_names is not None else None
                ),
                artifacts=artifacts,
                model=model,
                known_speaker_ids=known_speaker_ids,
            )
        if record_progress:
            ctx.record_item_done()
            completed += 1
            ctx.progress(progress_offset + completed, progress_total)
        return draft

    ctx.activity(fraction=0.0, detail=detail, force=True)
    drafts = await run_paid_shards(
        [lambda index=index, prompt=prompt: generate_one(index, prompt)
         for index, prompt in enumerate(prompts)],
        limit=_ADAPT_MAX_CONCURRENCY,
    )
    ctx.activity(fraction=1.0, detail=detail, force=True)
    return drafts


def _merge_book_drafts(
    drafts: list[_BookDraft],
) -> tuple[_BookDraft, dict[str, int]]:
    """Rebase shard-local identifiers into one consecutive global sequence."""

    beats: list[AdaptedBeat] = []
    ledger: list[AdaptationLedgerEntry] = []
    beat_to_shard: dict[str, int] = {}
    lettering_number = 0
    for shard_index, draft in enumerate(drafts, 1):
        beat_id_map: dict[str, str] = {}
        for beat in draft.beats:
            beat_id_map[beat.id] = f"beat_{len(beats) + len(beat_id_map) + 1:04d}"
        for beat in draft.beats:
            beat_to_shard[beat_id_map[beat.id]] = shard_index - 1
            lettering = []
            for item in beat.lettering:
                lettering_number += 1
                lettering.append(
                    item.model_copy(update={"id": f"lettering_{lettering_number:04d}"})
                )
            beats.append(
                beat.model_copy(
                    update={
                        "id": beat_id_map[beat.id],
                        "order": len(beats) + 1,
                        "lettering": tuple(lettering),
                    }
                )
            )
        for entry in draft.ledger:
            ledger.append(
                entry.model_copy(
                    update={
                        "adapted_beat_ids": tuple(
                            beat_id_map.get(
                                beat_id,
                                f"invalid_shard_{shard_index}_{beat_id}",
                            )
                            for beat_id in entry.adapted_beat_ids
                        )
                    }
                )
            )
    return _BookDraft(beats=tuple(beats), ledger=tuple(ledger)), beat_to_shard


def _materialize_draft_ledger(
    draft: _BookDraft,
    source_unit_ids: tuple[str, ...],
) -> _BookDraft:
    """Expand compact model decisions into the canonical source ledger."""

    beat_by_id = {beat.id: beat for beat in draft.beats}
    beats_by_source: dict[str, list[str]] = {}
    lettering_by_source: dict[str, tuple[str, str]] = {}
    for beat in draft.beats:
        for source_id in beat.source_unit_ids:
            beats_by_source.setdefault(source_id, []).append(beat.id)
        for item in beat.lettering:
            # SFX is canonical publishable lettering, but the source ledger
            # accounts for its underlying action as depicted. Keeping it out of
            # this map also lets dialogue/caption on the same source unit retain
            # the more specific reader-facing disposition.
            if item.kind == "sfx":
                continue
            for source_id in item.source_unit_ids:
                lettering_by_source.setdefault(source_id, (item.kind, beat.id))

    exception_by_source: dict[str, _LedgerException] = {}
    for exception in draft.ledger_exceptions:
        for source_id in exception.source_unit_ids:
            if source_id in exception_by_source:
                raise ValueError(
                    f"source unit {source_id!r} has duplicate ledger exceptions"
                )
            exception_by_source[source_id] = exception

    ledger: list[AdaptationLedgerEntry] = []
    for source_id in source_unit_ids:
        exception = exception_by_source.get(source_id)
        if exception is not None:
            ledger.append(
                AdaptationLedgerEntry(
                    source_unit_id=source_id,
                    disposition=exception.disposition,
                    adapted_beat_ids=exception.adapted_beat_ids,
                    reason=exception.reason,
                    preserved_function=exception.preserved_function,
                )
            )
            continue

        lettering = lettering_by_source.get(source_id)
        if lettering is not None:
            kind, beat_id = lettering
            ledger.append(
                AdaptationLedgerEntry(
                    source_unit_id=source_id,
                    disposition=kind,
                    adapted_beat_ids=(beat_id,),
                    preserved_function=(f"Realized as canonical {kind} in {beat_id}."),
                )
            )
            continue

        beat_ids = tuple(dict.fromkeys(beats_by_source.get(source_id, ())))
        if beat_ids:
            summaries = "; ".join(beat_by_id[beat_id].summary for beat_id in beat_ids)
            ledger.append(
                AdaptationLedgerEntry(
                    source_unit_id=source_id,
                    disposition="depicted",
                    adapted_beat_ids=beat_ids,
                    preserved_function=f"Depicted through: {summaries}",
                )
            )
            continue

        ledger.append(
            AdaptationLedgerEntry(
                source_unit_id=source_id,
                disposition="intentionally_omitted",
                reason=_MISSING_LEDGER_EXCEPTION,
                preserved_function=(
                    "The model omitted this source unit without the required "
                    "explicit exception."
                ),
            )
        )

    return draft.model_copy(
        update={
            "ledger": tuple(ledger),
            "ledger_exceptions": (),
        }
    )


def _merged_draft(
    drafts: list[_BookDraft],
) -> tuple[_BookDraft, dict[str, int]]:
    if len(drafts) == 1:
        return drafts[0], {beat.id: 0 for beat in drafts[0].beats}
    return _merge_book_drafts(drafts)


def _affected_shards(
    validation: AdaptationValidation,
    *,
    beat_to_shard: Mapping[str, int],
    shard_source_ids: tuple[tuple[str, ...], ...],
) -> tuple[int, ...]:
    source_to_shard = {
        source_id: shard_index
        for shard_index, source_ids in enumerate(shard_source_ids)
        for source_id in source_ids
    }
    affected: set[int] = set()
    for failure in validation.invariant_failures:
        affected.update(
            beat_to_shard[artifact_id]
            for artifact_id in failure.artifact_ids
            if artifact_id in beat_to_shard
        )
        affected.update(
            source_to_shard[source_id]
            for source_id in failure.source_unit_ids
            if source_id in source_to_shard
        )
    return tuple(sorted(affected))


def _repair_source_scope(
    source: SourceDocument,
    shard_source_ids: tuple[str, ...],
    validation: AdaptationValidation,
) -> tuple[str, ...]:
    """Expand cited failures to complete source scenes, not complete shards."""

    shard_set = set(shard_source_ids)
    failed = {
        source_id
        for failure in validation.invariant_failures
        for source_id in failure.source_unit_ids
        if source_id in shard_set
    }
    if not failed:
        return shard_source_ids
    scoped = {
        source_id
        for scene in source.scenes
        if failed.intersection(scene.unit_ids(source))
        for source_id in scene.unit_ids(source)
        if source_id in shard_set
    }
    return tuple(source_id for source_id in shard_source_ids if source_id in scoped)


def _subset_draft(
    draft: _BookDraft,
    source_unit_ids: tuple[str, ...],
) -> _BookDraft:
    wanted = set(source_unit_ids)
    beat_ids = {
        beat.id for beat in draft.beats if wanted.intersection(beat.source_unit_ids)
    }
    return _BookDraft(
        beats=tuple(beat for beat in draft.beats if beat.id in beat_ids),
        ledger=tuple(entry for entry in draft.ledger if entry.source_unit_id in wanted),
    )


def _rebase_local_draft(draft: _BookDraft) -> _BookDraft:
    beat_id_map = {
        beat.id: f"beat_{index:04d}" for index, beat in enumerate(draft.beats, 1)
    }
    lettering_number = 0
    beats: list[AdaptedBeat] = []
    for order, beat in enumerate(draft.beats, 1):
        lettering: list[LetteringItem] = []
        for item in beat.lettering:
            lettering_number += 1
            lettering.append(
                item.model_copy(update={"id": f"lettering_{lettering_number:04d}"})
            )
        beats.append(
            beat.model_copy(
                update={
                    "id": beat_id_map[beat.id],
                    "order": order,
                    "lettering": tuple(lettering),
                }
            )
        )
    return _BookDraft(
        beats=tuple(beats),
        ledger=tuple(
            entry.model_copy(
                update={
                    "adapted_beat_ids": tuple(
                        beat_id_map[beat_id]
                        for beat_id in entry.adapted_beat_ids
                        if beat_id in beat_id_map
                    )
                }
            )
            for entry in draft.ledger
        ),
    )


def _splice_draft_repair(
    draft: _BookDraft,
    repair: _BookDraft,
    source_unit_ids: tuple[str, ...],
    source_order: Mapping[str, int],
) -> _BookDraft:
    wanted = set(source_unit_ids)
    removed_beats = [
        beat for beat in draft.beats if wanted.intersection(beat.source_unit_ids)
    ]
    repair_id_map = {beat.id: f"repair_{beat.id}" for beat in repair.beats}
    namespaced_repair = _BookDraft(
        beats=tuple(
            beat.model_copy(update={"id": repair_id_map[beat.id]})
            for beat in repair.beats
        ),
        ledger=tuple(
            entry.model_copy(
                update={
                    "adapted_beat_ids": tuple(
                        repair_id_map[beat_id] for beat_id in entry.adapted_beat_ids
                    )
                }
            )
            for entry in repair.ledger
        ),
    )
    repair_destinations = {
        entry.source_unit_id: entry.adapted_beat_ids
        for entry in namespaced_repair.ledger
    }
    replacement_ids: dict[str, tuple[str, ...]] = {}
    for removed in removed_beats:
        destinations = [
            destination
            for source_id in removed.source_unit_ids
            for destination in repair_destinations.get(source_id, ())
        ]
        if not destinations:
            destinations = [
                replacement.id
                for replacement in namespaced_repair.beats
                if set(removed.source_unit_ids).intersection(
                    replacement.source_unit_ids
                )
            ]
        if not destinations and namespaced_repair.beats:
            removed_position = min(
                (
                    source_order[source_id]
                    for source_id in removed.source_unit_ids
                    if source_id in source_order
                ),
                default=len(source_order) + removed.order,
            )
            nearest = min(
                namespaced_repair.beats,
                key=lambda replacement: abs(
                    min(
                        (
                            source_order[source_id]
                            for source_id in replacement.source_unit_ids
                            if source_id in source_order
                        ),
                        default=len(source_order) + replacement.order,
                    )
                    - removed_position
                ),
            )
            destinations = [nearest.id]
        replacement_ids[removed.id] = tuple(dict.fromkeys(destinations))

    retained_beats = [
        beat for beat in draft.beats if not wanted.intersection(beat.source_unit_ids)
    ]
    combined_beats = [*retained_beats, *namespaced_repair.beats]
    combined_beats.sort(
        key=lambda beat: min(
            (
                source_order[source_id]
                for source_id in beat.source_unit_ids
                if source_id in source_order
            ),
            default=len(source_order) + beat.order,
        )
    )
    retained_ledger = []
    for entry in draft.ledger:
        if entry.source_unit_id in wanted:
            continue
        redirected = [
            replacement
            for beat_id in entry.adapted_beat_ids
            for replacement in replacement_ids.get(beat_id, (beat_id,))
        ]
        retained_ledger.append(
            entry.model_copy(
                update={"adapted_beat_ids": tuple(dict.fromkeys(redirected))}
            )
        )
    combined_ledger = [*retained_ledger, *namespaced_repair.ledger]
    combined_ledger.sort(
        key=lambda entry: source_order.get(
            entry.source_unit_id,
            len(source_order) + 1,
        )
    )
    return _rebase_local_draft(
        _BookDraft(
            beats=tuple(combined_beats),
            ledger=tuple(combined_ledger),
        )
    )


async def produce_book_adaptation(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
    /,
    *,
    artifacts: TargetArtifacts,
    ctx: StageRuntime,
    model: str,
    generate: StructuredGenerator,
    story_instruction: str = "",
) -> BookAdaptation:
    """Generate, validate, cost, and persist Adapt's one canonical artifact."""

    # An explicitly applied story change travels inside every Adapt prompt so
    # the owning stage regenerates from the approved revision. The suffix is
    # part of each prompt string before any checkpoint key is derived, so a
    # changed instruction never reuses a stale paid response.
    instruction_suffix = story_instruction_section(story_instruction, stage="adapt")
    require_approved_brief(brief)
    if artifacts.failed_adaptation_candidate_path.exists():
        recovered_candidate = _canonicalize_candidate_requirements(
            artifacts.read_failed_adaptation_candidate(),
            source,
            brief,
        )
        recovered_validation = validate_book_adaptation(
            source,
            brief,
            recovered_candidate,
            story_bible=story_bible,
        )
        if not recovered_validation.invariant_failures:
            adaptation = BookAdaptation.model_validate(
                {
                    **recovered_candidate.model_dump(mode="json"),
                    "content_sha256": "",
                    "editorial_issues": recovered_validation.editorial_issues,
                }
            )
            with ctx.execute(total=1, estimated_cost_usd=0):
                _persist_validation(
                    artifacts,
                    recovered_validation,
                    attempts=1,
                )
                artifacts.write_adaptation(adaptation)
                artifacts.clear_failed_adaptation_candidate()
                ctx.record_item_done()
                ctx.progress(1, 1)
            return adaptation

    treatment_prompt = build_narrative_treatment_prompt(
        source,
        story_bible,
        brief,
    ) + instruction_suffix
    initial_estimate = estimate_book_adaptation_cost(
        source,
        story_bible,
        brief,
        model=model,
        story_instruction=story_instruction,
    )
    shards = _adaptation_shards(source, model=model)
    total_steps = 1 + (2 * len(shards))

    with ctx.execute(total=total_steps, estimated_cost_usd=initial_estimate):
        treatment_key = _checkpoint_key(
            model=model,
            feature="adapt.narrative_treatment",
            prompt=treatment_prompt,
        )
        cached_treatment = _read_checkpoint(
            artifacts,
            name="treatment",
            input_sha256=treatment_key,
            model_type=NarrativeTreatment,
        )
        treatment = (
            cached_treatment
            if isinstance(cached_treatment, NarrativeTreatment)
            else None
        )
        if treatment is None:
            treatment_prompt_attempt = treatment_prompt
            for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
                # Heartbeat only — the treatment's output size isn't predictable
                # enough from the source to make a fraction honest.
                with stream_observer(
                    lambda chars: ctx.activity(detail="writing treatment")
                ):
                    treatment_result = await generate(
                        system_prompt=(
                            "You are the book-level narrative architect for a comic "
                            "adaptation."
                        ),
                        user_content=treatment_prompt_attempt,
                        feature="adapt.narrative_treatment",
                        json_schema=NarrativeTreatment.model_json_schema(),
                    )
                _record_result_usage(ctx, treatment_result)
                try:
                    treatment = NarrativeTreatment.model_validate(
                        normalize_treatment(treatment_result.value)
                    )
                    treatment = _canonicalize_treatment_requirements(treatment, brief)
                except ValidationError as error:
                    if attempt == _MAX_ADAPT_ATTEMPTS:
                        raise
                    treatment_prompt_attempt = _schema_repair_prompt(
                        treatment_prompt,
                        treatment_result.value,
                        error,
                    )
                    continue
                _write_checkpoint(
                    artifacts,
                    name="treatment",
                    input_sha256=treatment_key,
                    payload=treatment,
                )
                break
        assert treatment is not None
        ctx.record_item_done()
        ctx.progress(1, total_steps)

        unit_by_id = {unit.id: unit for unit in source.units}
        shard_requirements = partition_requirements_by_shard(source, brief, shards)
        blueprint_prompts = [
            build_adaptation_blueprint_prompt(
                source,
                story_bible,
                brief,
                treatment,
                primary_source_unit_ids=source_unit_ids,
                owned_requirement_ids=shard_requirements[shard_index - 1],
                shard_index=shard_index,
                shard_count=len(shards),
            )
            + instruction_suffix
            for shard_index, source_unit_ids in enumerate(shards, 1)
        ]
        ctx.set_estimated_cost(
            estimate_book_adaptation_cost(
                source,
                story_bible,
                brief,
                model=model,
                treatment=treatment,
                story_instruction=story_instruction,
            )
        )
        candidate: BookAdaptation | None = None
        validation = AdaptationValidation()
        known_speaker_ids = {character.id for character in story_bible.characters}
        completed_blueprints = 0

        async def generate_blueprint(index: int) -> _BlueprintDraft:
            nonlocal completed_blueprints
            blueprint = await _generate_blueprint(
                prompt=blueprint_prompts[index],
                brief=brief,
                source_unit_ids=shards[index],
                owned_requirement_ids=shard_requirements[index],
                checkpoint_name=f"blueprint/shard_{index + 1:03d}",
                model=model,
                artifacts=artifacts,
                generate=generate,
                ctx=ctx,
            )
            completed_blueprints += 1
            ctx.record_item_done()
            ctx.progress(1 + completed_blueprints, total_steps)
            return blueprint

        ctx.activity(fraction=0.0, detail="locking story structure", force=True)
        blueprints = await run_paid_shards(
            [lambda index=index: generate_blueprint(index) for index in range(len(shards))],
            limit=_ADAPT_MAX_CONCURRENCY,
        )
        ctx.activity(fraction=1.0, detail="locking story structure", force=True)
        lettering_prompts = [
            build_locked_lettering_prompt(
                source,
                story_bible,
                brief,
                treatment,
                blueprint,
                primary_source_unit_ids=source_ids,
                shard_index=index,
                shard_count=len(shards),
            )
            + instruction_suffix
            for index, (blueprint, source_ids) in enumerate(
                zip(blueprints, shards, strict=True),
                1,
            )
        ]
        completed_lettering = 0

        async def generate_lettering(index: int) -> _BookDraft:
            nonlocal completed_lettering
            draft = await _generate_locked_lettering(
                prompt=lettering_prompts[index],
                blueprint=blueprints[index],
                known_speaker_ids=known_speaker_ids,
                checkpoint_name=f"lettering/shard_{index + 1:03d}",
                model=model,
                artifacts=artifacts,
                generate=generate,
                ctx=ctx,
            )
            completed_lettering += 1
            ctx.record_item_done()
            ctx.progress(
                1 + len(shards) + completed_lettering,
                total_steps,
            )
            return draft

        ctx.activity(fraction=0.0, detail="writing locked lettering", force=True)
        generated_drafts = await run_paid_shards(
            [lambda index=index: generate_lettering(index) for index in range(len(shards))],
            limit=_ADAPT_MAX_CONCURRENCY,
        )
        ctx.activity(fraction=1.0, detail="writing locked lettering", force=True)
        drafts = [
            _canonicalize_draft_requirements(
                _materialize_draft_ledger(draft, source_ids),
                brief,
            )
            for draft, source_ids in zip(
                generated_drafts,
                shards,
                strict=True,
            )
        ]
        history: list[ValidationAttempt] = []
        for validation_attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
            draft, beat_to_shard = _merged_draft(drafts)
            candidate = BookAdaptation(
                revision=1,
                source_sha256=source.source_sha256,
                brief_revision=brief.revision,
                brief_sha256=brief.content_sha256,
                treatment=treatment,
                beats=draft.beats,
                ledger=draft.ledger,
            )
            candidate = _canonicalize_candidate_requirements(
                candidate,
                source,
                brief,
            )
            validation = validate_book_adaptation(
                source,
                brief,
                candidate,
                story_bible=story_bible,
            )
            history.append(_attempt_record(validation_attempt, validation))
            if not validation.invariant_failures:
                break
            artifacts.write_failed_adaptation_candidate(candidate)
            if validation_attempt == _MAX_ADAPT_ATTEMPTS:
                break
            affected = _affected_shards(
                validation,
                beat_to_shard=beat_to_shard,
                shard_source_ids=shards,
            )
            if not affected:
                break
            repair_scopes = [
                _repair_source_scope(
                    source,
                    shards[shard_index],
                    validation,
                )
                for shard_index in affected
            ]
            repair_prompts = [
                _repair_prompt(
                    build_book_adaptation_prompt(
                        source,
                        story_bible,
                        brief,
                        treatment,
                        primary_source_unit_ids=scope,
                        owned_requirement_ids=shard_requirements[shard_index],
                        shard_index=shard_index + 1,
                        shard_count=len(shards),
                    )
                    + instruction_suffix,
                    _subset_draft(drafts[shard_index], scope),
                    validation,
                    shard_index=shard_index,
                    beat_to_shard=beat_to_shard,
                )
                for shard_index, scope in zip(
                    affected,
                    repair_scopes,
                    strict=True,
                )
            ]
            generated_repairs = await _generate_book_drafts(
                prompts=repair_prompts,
                generate=generate,
                ctx=ctx,
                progress_offset=1,
                progress_total=total_steps,
                record_progress=False,
                expected_chars=[
                    _shard_output_chars(unit_by_id, scope) for scope in repair_scopes
                ],
                detail=(
                    f"repairing {len(affected)} of {len(shards)} shards "
                    f"(round {validation_attempt})"
                ),
                checkpoint_names=[
                    (
                        f"repairs/round_{validation_attempt:02d}_"
                        f"shard_{shard_index + 1:03d}"
                    )
                    for shard_index in affected
                ],
                artifacts=artifacts,
                model=model,
                known_speaker_ids=known_speaker_ids,
            )
            repaired = [
                _canonicalize_draft_requirements(
                    _materialize_draft_ledger(draft, scope),
                    brief,
                )
                for draft, scope in zip(
                    generated_repairs,
                    repair_scopes,
                    strict=True,
                )
            ]
            source_order = {unit.id: unit.ordinal for unit in source.units}
            for shard_index, scope, repaired_draft in zip(
                affected,
                repair_scopes,
                repaired,
                strict=True,
            ):
                drafts[shard_index] = _splice_draft_repair(
                    drafts[shard_index],
                    repaired_draft,
                    scope,
                    source_order,
                )

        assert candidate is not None  # validation loop runs at least once
        _persist_validation(
            artifacts,
            validation,
            attempts=validation_attempt,
            history=tuple(history),
        )
        if validation.invariant_failures:
            raise AdaptationInvariantError(validation)
        adaptation = BookAdaptation.model_validate(
            {
                **candidate.model_dump(),
                "content_sha256": "",
                "editorial_issues": validation.editorial_issues,
            }
        )
        artifacts.write_adaptation(adaptation)
        artifacts.clear_failed_adaptation_candidate()

    return adaptation


def _schema_repair_prompt(base_prompt: str, raw: object, error: Exception) -> str:
    """Re-prompt with the exact schema errors from the previous payload."""

    return (
        f"{base_prompt}\n\nYour previous response did not match the required JSON "
        "schema. Return one corrected, complete JSON object: use JSON arrays for "
        "every list field and exactly one of the permitted values for every "
        "enumerated field.\n\nYOUR PREVIOUS JSON:\n"
        f"{json.dumps(raw, indent=2, default=str)}\n\nVALIDATION ERRORS:\n{error}"
    )


def _repair_prompt(
    book_prompt: str,
    previous_draft: _BookDraft,
    validation: AdaptationValidation,
    *,
    shard_index: int,
    beat_to_shard: Mapping[str, int],
) -> str:
    relevant = [
        failure
        for failure in validation.invariant_failures
        if (
            not failure.artifact_ids
            or any(
                beat_to_shard.get(artifact_id) == shard_index
                for artifact_id in failure.artifact_ids
            )
            or not any(
                artifact_id in beat_to_shard for artifact_id in failure.artifact_ids
            )
        )
    ]
    failures = "\n".join(
        f"- [{failure.code}] {failure.message} " + " ".join(failure.evidence)
        for failure in relevant
    )
    previous = {
        "beats": [beat.model_dump(mode="json") for beat in previous_draft.beats],
        "ledger": [],
        "ledger_exceptions": [
            {
                "source_unit_ids": [entry.source_unit_id],
                "disposition": entry.disposition,
                "adapted_beat_ids": entry.adapted_beat_ids,
                "reason": entry.reason,
                "preserved_function": entry.preserved_function,
            }
            for entry in previous_draft.ledger
            if entry.disposition
            in {"visual_motif", "compressed_into", "intentionally_omitted"}
            and entry.reason != _MISSING_LEDGER_EXCEPTION
        ],
    }
    return (
        f"{book_prompt}\n\nYour previous book adaptation violated these blocking "
        "contract requirements. Return one complete corrected JSON object that "
        "resolves every one of them without dropping content you already had:\n"
        f"{failures}\n\nYOUR PREVIOUS SHARD JSON:\n"
        f"{json.dumps(previous, separators=(',', ':'), ensure_ascii=False)}"
    )


def _attempt_record(
    attempt: int, validation: AdaptationValidation
) -> ValidationAttempt:
    return ValidationAttempt(
        attempt=attempt,
        invariant_codes=tuple(
            failure.code for failure in validation.invariant_failures
        ),
        editorial_codes=tuple(issue.code for issue in validation.editorial_issues),
    )


def _persist_validation(
    artifacts: TargetArtifacts,
    validation: AdaptationValidation,
    *,
    attempts: int,
    history: tuple[ValidationAttempt, ...] = (),
) -> None:
    artifacts.write_validation(
        StageValidation(
            owner_stage="adapt",
            attempts=attempts,
            invariant_failures=validation.invariant_failures,
            editorial_issues=validation.editorial_issues,
            attempt_history=history,
        )
    )


def _best_requirement_beat(
    adaptation: BookAdaptation,
    *,
    requirement: str,
    story_function: str,
) -> AdaptedBeat | None:
    candidates = [
        beat for beat in adaptation.beats if story_function in beat.story_functions
    ]
    if not candidates:
        return None
    wanted = set(re.findall(r"\w+", requirement.casefold()))

    def score(beat: AdaptedBeat) -> tuple[int, int]:
        searchable = " ".join(
            (
                beat.summary,
                *(item.text for item in beat.lettering),
            )
        )
        overlap = len(wanted.intersection(re.findall(r"\w+", searchable.casefold())))
        return overlap, -beat.order

    return max(candidates, key=score)


def validate_book_adaptation(
    source: SourceDocument,
    brief: AdaptationBrief,
    adaptation: BookAdaptation,
    *,
    story_bible: StoryBible | None = None,
) -> AdaptationValidation:
    """Validate a candidate only against Adapt-owned canonical inputs."""

    failures: list[InvariantFailure] = []
    issues: list[EditorialIssue] = []
    if story_bible is not None:
        known_entities = {entity.id for entity in (*story_bible.characters, *story_bible.locations, *story_bible.props)}
        unknown_entities = {entity_id for beat in adaptation.beats for entity_id in beat.entity_ids} - known_entities
        if unknown_entities:
            failures.append(InvariantFailure(
                id="adapt_failure_unknown_entity", owner_stage="adapt", code="unknown_entity",
                message="Visible entity citations must resolve in the Story Bible.",
                artifact_ids=tuple(sorted(unknown_entities)),
                evidence=(f"Unknown entity IDs: {sorted(unknown_entities)!r}",),
            ))
    if adaptation.source_sha256 != source.source_sha256:
        failures.append(
            InvariantFailure(
                id="adapt_failure_source_authority_mismatch",
                owner_stage="adapt",
                code="source_authority_mismatch",
                message="Book adaptation was produced from a different source revision.",
                evidence=[
                    f"Expected source hash {source.source_sha256}; "
                    f"found {adaptation.source_sha256}."
                ],
            )
        )
    if (
        adaptation.brief_revision != brief.revision
        or adaptation.brief_sha256 != brief.content_sha256
    ):
        failures.append(
            InvariantFailure(
                id="adapt_failure_brief_authority_mismatch",
                owner_stage="adapt",
                code="brief_authority_mismatch",
                message="Book adaptation was produced from a different Brief revision.",
                evidence=[
                    f"Expected Brief revision/hash {brief.revision}/"
                    f"{brief.content_sha256}; found {adaptation.brief_revision}/"
                    f"{adaptation.brief_sha256}."
                ],
            )
        )

    expected = {unit.id for unit in source.units}
    accounted = {entry.source_unit_id for entry in adaptation.ledger}

    missing = sorted(expected - accounted)
    if missing:
        failures.append(
            InvariantFailure(
                id="adapt_failure_missing_source_disposition",
                owner_stage="adapt",
                code="missing_source_disposition",
                message="Every source unit must have one ledger disposition.",
                source_unit_ids=missing,
                evidence=[
                    "No adaptation-ledger entry exists for: " + ", ".join(missing)
                ],
            )
        )

    unknown = sorted(accounted - expected)
    if unknown:
        failures.append(
            InvariantFailure(
                id="adapt_failure_unknown_source_disposition",
                owner_stage="adapt",
                code="unknown_source_disposition",
                message="The adaptation ledger cites unknown source units.",
                source_unit_ids=unknown,
                evidence=[
                    "Ledger entries do not resolve in SourceDocument: "
                    + ", ".join(unknown)
                ],
            )
        )

    implicit_omissions = tuple(
        entry.source_unit_id
        for entry in adaptation.ledger
        if entry.reason == _MISSING_LEDGER_EXCEPTION
    )
    if implicit_omissions:
        failures.append(
            InvariantFailure(
                id="adapt_failure_missing_ledger_exceptions",
                owner_stage="adapt",
                code="missing_ledger_exception",
                message=(
                    "Every source unit absent from adapted beats requires an "
                    "explicit omission exception and reason."
                ),
                source_unit_ids=implicit_omissions,
                evidence=[
                    "No authored omission exception exists for: "
                    + ", ".join(implicit_omissions)
                ],
            )
        )

    for beat in adaptation.beats:
        cited = set(beat.source_unit_ids)
        cited.update(
            source_unit_id
            for item in beat.lettering
            for source_unit_id in item.source_unit_ids
        )
        unknown_provenance = sorted(cited - expected)
        if unknown_provenance:
            failures.append(
                InvariantFailure(
                    id=f"adapt_failure_unknown_source_provenance_{beat.id}",
                    owner_stage="adapt",
                    code="unknown_source_provenance",
                    message="Adapted-beat provenance must resolve in SourceDocument.",
                    source_unit_ids=unknown_provenance,
                    artifact_ids=[beat.id],
                    evidence=[
                        "Unknown source provenance: " + ", ".join(unknown_provenance)
                    ],
                )
            )

    lettering = [item for beat in adaptation.beats for item in beat.lettering]
    lettering_by_source: dict[str, list[LetteringItem]] = {}
    for item in lettering:
        for source_unit_id in item.source_unit_ids:
            lettering_by_source.setdefault(source_unit_id, []).append(item)

    if story_bible is not None:
        known_speakers = {character.id for character in story_bible.characters}
        for item in lettering:
            evidence = _lettering_contract_errors(
                item,
                known_speaker_ids=known_speakers,
            )
            if evidence:
                failures.append(
                    InvariantFailure(
                        id=f"adapt_failure_invalid_lettering_speaker_{item.id}",
                        owner_stage="adapt",
                        code="invalid_lettering_speaker",
                        message=(
                            "Canonical lettering must identify how and by whom "
                            "it is delivered."
                        ),
                        source_unit_ids=item.source_unit_ids,
                        artifact_ids=[item.id],
                        evidence=evidence,
                    )
                )

    expected_lettering_kind = {
        "dialogue": "dialogue",
        "thought": "thought",
        "caption": "caption",
    }
    for entry in adaptation.ledger:
        if entry.source_unit_id not in expected:
            continue
        expected_kind = expected_lettering_kind.get(entry.disposition)
        if expected_kind is None:
            continue
        realized = any(
            item.kind == expected_kind
            for item in lettering_by_source.get(entry.source_unit_id, ())
        )
        if not realized:
            failures.append(
                InvariantFailure(
                    id=(
                        "adapt_failure_source_disposition_not_realized_"
                        f"{entry.source_unit_id}"
                    ),
                    owner_stage="adapt",
                    code="source_disposition_not_realized",
                    message=(
                        "A source unit's ledger disposition must be realized by "
                        "source-linked canonical lettering."
                    ),
                    source_unit_ids=[entry.source_unit_id],
                    artifact_ids=[*entry.adapted_beat_ids],
                    evidence=[
                        f"Source unit {entry.source_unit_id!r} is marked "
                        f"{entry.disposition!r}, but no source-linked "
                        f"{expected_kind!r} LetteringItem exists."
                    ],
                )
            )

    # Both sides are model output: the Brief inferred the phrase, Adapt wrote the
    # balloon. They routinely disagree on quote style, dash form, and line
    # wrapping while carrying identical words, so compare under the shared
    # display-text policy instead of raw substring identity.
    complete_wording = tuple(_protected_language_key(item.text) for item in lettering)
    missing_protected = [
        phrase
        for phrase in brief.protected_language
        if not any(
            _protected_language_key(phrase) in wording for wording in complete_wording
        )
    ]
    if missing_protected:
        failures.append(
            InvariantFailure(
                id="adapt_failure_protected_language_missing",
                owner_stage="adapt",
                code="protected_language_missing",
                message="Protected language must survive verbatim in publishable wording.",
                evidence=[
                    "Missing exact protected phrase: " + repr(phrase)
                    for phrase in missing_protected
                ],
            )
        )

    # The approved Brief is the sole requirement text registry.
    registry = _requirement_registry(brief)
    covered_requirement_ids = {
        requirement_id
        for beat in adaptation.beats
        for requirement_id in beat.brief_requirement_ids
    }
    unknown_requirement_ids = covered_requirement_ids - set(registry)
    if unknown_requirement_ids:
        failures.append(InvariantFailure(
            id="adapt_failure_unknown_requirement", owner_stage="adapt", code="unknown_requirement",
            message="Requirement citations must resolve in the approved Brief registry.",
            artifact_ids=tuple(sorted(unknown_requirement_ids)),
            evidence=(f"Unknown requirement IDs: {sorted(unknown_requirement_ids)!r}",),
        ))
    for prefix, requirements, treatment_ids, code, label, story_function in (
        (
            "essential_event",
            brief.essential_events,
            adaptation.treatment.essential_event_ids,
            "missing_essential_event",
            "essential event",
            "causal_event",
        ),
        (
            "character_turn",
            brief.character_turns,
            adaptation.treatment.character_turn_ids,
            "missing_character_turn",
            "character turn",
            "character_turn",
        ),
    ):
        treated = set(treatment_ids)
        for index, requirement in enumerate(requirements, 1):
            requirement_id = f"{prefix}_{index:03d}"
            if requirement_id in treated and requirement_id in covered_requirement_ids:
                continue
            best_beat = _best_requirement_beat(
                adaptation,
                requirement=requirement,
                story_function=story_function,
            )
            failures.append(
                InvariantFailure(
                    id=f"adapt_failure_{code}_{requirement_id}",
                    owner_stage="adapt",
                    code=code,
                    message=f"Every approved {label} must be carried by a beat.",
                    source_unit_ids=best_beat.source_unit_ids if best_beat else (),
                    artifact_ids=[best_beat.id] if best_beat else (),
                    evidence=[
                        f"Uncovered approved {label} {requirement_id!r}: "
                        f"{registry[requirement_id]!r}"
                    ],
                )
            )

    for item in lettering:
        if item.kind == "sfx":
            continue
        text = item.text
        if _has_unbalanced_display_delimiters(text):
            failures.append(
                InvariantFailure(
                    id=f"adapt_failure_incomplete_display_text_{item.id}",
                    owner_stage="adapt",
                    code="incomplete_display_text",
                    message="Display text contains an unclosed quotation or delimiter.",
                    artifact_ids=[item.id],
                    evidence=[f"Incomplete display text: {text!r}"],
                )
            )
        if not _has_terminal_display_punctuation(text):
            failures.append(
                InvariantFailure(
                    id=f"adapt_failure_trailing_clipped_display_text_{item.id}",
                    owner_stage="adapt",
                    code="trailing_clipped_display_text",
                    message="Display text ends as if its final wording was clipped.",
                    artifact_ids=[item.id],
                    evidence=[f"Non-terminal display text: {text!r}"],
                )
            )

    appearance_states: dict[str, str] = {}
    continuity_states: dict[tuple[str, str], str] = {}
    for beat in adaptation.beats:
        if (
            beat.narrative_function == "transition"
            or "transition" in beat.story_functions
        ) and not beat.transitions:
            failures.append(
                InvariantFailure(
                    id=f"adapt_failure_incomplete_transition_{beat.id}",
                    owner_stage="adapt",
                    code="incomplete_transition",
                    message="A transition beat must state the continuity change.",
                    source_unit_ids=beat.source_unit_ids,
                    artifact_ids=[beat.id],
                    evidence=[
                        "The beat changes continuity but records no time, place, "
                        "knowledge, or emotional-state transition."
                    ],
                )
            )
        for change in beat.appearance_changes:
            previous = appearance_states.get(change.entity_id)
            if previous is not None and change.from_state_id != previous:
                failures.append(
                    InvariantFailure(
                        id=f"adapt_failure_appearance_state_chronology_{beat.id}",
                        owner_stage="adapt",
                        code="appearance_state_chronology",
                        message="An appearance-state change contradicts the prior beat.",
                        artifact_ids=[beat.id, change.entity_id],
                        evidence=[
                            f"Expected {change.entity_id!r} to change from "
                            f"{previous!r}; found {change.from_state_id!r}."
                        ],
                    )
                )
            appearance_states[change.entity_id] = change.to_state_id

        for transition in beat.transitions:
            state_key = (transition.dimension, transition.scope_id)
            previous = continuity_states.get(state_key)
            if previous is not None and transition.from_state != previous:
                issues.append(
                    EditorialIssue(
                        id=(
                            f"adapt_issue_transition_continuity_{beat.id}_"
                            f"{transition.dimension}"
                        ),
                        owner_stage="adapt",
                        code="continuity_state_mismatch",
                        message=(
                            "A scoped continuity transition may not begin from "
                            "the prior authored state."
                        ),
                        source_unit_ids=beat.source_unit_ids,
                        artifact_ids=[beat.id],
                        evidence=[
                            f"Within scope {transition.scope_id!r}, expected "
                            f"{transition.dimension!r} transition from {previous!r}; "
                            f"found {transition.from_state!r}."
                        ],
                    )
                )
            continuity_states[state_key] = transition.to_state

    issues.extend(_omission_issues(source, brief, adaptation))

    if brief.transformation_level == "faithful":
        entry_by_source = {entry.source_unit_id: entry for entry in adaptation.ledger}
        for scene in source.scenes:
            scene_units = tuple(scene.unit_ids(source))
            omitted = tuple(
                source_id
                for source_id in scene_units
                if entry_by_source.get(source_id) is not None
                and entry_by_source[source_id].disposition == "intentionally_omitted"
            )
            if (
                len(scene_units) >= 12
                and len(omitted) >= 12
                and len(omitted) * 5 >= len(scene_units) * 4
            ):
                failures.append(
                    InvariantFailure(
                        id=f"adapt_failure_faithful_source_scene_erased_{scene.id}",
                        owner_stage="adapt",
                        code="faithful_source_scene_erased",
                        message=(
                            "A faithful adaptation cannot erase nearly an entire "
                            "extracted source scene."
                        ),
                        source_unit_ids=omitted,
                        artifact_ids=[scene.id],
                        evidence=[
                            f"{len(omitted)} of {len(scene_units)} source units in "
                            f"{scene.id!r} ({scene.title}) were intentionally "
                            "omitted. Preserve its causal and reader-facing "
                            "function with adapted beats and complete lettering."
                        ],
                    )
                )

        silent_run: list[AdaptedBeat] = []
        for beat in (*adaptation.beats, None):
            if beat is not None and not beat.lettering:
                silent_run.append(beat)
                continue
            critical_functions = {
                function
                for candidate in silent_run
                for function in candidate.story_functions
            }.intersection({"causal_event", "reveal", "transition", "character_turn"})
            if len(silent_run) >= 3 and critical_functions:
                failures.append(
                    InvariantFailure(
                        id=(
                            "adapt_failure_reader_context_gap_"
                            f"{silent_run[0].id}_{silent_run[-1].id}"
                        ),
                        owner_stage="adapt",
                        code="reader_context_gap",
                        message=(
                            "A faithful adaptation cannot leave a sustained "
                            "reader-critical sequence entirely unlettered."
                        ),
                        source_unit_ids=tuple(
                            dict.fromkeys(
                                source_id
                                for candidate in silent_run
                                for source_id in candidate.source_unit_ids
                            )
                        ),
                        artifact_ids=[candidate.id for candidate in silent_run],
                        evidence=[
                            f"{len(silent_run)} consecutive beats carry "
                            f"{sorted(critical_functions)!r} but no publishable "
                            "lettering. Beat summaries are not reader-visible; "
                            "add the captions, testimony, dialogue, or transition "
                            "copy needed to follow the causal chain."
                        ],
                    )
                )
            silent_run = []

    for index, beat in enumerate(adaptation.beats):
        if "reveal" not in beat.story_functions:
            continue
        follow_through = [beat]
        for later in adaptation.beats[index + 1 :]:
            # A transition may also carry the reaction that closes the prior
            # sequence, so include it before treating it as the boundary.
            follow_through.append(later)
            if "transition" in later.story_functions:
                break
        carried_functions = {
            function
            for candidate in follow_through
            for function in candidate.story_functions
        }
        if carried_functions.isdisjoint({"reaction", "aftermath"}):
            evidence = [
                "The reveal sequence has no explicit reaction or "
                "aftermath beat before the next transition."
            ]
            issues.append(
                EditorialIssue(
                    id=f"adapt_issue_rushed_reaction_or_aftermath_{beat.id}",
                    owner_stage="adapt",
                    code="rushed_reaction_or_aftermath",
                    message="A reveal reaches the next transition without full follow-through.",
                    source_unit_ids=beat.source_unit_ids,
                    artifact_ids=[beat.id],
                    evidence=evidence,
                )
            )
            if brief.transformation_level == "faithful":
                failures.append(
                    InvariantFailure(
                        id=f"adapt_failure_faithful_rushed_reaction_or_aftermath_{beat.id}",
                        owner_stage="adapt",
                        code="faithful_rushed_reaction_or_aftermath",
                        message=(
                            "A faithful adaptation cannot move past a reveal "
                            "without explicit reaction or aftermath."
                        ),
                        source_unit_ids=beat.source_unit_ids,
                        artifact_ids=[beat.id],
                        evidence=evidence,
                    )
                )

    return AdaptationValidation(
        invariant_failures=failures,
        editorial_issues=issues,
    )


_OMITTED_RUN_THRESHOLD = 3


def _omission_issues(
    source: SourceDocument,
    brief: AdaptationBrief,
    adaptation: BookAdaptation,
) -> list[EditorialIssue]:
    """Surface omissions worth a human decision, not every omission.

    Flagging each intentionally omitted unit turns review-by-exception into a
    wall of noise on any real book: a faithful adaptation omits hundreds of
    units. What deserves the user's attention is an omission that drops
    protected language, or a long unbroken stretch of source that disappears.
    """

    ordinal_by_unit = {unit.id: unit.ordinal for unit in source.units}
    text_by_unit = {unit.id: unit.text for unit in source.units}
    omitted = sorted(
        (
            entry
            for entry in adaptation.ledger
            if entry.disposition == "intentionally_omitted"
            and entry.source_unit_id in ordinal_by_unit
        ),
        key=lambda entry: ordinal_by_unit[entry.source_unit_id],
    )
    issues: list[EditorialIssue] = []
    protected = [
        normalize_display_text(phrase)
        for phrase in brief.protected_language
        if phrase.strip()
    ]
    for entry in omitted:
        unit_text = normalize_display_text(text_by_unit[entry.source_unit_id])
        dropped = [phrase for phrase in protected if phrase in unit_text]
        if dropped:
            issues.append(
                EditorialIssue(
                    id=f"adapt_issue_omitted_protected_language_{entry.source_unit_id}",
                    owner_stage="adapt",
                    code="questionable_omission",
                    message="An omitted source unit carries protected language.",
                    source_unit_ids=[entry.source_unit_id],
                    evidence=[
                        "Protected phrase in the omitted unit: " + repr(dropped[0]),
                        entry.reason or "No omission reason was recorded.",
                    ],
                )
            )

    run: list[str] = []
    runs: list[list[str]] = []
    previous_ordinal: int | None = None
    for entry in omitted:
        ordinal = ordinal_by_unit[entry.source_unit_id]
        if previous_ordinal is not None and ordinal == previous_ordinal + 1:
            run.append(entry.source_unit_id)
        else:
            run = [entry.source_unit_id]
            runs.append(run)
        previous_ordinal = ordinal
    for stretch in runs:
        if len(stretch) < _OMITTED_RUN_THRESHOLD:
            continue
        issues.append(
            EditorialIssue(
                id=f"adapt_issue_questionable_omission_{stretch[0]}",
                owner_stage="adapt",
                code="questionable_omission",
                message="A continuous stretch of source is intentionally omitted.",
                source_unit_ids=stretch,
                evidence=[
                    f"{len(stretch)} consecutive source units were omitted, "
                    f"{stretch[0]} through {stretch[-1]}.",
                ],
            )
        )
    return issues


def _has_terminal_display_punctuation(text: str) -> bool:
    stripped = text.rstrip()
    while stripped and stripped[-1] in "\"'”’)]}":
        stripped = stripped[:-1].rstrip()
    return bool(stripped) and stripped[-1] in ".!?…—"


def _has_unbalanced_display_delimiters(text: str) -> bool:
    if text.count('"') % 2:
        return True
    return any(
        text.count(opening) != text.count(closing)
        for opening, closing in (
            ("“", "”"),
            ("(", ")"),
            ("[", "]"),
            ("{", "}"),
        )
    )
