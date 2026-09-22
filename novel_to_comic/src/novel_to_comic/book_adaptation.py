"""Book-level Adapt production for the full-page pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from copy import deepcopy
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from novel_to_comic.narrative_instructions import ADAPT_DEPICTION_GUIDANCE
from novel_to_comic.ai.context import ai_source_context, stream_observer
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
from novel_to_comic.narrative_review import (
    adaptation_context, require_narrative_review, review_narrative, reviewed_validation,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.paid_shards import run_paid_pipeline, run_paid_shards
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.text_utils import normalize_display_text
from novel_to_comic.usage import ApiResult, estimate_text_cost


_MAX_ADAPT_ATTEMPTS = 2
# A normal adaptation gets one bounded repair. Allow a final correction only
# when blocking codes decrease or a changed narrative-review finding appears.
# Repeated or newly introduced structural failures do not extend the loop.
_MAX_ADAPT_VALIDATION_ATTEMPTS = _MAX_ADAPT_ATTEMPTS + 1
_ADAPT_SHARD_MAX_UNITS = 180
_ADAPT_MAX_CONCURRENCY = 4
_ADAPT_OUTPUT_BUDGET_RATIO = 0.65
# Beats plus compact ledger exceptions are materially smaller than the source;
# the canonical per-unit ledger is expanded locally after generation.
_ADAPT_OUTPUT_TOKENS_PER_SOURCE_CHAR = 0.5
# A blueprint is structural JSON, not the final script.  Its output needs room
# for a large source shard, but leaving OpenRouter's 131k model ceiling in
# place lets mandatory low-effort GLM reasoning consume roughly 26k tokens
# before it starts the compact object.  That produced fragile 15-minute
# streams and repeated mid-stream disconnects.  This leaves ample room for
# the largest observed blueprint while bounding its reasoning stream.
_BLUEPRINT_MAX_OUTPUT_TOKENS = 24_000
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
            raise ValueError(
                f"{self.disposition} requires nonempty adapted_beat_ids containing "
                "exact existing beat IDs. A destination described only in reason "
                "or preserved_function (such as 'beat_030 onward') is not a citation."
            )
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


class _LetteringCopy(BaseModel):
    """Writer decisions only; identity is assigned after validating the response."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["dialogue", "thought", "caption", "sfx"]
    text: str = Field(min_length=1)
    speaker: str | None = None
    speaker_entity_id: str | None = None
    presentation: Literal["onscreen", "offscreen", "narration", "quoted_text", "display"]
    source_unit_ids: tuple[str, ...] = ()


class _BeatLetteringCopy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    beat_id: str = Field(min_length=1)
    lettering: tuple[_LetteringCopy, ...]


class _LetteringResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    beats: tuple[_BeatLetteringCopy, ...]


def _compile_locked_lettering(value: Mapping[str, Any], blueprint: _BlueprintDraft) -> _LetteringDraft:
    """Assign local IDs in locked beat order without altering any authored words."""
    response = _LetteringResponse.model_validate(value)
    by_id = {entry.beat_id: entry for entry in response.beats}
    if set(by_id) != {beat.id for beat in blueprint.beats} or len(by_id) != len(response.beats):
        raise ValueError("lettering must contain each locked blueprint beat exactly once")
    next_id = 1
    beats = []
    for beat in blueprint.beats:
        items = []
        for copy in by_id[beat.id].lettering:
            items.append(LetteringItem(
                **copy.model_dump(exclude={"presentation"}),
                id=f"lettering_{next_id:04d}", delivery=copy.presentation,
            ))
            next_id += 1
        beats.append(_BeatLettering(beat_id=beat.id, lettering=tuple(items)))
    return _LetteringDraft(beats=tuple(beats))


def _lettering_copy_view(draft: _LetteringDraft) -> dict[str, Any]:
    """Render canonical cached lettering as the current authoring contract."""
    return {"beats": [
        {"beat_id": beat.beat_id, "lettering": [
            {**item.model_dump(mode="json", exclude={"id", "delivery"}), "presentation": item.delivery}
            for item in beat.lettering
        ]} for beat in draft.beats
    ]}


def _ledger_response_schema(model_type: type[BaseModel]) -> dict[str, Any]:
    """Expose disposition-dependent accounting rules to the structured writer.

    Python model validators do not appear in generated JSON Schema. Closed
    object alternatives make their requirements explicit before generation.
    Destination existence still needs validation against the authored beats.
    """
    schema = model_type.model_json_schema()
    exception = schema.get("$defs", {}).get("_LedgerException")
    if exception is None:
        return schema
    variants = []
    for disposition in ("visual_motif", "compressed_into", "intentionally_omitted"):
        variant = deepcopy(exception)
        properties = variant["properties"]
        properties["disposition"] = {"type": "string", "enum": [disposition]}
        properties["adapted_beat_ids"] = {
            "type": "array", "items": {"type": "string", "minLength": 1},
            **({"maxItems": 0} if disposition == "intentionally_omitted" else {"minItems": 1}),
        }
        if disposition in {"compressed_into", "intentionally_omitted"}:
            properties["reason"] = {"type": "string", "minLength": 1}
        variant["required"] = list(properties)
        variants.append(variant)
    schema["$defs"]["_LedgerException"] = {"anyOf": variants}
    return schema


def _lettering_response_schema(
    model_type: type[BaseModel], known_speaker_ids: set[str],
    *, source_unit_ids: tuple[str, ...] | None = None,
) -> dict:
    """Constrain kind/delivery pairs at generation, retaining canonical validation.

    Full object alternatives use the strict providers' supported anyOf subset.
    Keep the persisted model unchanged so valid paid checkpoints remain reusable.
    """
    schema = _ledger_response_schema(model_type)
    item_name = "_LetteringCopy" if model_type is _LetteringResponse else "LetteringItem"
    presentation_field = "presentation" if model_type is _LetteringResponse else "delivery"
    item = schema["$defs"][item_name]
    variants = []
    speaker_id = {"anyOf": [
        *([{"type": "string", "enum": sorted(known_speaker_ids)}] if known_speaker_ids else []),
        {"type": "null"},
    ]}
    for kinds, deliveries in (
        (["dialogue", "thought"], ["onscreen"]),
        (["dialogue", "thought"], ["offscreen"]),
        (["caption"], ["narration", "quoted_text"]),
        (["sfx"], ["display"]),
    ):
        if deliveries == ["onscreen"] and not known_speaker_ids:
            continue
        variant = deepcopy(item)
        properties = variant["properties"]
        properties["kind"] = {"type": "string", "enum": kinds}
        properties[presentation_field] = {"type": "string", "enum": deliveries}
        properties["speaker_entity_id"] = deepcopy(speaker_id)
        if "dialogue" in kinds:
            properties["speaker"] = {"type": "string", "minLength": 1}
        if deliveries == ["onscreen"]:
            properties["speaker_entity_id"] = {"type": "string", "enum": sorted(known_speaker_ids)}
        variant["required"] = list(properties)
        variants.append(variant)
    schema["$defs"][item_name] = {"anyOf": variants}
    if source_unit_ids is not None:
        _constrain_source_schema(schema, source_unit_ids)
    return schema


def _constrain_source_schema(schema: dict, source_unit_ids: tuple[str, ...]) -> None:
    """Bound provenance in every authoring pass with one shared source-ID enum."""
    if not source_unit_ids:
        raise ValueError("Generation source scope must not be empty")
    schema.setdefault("$defs", {})["_ScopedSourceUnitId"] = {
        "type": "string", "enum": list(source_unit_ids),
    }

    def constrain_sources(node):
        if isinstance(node, dict):
            sources = node.get("properties", {}).get("source_unit_ids")
            if sources is not None:
                sources["items"] = {"$ref": "#/$defs/_ScopedSourceUnitId"}
            for child in node.values():
                constrain_sources(child)
        elif isinstance(node, list):
            for child in node:
                constrain_sources(child)

    constrain_sources(schema)


def _approved_appearance_states(story_bible: StoryBible) -> dict[str, tuple[str, ...]]:
    """Return the only visual-state IDs Adapt may activate for each entity.

    A base appearance deliberately has no state ID. Any named appearance
    change therefore needs a Story-owned state that Cast can either render as a
    distinct reference or explicitly mark canonical-equivalent.
    """

    return {
        entity.id: tuple(state.id for state in entity.appearance_states)
        for entity in (*story_bible.characters, *story_bible.locations, *story_bible.props)
    }


def _constrain_appearance_state_schema(schema: dict, story_bible: StoryBible) -> None:
    """Make invented appearance-state IDs impossible in Adapt JSON output."""

    state_ids_by_entity = _approved_appearance_states(story_bible)
    change_schema = schema.get("$defs", {}).get("AppearanceChange")
    if not isinstance(change_schema, dict):
        return
    variants: list[dict[str, Any]] = []
    for entity_id, state_ids in state_ids_by_entity.items():
        if not state_ids:
            continue
        variant = deepcopy(change_schema)
        properties = variant["properties"]
        properties["entity_id"] = {"type": "string", "enum": [entity_id]}
        properties["to_state_id"] = {"type": "string", "enum": list(state_ids)}
        properties["from_state_id"] = {
            "anyOf": [
                {"type": "null"},
                {"type": "string", "enum": list(state_ids)},
            ]
        }
        variants.append(variant)

    def constrain_changes(node: Any) -> None:
        if isinstance(node, dict):
            changes = node.get("properties", {}).get("appearance_changes")
            if isinstance(changes, dict):
                if variants:
                    changes["items"] = {"anyOf": deepcopy(variants)}
                else:
                    changes["maxItems"] = 0
            for child in node.values():
                constrain_changes(child)
        elif isinstance(node, list):
            for child in node:
                constrain_changes(child)

    constrain_changes(schema)


def _appearance_state_authority_failures(
    adaptation: BookAdaptation,
    story_bible: StoryBible,
) -> list[InvariantFailure]:
    """Report each missing visual authority once, at its owning Adapt beat."""

    approved = _approved_appearance_states(story_bible)
    failures: list[InvariantFailure] = []
    seen: set[tuple[str, str]] = set()
    for beat in adaptation.beats:
        for change in beat.appearance_changes:
            pair = (change.entity_id, change.to_state_id)
            if pair in seen or change.to_state_id in approved.get(change.entity_id, ()):
                continue
            seen.add(pair)
            failures.append(InvariantFailure(
                id=(
                    "adapt_failure_unapproved_appearance_state_"
                    f"{beat.id}_{change.to_state_id}"
                ),
                owner_stage="adapt",
                code="unapproved_appearance_state",
                message=(
                    "An appearance change must use a Story Bible state that Cast "
                    "can reference. Base appearances have no state ID."
                ),
                source_unit_ids=beat.source_unit_ids,
                artifact_ids=[beat.id, change.entity_id, change.to_state_id],
                evidence=[
                    f"Beat {beat.id!r} changes {change.entity_id!r} into "
                    f"{change.to_state_id!r}, but that entity's Story Bible "
                    "appearance_states does not declare it."
                ],
            ))
    return failures


class _AdaptCheckpoint(BaseModel):
    """Hash-keyed cache entry for one paid Adapt response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    input_sha256: str
    payload: dict[str, Any]


class _RepairBatchOutcome(BaseModel):
    """A completed validation pass, distinct from saved writer responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_sha256: str
    invariant_codes: tuple[str, ...]


class _PendingRepairBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    names: tuple[str, ...]
    prompts: tuple[str, ...]
    model: str


class _AdaptWorkCheckpoint(BaseModel):
    """Unpublished work bound to stage authorities, independent of the next model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: BookAdaptation
    shards: tuple[tuple[str, ...], ...]
    pending_repair: _PendingRepairBatch | None = None


def _repair_batch_receipt(names: list[str], prompts: list[str], model: str) -> tuple[str, str]:
    requests = [
        (name, _checkpoint_key(model=model, feature="adapt.book", prompt=prompt))
        for name, prompt in zip(names, prompts, strict=True)
    ]
    digest = hashlib.sha256(json.dumps(requests, separators=(",", ":")).encode()).hexdigest()
    return f"{names[0].rsplit('/', 1)[0]}/checked_{digest}", digest


def _record_repair_batch_outcome(artifacts, names, prompts, model, candidate, validation) -> None:
    name, key = _repair_batch_receipt(names, prompts, model)
    _write_checkpoint(
        artifacts, name=name, input_sha256=key,
        payload=_RepairBatchOutcome(candidate_sha256=candidate.content_sha256,
                                   invariant_codes=tuple(f.code for f in validation.invariant_failures)),
    )


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


def _repair_checkpoint_names(
    artifacts: TargetArtifacts, *, prompts: list[str], model: str,
    shard_indices: list[int], round_number: int, fresh_namespace: str,
) -> list[str]:
    """Reuse an interrupted batch, but never recycle a fully rejected repair.

    Every existing sibling must match the exact request. All responses may have
    arrived before an interruption in splicing or validation; only a recorded
    validation outcome makes a complete batch ineligible for reuse.
    """
    suffixes = [f"round_{round_number:02d}_shard_{index + 1:03d}" for index in shard_indices]
    keys = [_checkpoint_key(model=model, feature="adapt.book", prompt=p) for p in prompts]
    for namespace in artifacts.adapt_repair_namespaces():
        hits = 0
        mismatched = False
        for suffix, key in zip(suffixes, keys, strict=True):
            name = f"{namespace}/{suffix}"
            if not artifacts.adapt_checkpoint_path(name).exists():
                continue
            if _read_checkpoint(artifacts, name=name, input_sha256=key, model_type=_BookDraft) is None:
                mismatched = True
                break
            hits += 1
        if not mismatched and hits:
            names = [f"{namespace}/{suffix}" for suffix in suffixes]
            name, key = _repair_batch_receipt(names, prompts, model)
            checked = _read_checkpoint(
                artifacts, name=name, input_sha256=key, model_type=_RepairBatchOutcome,
            )
            if hits < len(prompts) or checked is None:
                return names
    return [f"{fresh_namespace}/{suffix}" for suffix in suffixes]


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
    *,
    story_bible: StoryBible | None = None,
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
                for beat in _canonicalize_reveal_responses(
                    _canonicalize_prior_states(beats)
                )
            ],
            "ledger": [entry.model_dump(mode="json") for entry in draft.ledger],
        }
    )
    return _materialize_protected_lettering(
        canonical, source, brief, story_bible=story_bible
    )


def _has_explicit_reveal_response(beat: AdaptedBeat) -> bool:
    """Whether this reveal already shows a source-backed response on the page."""
    return "character_turn" in beat.story_functions or any(
        item.kind == "thought"
        and item.speaker_entity_id in beat.entity_ids
        and bool(set(item.source_unit_ids).intersection(beat.source_unit_ids))
        for item in beat.lettering
    )


def _canonicalize_reveal_responses(beats: list[AdaptedBeat]) -> list[AdaptedBeat]:
    """Derive a reaction tag from an explicit reader-visible response.

    A structural label should not erase what the canonical script already
    proves. When a reveal includes either a declared character turn or an
    on-beat, source-cited thought by a visible participant, the reader has
    received the response before the transition. Canonicalizing that fact
    makes the invariant deterministic and gives Plan an honest story function.
    This deliberately does not infer a reaction from a neutral caption,
    summary, or an unrelated later beat.
    """
    canonical: list[AdaptedBeat] = []
    for beat in beats:
        functions = set(beat.story_functions)
        if (
            "reveal" in functions
            and not functions.intersection({"reaction", "aftermath"})
            and _has_explicit_reveal_response(beat)
        ):
            # Preserve the author's original ordering; only add the derived
            # structural truth that downstream validation and planning use.
            canonical.append(
                beat.model_copy(
                    update={"story_functions": (*beat.story_functions, "reaction")}
                )
            )
        else:
            canonical.append(beat)
    return canonical


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
    wording = re.sub(
        r"\s+/\s+",
        " ",
        normalize_display_text(text),
    )
    # Briefs frequently preserve dialogue with source quotation marks, while
    # a comic balloon correctly carries only the spoken words.  Those wrappers
    # are presentation, not protected wording; retain every interior character
    # (including Spanish opening/closing punctuation) for the verbatim check.
    return wording.strip().strip('"“”«»').strip()


def _contains_protected_language(text: str, phrase: str) -> bool:
    """Match wording, allowing only the initial case change of an excerpt.

    The Brief may capitalize a clause lifted from mid-sentence. Interior case,
    punctuation and words remain significant; neither authority is rewritten.
    """
    wording, excerpt = _protected_language_key(text), _protected_language_key(phrase)
    if not excerpt:
        return False
    initial = "(?:" + "|".join(re.escape(c) for c in {excerpt[0].lower(), excerpt[0].upper()}) + ")"
    return re.search(r"(?<!\w)" + initial + re.escape(excerpt[1:]) + r"(?!\w)", wording) is not None


def _protected_language_obligations(source, brief, source_ids):
    owned = set(source_ids)
    return [
        {"text": phrase, "source_unit_ids": matches}
        for phrase in brief.protected_language
        if (matches := [unit.id for unit in source.units if unit.id in owned
                        and _contains_protected_language(_protected_source_key(unit.text), phrase)])
    ]


def _quoted_source_wording(text: str) -> tuple[str, ...]:
    """Return publishable wording enclosed in straight or curly double quotes."""

    return tuple(
        wording
        for match in re.finditer(r'[“"]\s*(.+?)\s*[”"]', text, flags=re.DOTALL)
        if (wording := re.sub(r"\s+", " ", match.group(1)).strip())
    )


def _protected_source_key(text: str) -> str:
    """Compare source emphasis as presentation without changing source bytes."""
    # Only paired word-boundary emphasis, not arbitrary asterisks/underscores
    # (multiplication and identifiers remain literal source wording).
    text = re.sub(r"(?<![\w\\])(\*\*|__|\*|_)(?=\S)(.+?\S|\S)\1(?!\w)", r"\2", text)
    return _protected_language_key(text)


def _complete_source_quote_excerpt(item: LetteringItem, source_by_id) -> LetteringItem:
    """Close a sentence copied from inside a longer source quotation."""
    if (item.delivery != "quoted_text" or item.kind != "caption"
            or not _has_terminal_display_punctuation(item.text)
            or item.text.rstrip()[-1:] not in (".", "!", "?", "…", "—")
            or not any(source_id in source_by_id
                       and normalize_display_text(item.text) == normalize_display_text(source_by_id[source_id].text)
                       for source_id in item.source_unit_ids)):
        return item
    for opening, closing in (("“", "”"), ('"', '"')):
        unmatched = (item.text.count(opening) - item.text.count(closing)
                     if opening != closing else item.text.count(opening) % 2)
        if unmatched == 1 and not _has_unbalanced_display_delimiters(item.text + closing):
            return item.model_copy(update={"text": item.text + closing})
    return item


def _materialize_protected_lettering(
    candidate: BookAdaptation,
    source: SourceDocument,
    brief: AdaptationBrief,
    *,
    story_bible: StoryBible | None = None,
) -> BookAdaptation:
    """Realize protected wording and ledgered speech as canonical lettering."""

    # Earlier canonicalization inserted protected captions without delivery.
    # Recover only exact, source-backed quotations; never guess dialogue owners.
    protected = set(brief.protected_language)
    source_by_id = {unit.id: unit for unit in source.units}
    beats = [
        beat.model_copy(update={"lettering": tuple(
            item.model_copy(update={"delivery": "quoted_text"})
            if item.kind == "caption"
            and item.delivery is None
            and item.speaker is None
            and item.speaker_entity_id is None
            and item.text in protected
            and any(
                source_id in source_by_id
                and _contains_protected_language(
                    _protected_source_key(source_by_id[source_id].text), item.text
                )
                for source_id in item.source_unit_ids
            )
            else item
            for item in beat.lettering
        )})
        for beat in candidate.beats
    ]
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
        if any(_contains_protected_language(existing, phrase) for existing in existing_keys):
            continue
        source_unit = next(
            (
                unit
                for unit in source.units
                if _contains_protected_language(_protected_source_key(unit.text), phrase)
            ),
            None,
        )
        if source_unit is None:
            continue
        ledger_index = ledger_index_by_source.get(source_unit.id)
        entry = ledger[ledger_index] if ledger_index is not None else None
        # A protected, source-backed title has a deterministic home: the
        # opening beat. Do not infer placement for omitted narrative phrases.
        restore_title = (
            story_bible is not None
            and phrase == story_bible.title
            and entry is not None
            and entry.disposition == "intentionally_omitted"
            and not entry.adapted_beat_ids
            and bool(beats)
        )
        if restore_title:
            entry = entry.model_copy(update={
                "disposition": "caption",
                "adapted_beat_ids": (beats[0].id,),
                "reason": None,
            })
            ledger[ledger_index] = entry
            source_order = {unit.id: unit.ordinal for unit in source.units}
            beats[0] = beats[0].model_copy(update={
                "source_unit_ids": tuple(sorted(
                    set((*beats[0].source_unit_ids, source_unit.id)),
                    key=lambda source_id: source_order.get(source_id, len(source_order)),
                )),
            })
        if (
            entry is not None
            and entry.disposition not in kind_by_disposition
            and entry.adapted_beat_ids
        ):
            entry = entry.model_copy(update={"disposition": "caption", "reason": None})
            ledger[ledger_index] = entry
        kind = "caption" if entry and entry.disposition in kind_by_disposition else None
        if kind and entry.disposition != "caption":
            entry = entry.model_copy(update={"disposition": "caption", "reason": None})
            ledger[ledger_index] = entry
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
            delivery="quoted_text" if kind == "caption" else None,
            source_unit_ids=(source_unit.id,),
        )
        next_lettering_number += 1
        beat = beats[beat_index]
        beats[beat_index] = beat.model_copy(
            update={"lettering": (
                (lettering, *beat.lettering) if restore_title
                else (*beat.lettering, lettering)
            )}
        )
        existing_keys.add(phrase_key)

    realized_dispositions = {
        (source_unit_id, item.kind)
        for beat in beats
        for item in beat.lettering
        for source_unit_id in item.source_unit_ids
    }
    for ledger_index, entry in enumerate(ledger):
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
                    kind="caption",
                    delivery="quoted_text",
                    text=wording,
                    source_unit_ids=(entry.source_unit_id,),
                )
            )
            next_lettering_number += 1
        beats[beat_index] = beat.model_copy(
            update={"lettering": (*beat.lettering, *additions)}
        )
        ledger[ledger_index] = entry.model_copy(update={"disposition": "caption", "reason": None})
        realized_dispositions.add((entry.source_unit_id, "caption"))

    return BookAdaptation.model_validate(
        {
            **candidate.model_dump(mode="json"),
            "content_sha256": "",
            "beats": [beat.model_copy(update={"lettering": tuple(
                _complete_source_quote_excerpt(item, source_by_id) for item in beat.lettering
            )}).model_dump(mode="json") for beat in beats],
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
        "action_constraint_contract": (
            "Entity-scoped action constraints are verbatim source-established physical "
            "limits for the active appearance state. Respect them when authoring actions "
            "and state transitions; they are not instructions to redesign style or identity."
        ),
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
                        "action_constraint": state.continuity_guard or "",
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
                        "action_constraint": state.continuity_guard or "",
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
            "whole_scene_context": scene.summary,
            "scene_participant_entity_ids": scene.character_ids,
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
    """Compile the book-wide editorial treatment prompt from canonical inputs."""

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
        "Write a finished editorial story outline for the comic's creative team. "
        "Each field describes the fictional story: its events, character arcs, "
        "and presentation. Return the editorial deliverable only, without an "
        "account of your internal deliberations or hidden reasoning. "
        "Account for the causal spine, essential events, character turns, reveals, "
        "reactions, consequences, transitions, aftermath, motifs, narrator voice, "
        "and relative narrative emphasis. Carry every approved essential event and "
        "character turn from the brief into the matching treatment field using the "
        "brief's own wording. Copy the corresponding stable IDs from "
        "approved_requirement_registry into essential_event_ids and "
        "character_turn_ids. Use the approved target page range only "
        "to guide proportional selection. Do not allocate pages, panels, layouts, "
        "or geometry. Do not create parallel per-scene adaptations or reconciliation "
        "work. Use scene_obligations to preserve the source-supported causal "
        "function and relative weight of each scene. A scene participant need not "
        "speak. Distinguish an event's first mention, testimony or recollection, "
        "and its enacted occurrence; specify that presentation in the treatment "
        "so local authors do not dramatize it anew each time it is referenced. "
        "Return only the "
        "narrative-treatment JSON object. "
        + ADAPT_DEPICTION_GUIDANCE
        + "\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


_LEDGER_EXCEPTION_CONTRACT = (
    "Use beat source_unit_ids for directly represented source material; do not "
    "add redundant ledger exceptions for the same decision. For compressed_into "
    "and visual_motif, adapted_beat_ids must contain one or more exact destination "
    "IDs, for example [\"beat_030\",\"beat_031\"] if those beats exist. A range "
    "such as 'beat_030 onward' in reason or preserved_function does not populate "
    "adapted_beat_ids. For intentionally_omitted, adapted_beat_ids must be []. "
    "Compression and omission require a nonempty reason; preserved_function "
    "describes the function retained or deliberately removed. Never change the "
    "disposition merely to avoid specifying its destination or reason. "
)


_SCENE_SCOPE_CONTRACT = (
    "The book_scene_outline is read-only chronology and scene context, not additional "
    "source to adapt. source_scenes identifies whether this scope contains a complete "
    "scene or only its opening, middle, or closing. Scene summaries and participants "
    "describe the whole scene: realize only the facts supported by supplied source "
    "units, never repeat the whole scene in each fragment. Participants need not "
    "speak. Preserve the source's framing of testimony, documents, recollections, "
    "and present action; mention of an event is not a second enactment of it. If "
    "visualizing a recollection, make its entry and return clear to the reader. "
    "Carry consequential reactions and causal links where supported, but do not "
    "invent a separate reaction, ominous pause, or recap for every fact or fragment. "
)


_DISPLAY_EXCERPT_CONTRACT = (
    "Source units are sentence slices, not quotation boundaries. A quotation can "
    "continue across several units. Make each display item a complete excerpt "
    "with balanced quotation marks; do not copy an opening quote without closing "
    "it. Source Markdown emphasis is formatting, not part of the protected words. "
)


def _scoped_source_scenes(
    source: SourceDocument, primary_ids: set[str],
) -> list[dict[str, Any]]:
    scenes = []
    for scene in source.scenes:
        all_ids = scene.unit_ids(source)
        supplied = [unit_id for unit_id in all_ids if unit_id in primary_ids]
        if not supplied:
            continue
        opens = supplied[0] == all_ids[0]
        closes = supplied[-1] == all_ids[-1]
        scenes.append({
            "id": scene.id, "title": scene.title,
            "first_unit_id": supplied[0], "last_unit_id": supplied[-1],
            "full_scene_first_unit_id": all_ids[0],
            "full_scene_last_unit_id": all_ids[-1],
            "scope": ("complete" if opens and closes else
                      "opening" if opens else "closing" if closes else "middle"),
        })
    return scenes


def _book_scene_outline(source: SourceDocument, story_bible: StoryBible) -> list[dict[str, Any]]:
    summaries = {scene.id: scene.summary for scene in story_bible.scenes}
    return [
        {"id": scene.id, "title": scene.title, "summary": summaries.get(scene.id, ""),
         "first_unit_id": scene.first_unit_id, "last_unit_id": scene.last_unit_id}
        for scene in source.scenes
    ]


_PROTECTED_LANGUAGE_GUIDANCE = (
    "protected_language_obligations locates protected wording in this source scope. "
    "Keep a source-backed beat for each obligation and realize its wording in "
    "the final lettering, with its source citation. Do not omit it or replace "
    "it with a summary. Initial excerpt capitalization may differ from the "
    "source; preserve all words and interior capitalization. "
)


_NARRATION_THOUGHT_GUIDANCE = (
    "Classify caption versus thought by the source's narrative role and surrounding "
    "context, not grammatical person. First-person pronouns (I, me, my, we), "
    "present tense, emotional language, and an identifiable narrator are not "
    "evidence of a thought. First-person storytelling, recollection, exposition, "
    "and commentary addressed to the reader remain kind='caption' with narration "
    "presentation/delivery, even when the narrator is visible in the scene. "
    "Third-person narration about feelings also remains a caption. Use kind='thought' "
    "only when the source context establishes a specific character's unspoken, "
    "in-the-moment inner words (for example, explicit thinking attribution or "
    "clearly established interior monologue), with an identified thinker. "
    "An identified speaker alone is insufficient. 'I felt warm that summer' in "
    "a narrator's recollection is a caption; 'I feel warm' in ongoing first-person "
    "narration is also a caption; 'I must hide, she thought as the door opened' "
    "supports the thought 'I must hide.' Thoughts need not contain 'I'. "
    "When ambiguous, preserve narration as a caption. Do not rewrite narration "
    "into first person to justify a thought bubble. "
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
    source_scenes = _scoped_source_scenes(source, primary_id_set)
    scene_ids = {scene["id"] for scene in source_scenes}
    context = {
        "adaptation_scope": {
            "shard_index": shard_index,
            "shard_count": shard_count,
            "primary_source_unit_ids": primary_ids,
        },
        "source_units": source_units,
        "source_scenes": source_scenes,
        "book_scene_outline": _book_scene_outline(source, story_bible),
        "story_bible": _story_bible_view(story_bible, scene_ids=scene_ids),
        "scene_obligations": _scene_obligations(
            story_bible,
            scene_ids=scene_ids,
        ),
        "approved_adaptation_brief": _brief_view(brief),
        "protected_language_obligations": _protected_language_obligations(source, brief, primary_ids),
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
            "for adaptation_scope.primary_source_unit_ids, in authored reading order. "
            "Do not account for source units outside this shard. Beat, lettering, "
            "and order identifiers may be shard-local; the deterministic merge "
            "rebases them into one global sequence. The shard is a transport "
            "boundary, never an independently authoritative adaptation. "
        )
    ownership_instruction = ""
    if owned_requirement_ids is not None:
        # Without this the shard sees all nine approved requirements and has to
        # infer which fall in its own source range.
        ownership_instruction = (
            "adaptation_scope.owned_requirement_ids lists the approved "
            "requirements whose content falls in this shard's source range; "
            "carry each one onto the beat that realizes it. Requirements outside "
            "that list may belong to retained beats or other source ranges — carry one only if this shard's "
            "own source plainly realizes it. "
        )
    faithful_instruction = ""
    if brief.transformation_level == "faithful":
        faithful_instruction = (
            "This is a faithful adaptation. Treat narrative completeness as a "
            "blocking requirement: preserve source-supported consequences and reactions "
            "before the next transition. Do not compress a "
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
        + _NARRATION_THOUGHT_GUIDANCE
        + "Cite source-unit provenance. Do not restate the full source ledger: code "
        "derives depicted, dialogue, thought, and caption dispositions from beats "
        "and lettering. Author ledger_exceptions only for "
        "visual_motif, compressed_into, or intentionally_omitted source units. Group "
        "every contiguous run that shares a disposition and destination into one "
        "exception with one concise reason; never emit repetitive per-unit "
        "exceptions for the same decision. Compression "
        "requires a reason and an existing adapted-beat destination. Intentional "
        "omission requires a reason, the function intentionally removed, and no "
        "adapted-beat destination. Every source unit not cited by a beat requires "
        "an explicit exception. Use scene_obligations for source-supported completeness "
        "and proportional weight within the supplied scope. Use the target "
        "page range only for proportional "
        "selection. Do not allocate pages, panels, layouts, or geometry. Do not "
        "create scene-parallel screenplays or reconciliation work. Return one JSON "
        "object containing only beats and ledger_exceptions. "
        + _LEDGER_EXCEPTION_CONTRACT
        + _PROTECTED_LANGUAGE_GUIDANCE
        + _SCENE_SCOPE_CONTRACT
        + ADAPT_DEPICTION_GUIDANCE
        + "\n"
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
    source_scenes = _scoped_source_scenes(source, primary_id_set)
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
        "book_scene_outline": _book_scene_outline(source, story_bible),
        "story_bible": _story_bible_view(story_bible, scene_ids=scene_ids),
        "scene_obligations": _scene_obligations(story_bible, scene_ids=scene_ids),
        "approved_adaptation_brief": _brief_view(brief),
        "protected_language_obligations": _protected_language_obligations(source, brief, primary_source_unit_ids),
        "approved_requirement_registry": _requirement_registry(brief),
        "narrative_treatment": _treatment_view(treatment),
    }
    faithful = (
        "For this faithful adaptation, preserve every causal step and each "
        "source-supported consequence or reaction before a transition. For every "
        "beat tagged reveal, before its next transition tag reaction or aftermath "
        "on the source-backed response beat; if the reveal itself contains the "
        "character's realization, tag that same beat reaction as well as reveal. "
        "Do not invent a response solely to satisfy the tag. "
        if brief.transformation_level == "faithful"
        else ""
    )
    return (
        f"Design locked story structure for internal shard {shard_index} of "
        f"{shard_count}. {faithful}"
        "Page-count targets are advisory and never dictate beat count. Do not preview "
        "a later event as if it has already happened, then stage it again. At shard "
        "boundaries distinguish mentions, documents, recollections, and lived events. "
        "Assume a reader has never read the novel. Create one drawable beat per "
        "story moment and make chronology, evidence, motives, deductions, reactions, "
        "consequences, and aftermath explicit in the beat sequence. Preserve the "
        "relative weight in scene_obligations. Carry every owned requirement onto "
        "the beat that realizes it by copying its exact registry key into that "
        "beat's brief_requirement_ids array. Across all beats, cite every ID in "
        "adaptation_scope.owned_requirement_ids at least once; requirement text "
        "in a summary does not substitute for its ID. Include brief_requirement_ids "
        "and transitions on every beat, using [] only when none apply. "
        "Every beat whose narrative_function or story_functions includes transition "
        "must have a nonempty transitions array. Each transition contains dimension "
        "(time, place, knowledge, or emotional_state), scope_id (a stable entity "
        "or narrative-thread ID), from_state, to_state, and description; from_state "
        "and to_state must differ and describe a source-supported change. "
        "Record an appearance change only when the Story Bible declares its "
        "entity-scoped state ID. Base appearances have no state ID: do not turn "
        "an ordinary description, first sighting, or default outfit into a named "
        "appearance change. "
        "Do not write dialogue, captions, thoughts, SFX, "
        "pages, panels, or layouts: another locked expansion pass writes the final "
        "words without changing this structure. Do not return a canonical ledger. "
        "Code derives ordinary source accounting from beat provenance. Use "
        "ledger_exceptions only for visual_motif, compressed_into, or "
        "intentionally_omitted units; every uncited source unit requires an explicit "
        "exception with a reason; omission also names the function removed, and "
        "compression cites an existing beat destination. Return only beats and ledger_exceptions. "
        "Every exception destination must be a beat ID present in this response, "
        "never a future shard or an unspecified range. "
        + _LEDGER_EXCEPTION_CONTRACT
        + _PROTECTED_LANGUAGE_GUIDANCE
        + _SCENE_SCOPE_CONTRACT
        + ADAPT_DEPICTION_GUIDANCE
        + "\n"
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
    blueprint: _BlueprintDraft | None,
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
        "source_scenes": _scoped_source_scenes(source, set(primary_source_unit_ids)),
        "book_scene_outline": _book_scene_outline(source, story_bible),
        "story_bible": _story_bible_view(story_bible, scene_ids=scene_ids),
        "approved_adaptation_brief": _brief_view(brief),
        "protected_language_obligations": _protected_language_obligations(source, brief, primary_source_unit_ids),
        "narrative_treatment": _treatment_view(treatment),
        "locked_blueprint": (blueprint.model_dump(mode="json") if blueprint is not None
                             else {"estimate_only": "Blueprint not generated yet."}),
    }
    return (
        "Write complete publishable lettering for the locked blueprint. Return "
        "exactly one entry for every blueprint beat_id, in order; an entry may have "
        "empty lettering only when the beat is visually self-explanatory. Do not "
        "add, remove, reorder, summarize, merge, or redesign beats. Every causal "
        "link, motive, chronology change, deduction, testimony, and relationship "
        "between evidence that a still image cannot establish must appear in "
        "dialogue, thought, or caption. Preserve protected language verbatim. "
        "The application assigns lettering IDs; do not supply id fields. For every lettering item cite source_unit_ids and set presentation. On-screen "
        "dialogue/thought requires speaker (the precise character name) and "
        "speaker_entity_id (that character's exact Story Bible ID). Include "
        "kind, text, speaker, speaker_entity_id, presentation, and source_unit_ids on every item, using null for "
        "speaker fields only when no character speaks. "
        + _NARRATION_THOUGHT_GUIDANCE
        + "presentation specifies how the words appear on the page, never tone or acting "
        "direction. Values such as 'listless', 'quiet, sincere', or 'whisper' are invalid. "
        "Use exactly onscreen, offscreen, narration, quoted_text, or display. "
        "off-panel voices use offscreen; narration uses narration; quoted prose, "
        "inscriptions, and manuscript excerpts use caption/quoted_text; SFX uses "
        "display. Never combine two speakers in one item. Return only beat_id and "
        "lettering; the application owns all structural fields and the ledger. "
        "All lettering source citations must belong to the supplied source_units; "
        "the treatment and scene summaries supply context, not extra source authority. "
        + _PROTECTED_LANGUAGE_GUIDANCE
        + _SCENE_SCOPE_CONTRACT
        + ADAPT_DEPICTION_GUIDANCE
        + "\n"
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
        scene_ids = scene.unit_ids(source)
        scene_chars = sum(len(unit_by_id[source_id].text) for source_id in scene_ids)
        # A scene that fits one request should not straddle independent authors.
        if current and (
            len(current) + len(scene_ids) > _ADAPT_SHARD_MAX_UNITS
            or current_chars + scene_chars > source_char_budget
        ):
            shards.append(tuple(current))
            current = []
            current_chars = 0
        for source_id in scene_ids:
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
    artifacts: TargetArtifacts | None = None,
) -> float:
    """Estimate remaining clean work, two potential repair scenarios and re-review.

    Known matching checkpoints cost nothing. Unknown output lengths remain
    projections; this quote is not a spend ceiling. In particular a semantic
    repair writes complete scoped drafts, not 25% of the original work.
    """
    published = _published_adaptation_for_review(artifacts, story_instruction)
    if published is not None:
        from novel_to_comic.narrative_review import estimate_narrative_review

        context = adaptation_context(source, brief, published)
        try:
            require_narrative_review(artifacts, "adapt", context)
        except ValueError:
            return estimate_narrative_review(model, context, passes=1)
        return 0.0
    resume_work = (_resume_adaptation_work(
        source, story_bible, brief, artifacts=artifacts, model=model, instruction=story_instruction,
    ) if artifacts is not None else None)
    instruction_suffix = story_instruction_section(story_instruction, stage="adapt")
    treatment_prompt = build_narrative_treatment_prompt(source, story_bible, brief) + instruction_suffix
    cached_treatment = None
    if artifacts is not None:
        cached_treatment = _read_checkpoint(
            artifacts, name="treatment", model_type=NarrativeTreatment,
            input_sha256=_checkpoint_key(model=model, feature="adapt.narrative_treatment", prompt=treatment_prompt),
        )
    treatment = (resume_work.candidate.treatment if resume_work else cached_treatment) or treatment or NarrativeTreatment(
        causal_spine=("Pending book-level treatment.",),
        essential_events=brief.essential_events, character_turns=brief.character_turns,
    )
    clean = (0.0 if resume_work is not None or cached_treatment is not None else estimate_text_cost(
        model, treatment_prompt, output_chars=max(12_000, len(source.text)),
    ))
    repair = 0.0
    shards = resume_work.shards if resume_work else _adaptation_shards(source, model=model)
    requirements = partition_requirements_by_shard(source, brief, shards)
    unit_by_id = {u.id: u for u in source.units}
    speakers = {c.id for c in story_bible.characters}
    for index, ids in enumerate(shards):
        projected_chars = _shard_output_chars(unit_by_id, ids)
        if resume_work is None:
            blueprint_prompt = build_adaptation_blueprint_prompt(
                source, story_bible, brief, treatment, primary_source_unit_ids=ids,
                owned_requirement_ids=requirements[index], shard_index=index + 1, shard_count=len(shards),
            ) + instruction_suffix
            blueprint_chars = max(4_000, int(projected_chars * 0.55))
            lettering_chars = max(3_000, int(projected_chars * 0.45))
            blueprint = None
            if artifacts is not None:
                blueprint = _read_checkpoint(
                    artifacts, name=f"blueprint/shard_{index + 1:03d}", model_type=_BlueprintDraft,
                    input_sha256=_checkpoint_key(model=model, feature="adapt.blueprint", prompt=blueprint_prompt),
                )
                if blueprint is not None:
                    try:
                        _validate_blueprint_scope(blueprint, source_unit_ids=ids, owned_requirement_ids=requirements[index])
                    except ValueError:
                        blueprint = None
            if blueprint is None:
                clean += estimate_text_cost(model, blueprint_prompt, output_chars=blueprint_chars)
            # Use the actual lettering contract. With no blueprint yet, separately
            # price its projected input size instead of pretending this is a second
            # blueprint request. The missing structure is explicitly marked as an estimate.
            lettering_prompt = build_locked_lettering_prompt(
                source, story_bible, brief, treatment, blueprint,
                primary_source_unit_ids=ids, shard_index=index + 1, shard_count=len(shards),
            ) + instruction_suffix
            cached_lettering = None
            if artifacts is not None and blueprint is not None:
                cached_lettering = _read_checkpoint(
                    artifacts, name=f"lettering/shard_{index + 1:03d}", model_type=_LetteringDraft,
                    input_sha256=_checkpoint_key(model=model, feature="adapt.lettering", prompt=lettering_prompt),
                )
                if cached_lettering is not None:
                    try:
                        _validate_locked_lettering(cached_lettering, known_speaker_ids=speakers)
                        _apply_locked_lettering(blueprint, cached_lettering)
                    except ValueError:
                        cached_lettering = None
            if cached_lettering is None:
                clean += estimate_text_cost(model, lettering_prompt, output_chars=lettering_chars)
                if blueprint is None:
                    clean += estimate_text_cost(model, blueprint_chars)
        repair_prompt = build_book_adaptation_prompt(
            source, story_bible, brief, treatment, primary_source_unit_ids=ids,
            owned_requirement_ids=requirements[index], shard_index=index + 1, shard_count=len(shards),
        ) + instruction_suffix
        # A normal validation failure gets one repair. A repaired draft can
        # expose a distinct, evidence-backed narrative fault during review, so
        # include the one additional bounded narrative correction too.
        repair += _MAX_ADAPT_ATTEMPTS * estimate_text_cost(
            model, repair_prompt, output_chars=projected_chars,
        )
        repair += _MAX_ADAPT_ATTEMPTS * estimate_text_cost(
            model, projected_chars,  # previous scoped draft in repair input
        )

    from novel_to_comic.narrative_review import estimate_narrative_review
    candidate = resume_work.candidate if resume_work else None
    if candidate is None and artifacts is not None and artifacts.failed_adaptation_candidate_path.exists():
        candidate = artifacts.read_failed_adaptation_candidate()
    if (candidate is not None and candidate.source_sha256 == source.source_sha256
            and candidate.brief_sha256 == brief.content_sha256):
        review = estimate_narrative_review(model, {
            **adaptation_context(source, brief, candidate), "approved_story_instruction": story_instruction,
        }, passes=_MAX_ADAPT_VALIDATION_ATTEMPTS)
    else:
        # Unknown candidate: each future source window carries global treatment,
        # source evidence and projected beat context. Two reviews, including the
        # repaired candidate, plus the narrowly permitted final narrative
        # correction, are an explicit scenario rather than a percentage.
        review = estimate_text_cost(
            model, source.text + brief.model_dump_json() + treatment.model_dump_json(),
            output_chars=5_000,
        ) * 2 * _adapt_review_window_count(source) * _MAX_ADAPT_VALIDATION_ATTEMPTS
    return clean + repair + review


def _adapt_review_window_count(source: SourceDocument) -> int:
    windows, size = 1, 0
    for unit in source.units:
        if size and size + len(unit.text) > 24000:
            windows += 1
            size = 0
        size += len(unit.text)
    return windows


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
    require_reveal_follow_through: bool = False,
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
    rushed_reveals = []
    if require_reveal_follow_through:
        for index, beat in enumerate(blueprint.beats):
            if "reveal" not in beat.story_functions:
                continue
            follow_through = [beat]
            for later in blueprint.beats[index + 1 :]:
                follow_through.append(later)
                if "transition" in later.story_functions:
                    break
            # At an open shard boundary the response may legitimately be in
            # the next shard; only reject a sequence that has already reached
            # its own transition without a labeled response.
            reaches_transition = any(
                "transition" in candidate.story_functions
                for candidate in follow_through
            )
            carried = {
                function
                for candidate in follow_through
                for function in candidate.story_functions
            }
            if reaches_transition and carried.isdisjoint({"reaction", "aftermath"}):
                rushed_reveals.append(beat.id)
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
    if rushed_reveals:
        errors.append(
            "faithful reveal(s) need reaction or aftermath before their next "
            f"transition: {rushed_reveals}"
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
    story_bible: StoryBible | None = None,
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
    if isinstance(cached, _BlueprintDraft):
        try:
            _validate_blueprint_scope(
                cached,
                source_unit_ids=source_unit_ids,
                owned_requirement_ids=owned_requirement_ids,
                require_reveal_follow_through=(brief.transformation_level == "faithful"),
            )
            return cached
        except ValueError as error:
            # A validator added after the checkpoint was written can cheaply
            # repair the compact cached structure instead of discarding every
            # paid stage result or crashing before a model call.
            attempt_prompt = _schema_repair_prompt(
                prompt,
                cached.model_dump(mode="json"),
                error,
            )
    response_schema = _ledger_response_schema(_BlueprintDraft)
    _constrain_source_schema(response_schema, source_unit_ids)
    if story_bible is not None:
        _constrain_appearance_state_schema(response_schema, story_bible)
    # Require an explicit model decision for fields with semantic coverage rules.
    # Empty arrays remain valid for individual beats; scope validation below
    # still enforces complete requirement coverage and transition detail.
    response_schema["$defs"]["_BlueprintBeat"]["required"].extend(
        ["brief_requirement_ids", "transitions"]
    )
    for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
        result = await generate(
            system_prompt=(
                "You are the structural architect for a graphic novel. Return "
                "compact locked story structure, not prose."
            ),
            user_content=attempt_prompt,
            feature="adapt.blueprint",
            max_output_tokens=_BLUEPRINT_MAX_OUTPUT_TOKENS,
            json_schema=response_schema,
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
                require_reveal_follow_through=(brief.transformation_level == "faithful"),
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
    source_scope = tuple(dict.fromkeys(
        source_id
        for entry in (*blueprint.beats, *blueprint.ledger_exceptions)
        for source_id in entry.source_unit_ids
    ))
    key = _checkpoint_key(model=model, feature="adapt.lettering", prompt=prompt)
    cached = _read_checkpoint(
        artifacts,
        name=checkpoint_name,
        input_sha256=key,
        model_type=_LetteringDraft,
    )
    if cached is None:
        cached = _read_checkpoint(
            artifacts, name=f"{checkpoint_name}/rejected", input_sha256=key,
            model_type=_LetteringDraft,
        )
    attempt_prompt = prompt
    if isinstance(cached, _LetteringDraft):
        try:
            _validate_locked_lettering(
                cached,
                known_speaker_ids=known_speaker_ids,
            )
            draft = _apply_locked_lettering(blueprint, cached)
            _validate_draft_source_scope(draft, source_scope)
            return draft
        except ValueError as error:
            attempt_prompt = _schema_repair_prompt(
                prompt,
                _lettering_copy_view(cached),
                error,
            )
    response_schema = _lettering_response_schema(
        _LetteringResponse, known_speaker_ids, source_unit_ids=source_scope,
    )
    for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
        result = await generate(
            system_prompt=(
                "You are the dialogue and caption writer for a locked graphic-"
                "novel blueprint. You may write words but not redesign the story. "
                "When repairing a response, change only invalid fields. Preserve "
                "all unaffected wording, beat IDs, speaker "
                "assignments, and source citations exactly as supplied."
            ),
            user_content=attempt_prompt,
            feature="adapt.lettering",
            json_schema=response_schema,
        )
        _record_result_usage(ctx, result)
        lettering = None
        try:
            lettering = _compile_locked_lettering(result.value, blueprint)
            _validate_locked_lettering(
                lettering,
                known_speaker_ids=known_speaker_ids,
            )
            draft = _apply_locked_lettering(blueprint, lettering)
            _validate_draft_source_scope(draft, source_scope)
        except (ValidationError, ValueError) as error:
            if lettering is not None:
                _write_checkpoint(
                    artifacts, name=f"{checkpoint_name}/rejected",
                    input_sha256=key, payload=lettering,
                )
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
        artifacts.adapt_checkpoint_path(f"{checkpoint_name}/rejected").unlink(missing_ok=True)
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
    source_unit_ids: tuple[str, ...] | None = None,
    required_requirement_ids: tuple[str, ...] = (),
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
                if source_unit_ids is not None:
                    _validate_draft_source_scope(cached, source_unit_ids)
                _validate_repair_requirements(cached, required_requirement_ids)
                return cached
            except ValueError as error:
                attempt_prompt = _schema_repair_prompt(
                    prompt,
                    cached.model_dump(mode="json"),
                    error,
                )

    response_schema = _lettering_response_schema(
        _BookDraft, known_speaker_ids, source_unit_ids=source_unit_ids,
    )
    response_schema["properties"].pop("ledger", None)
    for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
        result = await generate(
            system_prompt=(
                "You are the sole book-level Adapt writer. Return complete JSON."
            ),
            user_content=attempt_prompt,
            feature="adapt.book",
            json_schema=response_schema,
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
            if source_unit_ids is not None:
                _validate_draft_source_scope(draft, source_unit_ids)
            _validate_repair_requirements(draft, required_requirement_ids)
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
    source_scopes: list[tuple[str, ...]] | None = None,
    required_requirements: list[tuple[str, ...]] | None = None,
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
        with ai_source_context(
            checkpoint_names[index] if checkpoint_names else f"repair/shard_{index + 1:03d}",
            source_scopes[index] if source_scopes else (),
        ), stream_observer(lambda chars: report(index, chars)):
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
                source_unit_ids=source_scopes[index] if source_scopes is not None else None,
                required_requirement_ids=required_requirements[index] if required_requirements is not None else (),
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

    external_maps: dict[str, list[str]] = {}
    ordinal = 0
    for part in drafts:
        for beat in part.beats:
            ordinal += 1
            external_maps.setdefault(beat.id, []).append(f"beat_{ordinal:04d}")

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
                                external_maps[beat_id][0]
                                if entry.disposition == "compressed_into" and len(external_maps.get(beat_id, [])) == 1
                                else f"invalid_shard_{shard_index}_{beat_id}",
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


def _closed_repair_scope(
    draft: _BookDraft, source_unit_ids: tuple[str, ...],
    owned_source_unit_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Close a replacement over complete beats and their literal source claims.

    Scene boundaries and beat boundaries need not coincide. Replacing any part
    of a beat removes all of its lettering, so all of that evidence must be in
    the writer's scope too. Repeat for overlapping beats until stable.
    External compression links remain redirectable without rewriting their source.
    """
    wanted = set(source_unit_ids)
    while True:
        touched = [b for b in draft.beats if wanted.intersection(b.source_unit_ids)]
        # A replacement occupies one contiguous interval in authored beat
        # order. Close over intervening beats too; source citation order is not
        # narrative order (a flashback may cite an earlier summary sentence).
        positions = [i for i, b in enumerate(draft.beats) if b in touched]
        if positions:
            touched = list(draft.beats[min(positions):max(positions) + 1])
        touched_ids = {b.id for b in touched}
        expanded = wanted | {
            source_id for beat in touched for source_id in beat.source_unit_ids
        } | {
            source_id for beat in touched for item in beat.lettering
            for source_id in item.source_unit_ids
        } | {
            entry.source_unit_id for entry in draft.ledger
            if entry.disposition in {"depicted", "dialogue", "thought", "caption"}
            and touched_ids.intersection(entry.adapted_beat_ids)
        }
        if expanded == wanted:
            break
        wanted = expanded
    unknown = wanted - set(owned_source_unit_ids)
    if unknown:
        raise ValueError(f"Repair scope crosses unowned source units: {sorted(unknown)}")
    return tuple(source_id for source_id in owned_source_unit_ids if source_id in wanted)


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
                    )
                }
            )
            for entry in draft.ledger
        ),
    )


def _splice_draft_repair(
    draft: _BookDraft, repair: _BookDraft, source_unit_ids: tuple[str, ...],
    source_order: Mapping[str, int],
) -> _BookDraft:
    return _splice_draft_repairs(draft, [(repair, source_unit_ids)], source_order)


def _validate_draft_source_scope(draft: _BookDraft, source_unit_ids: tuple[str, ...]) -> None:
    """Reject copied neighbor citations before caching or splicing a repair.

    Compression may point to an external beat, but its source citation still
    belongs to this repair. Never erase or relabel an out-of-scope citation.
    """
    allowed = set(source_unit_ids)
    claims = [(f"beat {beat.id}", beat.source_unit_ids) for beat in draft.beats]
    claims.extend((f"lettering {item.id}", item.source_unit_ids)
                  for beat in draft.beats for item in beat.lettering)
    claims.extend((f"ledger exception {index}", entry.source_unit_ids)
                  for index, entry in enumerate(draft.ledger_exceptions, 1))
    errors = [f"{owner}: {sorted(set(citations) - allowed)}"
              for owner, citations in claims if set(citations) - allowed]
    if errors:
        raise ValueError("Repair contains out-of-scope literal provenance: " + "; ".join(errors))
    accounted = {source_id for _, citations in claims for source_id in citations}
    accounted.update(entry.source_unit_id for entry in draft.ledger
                     if entry.reason != _MISSING_LEDGER_EXCEPTION)
    missing = allowed - accounted
    if missing:
        raise ValueError(
            f"Repair is missing source accounting for {sorted(missing)}. "
            "Preserve the source in a beat or author an explicit ledger exception with a reason."
        )


def _repair_required_requirements(candidate: BookAdaptation, scope: tuple[str, ...]) -> tuple[str, ...]:
    """Retain requirement ownership that would otherwise disappear in a splice."""
    removed, retained = set(), set()
    for beat in candidate.beats:
        owner = removed if set(scope).intersection(beat.source_unit_ids) else retained
        owner.update(beat.brief_requirement_ids)
    return tuple(sorted(removed - retained))


def _validate_repair_requirements(draft: _BookDraft, required: tuple[str, ...]) -> None:
    covered = {requirement for beat in draft.beats for requirement in beat.brief_requirement_ids}
    missing = set(required) - covered
    if missing:
        raise ValueError(
            f"Repair dropped required event/character citations: {sorted(missing)}. "
            "Carry each requirement in a source-backed beat and cite its exact approved ID."
        )


def _splice_draft_repairs(
    draft: _BookDraft,
    repairs: list[tuple[_BookDraft, tuple[str, ...]]],
    source_order: Mapping[str, int],
) -> _BookDraft:
    """Resolve a whole repair transaction before rebasing any global IDs.

    Compression may move a claim to another shard's retained or replacement
    beat. Literal evidence remains source-owned. Unknown/deleted destinations
    fail closed; proximity is never evidence for a replacement ledger link.
    """
    owned = tuple(sorted(
        {e.source_unit_id for e in draft.ledger}
        | {u for b in draft.beats for u in b.source_unit_ids}
        | {u for b in draft.beats for i in b.lettering for u in i.source_unit_ids},
        key=lambda u: source_order.get(u, len(source_order)),
    ))
    original_ids = {b.id for b in draft.beats}
    replaced_sources, removed_ids, new_ids = set(), set(), set()
    aliases, insertions, replacement_ledger = {}, {}, []
    for index, (repair, scope) in enumerate(repairs):
        wanted = set(scope)
        missing = set(_closed_repair_scope(draft, scope, owned)) - wanted
        if missing:
            raise ValueError(f"Repair would remove out-of-scope source evidence: {sorted(missing)}")
        if wanted & replaced_sources or wanted - set(owned):
            raise ValueError("Repair scopes overlap or cross unowned source units.")
        replaced_sources.update(wanted)
        positions = [i for i, b in enumerate(draft.beats) if wanted.intersection(b.source_unit_ids)]
        removed = [draft.beats[i] for i in positions]
        removed_ids.update(b.id for b in removed)
        id_map = {b.id: f"repair_{index}_{b.id}" for b in repair.beats}
        if len(id_map) != len(repair.beats):
            raise ValueError("Repair contains duplicate beat IDs.")
        if {e.source_unit_id for e in repair.ledger} != wanted:
            raise ValueError("Repair ledger must account for exactly its source scope.")
        _validate_draft_source_scope(repair, scope)
        if set(id_map.values()) & original_ids:
            raise ValueError("Repair namespace collides with an existing beat.")
        new_ids.update(id_map.values())
        scoped_ledger = []
        for entry in repair.ledger:
            external = set(entry.adapted_beat_ids) - set(id_map)
            if external and entry.disposition != "compressed_into":
                raise ValueError("Only compression may target an external repair beat.")
            if external - original_ids:
                raise ValueError(f"Repair cites unknown external beats: {sorted(external - original_ids)}")
            scoped_ledger.append(entry.model_copy(update={"adapted_beat_ids": tuple(
                id_map.get(target, target) for target in entry.adapted_beat_ids
            )}))
        replacement_ledger.extend(scoped_ledger)
        destinations = {e.source_unit_id: e.adapted_beat_ids for e in scoped_ledger}
        for old in removed:
            preserved = next((b for b in repair.beats if b.id == old.id
                              and set(b.source_unit_ids).intersection(old.source_unit_ids)), None)
            targets = ([id_map[preserved.id]] if preserved is not None else
                       [t for u in old.source_unit_ids for t in destinations.get(u, ())])
            if not targets:
                targets = [id_map[b.id] for b in repair.beats
                           if set(old.source_unit_ids).intersection(b.source_unit_ids)]
            aliases[old.id] = tuple(dict.fromkeys(targets))
        if positions:
            insertion = min(positions)
        else:
            first = min((source_order[u] for u in wanted), default=len(source_order))
            insertion = next((i for i, b in enumerate(draft.beats)
                              if min(source_order[u] for u in b.source_unit_ids) > first), len(draft.beats))
        insertions.setdefault(insertion, []).extend(
            b.model_copy(update={"id": id_map[b.id]}) for b in repair.beats
        )

    retained_ids = original_ids - removed_ids
    def resolve(target, trail=()):
        if target in new_ids or target in retained_ids:
            return (target,)
        if target in trail:
            raise ValueError(f"Repair compression contains a cyclic destination: {target}")
        if not aliases.get(target):
            raise ValueError(f"Repair removed referenced beat without a supported destination: {target}")
        return tuple(dict.fromkeys(t for linked in aliases[target] for t in resolve(linked, (*trail, target))))

    beats = []
    for index, beat in enumerate(draft.beats):
        beats.extend(insertions.get(index, ()))
        if beat.id not in removed_ids:
            beats.append(beat)
    beats.extend(insertions.get(len(draft.beats), ()))
    ledger = [e for e in draft.ledger if e.source_unit_id not in replaced_sources] + replacement_ledger
    ledger = [e.model_copy(update={"adapted_beat_ids": tuple(dict.fromkeys(
        resolved for target in e.adapted_beat_ids for resolved in resolve(target)
    ))}) for e in ledger]
    ledger.sort(key=lambda e: source_order.get(e.source_unit_id, len(source_order)))
    return _rebase_local_draft(_BookDraft(beats=tuple(beats), ledger=tuple(ledger)))


def recoverable_adaptation_candidate(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
    *,
    artifacts: TargetArtifacts,
    story_instruction: str = "",
) -> BookAdaptation | None:
    """Revalidate a saved draft without generation or artifact mutations."""
    if story_instruction.strip() or not artifacts.failed_adaptation_candidate_path.exists():
        return None
    candidate = artifacts.read_failed_adaptation_candidate()
    # Do not canonicalize a stale draft into the current approved contract.
    if (
        candidate.source_sha256 != source.source_sha256
        or candidate.brief_revision != brief.revision
        or candidate.brief_sha256 != brief.content_sha256
    ):
        return None
    candidate = _canonicalize_candidate_requirements(
        candidate, source, brief, story_bible=story_bible
    )
    validation = validate_book_adaptation(source, brief, candidate, story_bible=story_bible)
    if validation.invariant_failures:
        return None
    try:
        require_narrative_review(artifacts, "adapt", adaptation_context(source, brief, candidate))
    except ValueError:
        return None
    return BookAdaptation.model_validate({
        **candidate.model_dump(mode="json"),
        "content_sha256": "",
        "editorial_issues": validation.editorial_issues,
    })


def _adaptation_work_inputs(source, story_bible, brief, instruction):
    return {"source": source.model_dump(mode="json"), "brief": brief.model_dump(mode="json"),
            "bible": story_bible.model_dump(mode="json"), "instruction": instruction}


def _reviewed_candidate_for_resume(source, story_bible, brief, *, artifacts, model,
                                  story_instruction="") -> BookAdaptation | None:
    """Resume editorial work, never publish, from exact reviewed input receipts.

    A review digest binds the candidate; completed request receipts in the
    current work lineage bind the source, Brief, Bible and author instruction.
    Old/stale artifacts without this evidence are not silently adopted.
    """
    from novel_to_comic.generation_budget import generation_lineage
    from novel_to_comic.narrative_review import (
        REVIEW_VERSION, _review_contexts, _review_request, review_digest,
    )
    from novel_to_comic.target_artifacts import ArtifactMissing, ArtifactInvalid

    if story_instruction.strip() or not artifacts.failed_adaptation_candidate_path.exists():
        return None
    candidate = artifacts.read_failed_adaptation_candidate()
    if (candidate.source_sha256 != source.source_sha256
            or candidate.brief_revision != brief.revision
            or candidate.brief_sha256 != brief.content_sha256):
        return None
    if validate_book_adaptation(source, brief, candidate, story_bible=story_bible).invariant_failures:
        return None
    try:
        review = artifacts.read_narrative_review("adapt")
    except (ArtifactMissing, ArtifactInvalid):
        return None
    context = adaptation_context(source, brief, candidate)
    if (review.version != REVIEW_VERSION
            or review.input_sha256 != review_digest(context)
            or review.instruction != story_instruction or not review.verdicts
            or any(f.code == "narrative_review_invalid" for f in review.failures)):
        return None
    lineage = generation_lineage(_adaptation_work_inputs(source, story_bible, brief, story_instruction))
    if not artifacts.generation_budget_path("adapt", lineage).exists():
        return None
    budget = artifacts.read_generation_budget("adapt", lineage)
    if budget.version != 1 or budget.lineage != lineage:
        return None
    # The previous review's model proves provenance. The selected model owns
    # subsequent work; changing it does not invalidate the existing story.
    receipts = {c.request_sha256 for c in budget.calls if c.status == "completed" and c.model == review.model}
    windows = list(_review_contexts({**context, "approved_story_instruction": story_instruction}))
    if len(windows) != len(review.verdicts):
        return None
    for window in windows:
        request = _review_request(window)
        key = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if key not in receipts:
            return None
    return candidate


def _partition_reviewed_candidate(candidate, shards) -> list[_BookDraft]:
    """Keep reviewed global IDs in repair inputs and enforce shard ownership."""
    source_owner = {u: index for index, ids in enumerate(shards) for u in ids}
    beats = [[] for _ in shards]
    owners = []
    for beat in candidate.beats:
        sources = set(beat.source_unit_ids) | {u for i in beat.lettering for u in i.source_unit_ids}
        ownership = {source_owner.get(u) for u in sources}
        if len(ownership) != 1 or None in ownership:
            raise ValueError("Reviewed candidate crosses source ownership; repair cannot safely resume.")
        owner = ownership.pop()
        owners.append(owner)
        beats[owner].append(beat)
    if owners != sorted(owners):
        raise ValueError("Reviewed candidate crosses shard order; repair cannot safely resume.")
    drafts = []
    for index, ids in enumerate(shards):
        local_ids = {b.id for b in beats[index]}
        ledger = tuple(e for e in candidate.ledger if e.source_unit_id in ids)
        if any(set(e.adapted_beat_ids) - local_ids and e.disposition != "compressed_into" for e in ledger):
            raise ValueError("Reviewed ledger crosses shard ownership; repair cannot safely resume.")
        drafts.append(_BookDraft(beats=tuple(beats[index]), ledger=ledger))
    return drafts


def _repair_boundary_context(candidate, scope):
    """Expose retained events immediately outside the replacement interval."""
    wanted = set(scope)
    positions = [i for i, beat in enumerate(candidate.beats) if wanted.intersection(beat.source_unit_ids)]
    if not positions:
        return {"before": [], "after": []}
    first, last = min(positions), max(positions)
    def view(beats):
        return [{"id": b.id, "source_unit_ids": b.source_unit_ids, "summary": b.summary,
                 "lettering": [i.model_dump(mode="json") for i in b.lettering]} for b in beats]
    return {
        "before": view(candidate.beats[max(0, first - 3):first]),
        "after": view(candidate.beats[last + 1:last + 4]),
    }


def _repair_prompts_for_candidate(source, story_bible, brief, candidate, shards,
                                  validation, affected, scopes, instruction):
    drafts = _partition_reviewed_candidate(candidate, shards)
    _, beat_to_shard = _merged_draft(drafts)
    requirements = partition_requirements_by_shard(source, brief, shards)
    return [
        _repair_prompt(
            build_book_adaptation_prompt(
                source, story_bible, brief, candidate.treatment,
                primary_source_unit_ids=scope,
                owned_requirement_ids=(requirements[index] if set(scope) == set(shards[index])
                                       else _repair_required_requirements(candidate, scope)),
                shard_index=index + 1, shard_count=len(shards),
            ) + story_instruction_section(instruction, stage="adapt"),
            _subset_draft(drafts[index], scope), validation,
            shard_index=index, beat_to_shard=beat_to_shard,
            retained_neighbors=_repair_boundary_context(candidate, scope),
        )
        for index, scope in zip(affected, scopes, strict=True)
    ]


def _resume_adaptation_work(source, story_bible, brief, *, artifacts, model, instruction):
    """Recover authority-bound work and completed, unchecked repair responses.

    No provider calls or artifact mutations. A model switch requires its own
    review, but must not send an existing story back through initial generation.
    """
    from novel_to_comic.generation_budget import generation_lineage

    if not artifacts.failed_adaptation_candidate_path.exists():
        return None
    lineage = generation_lineage(_adaptation_work_inputs(source, story_bible, brief, instruction))
    saved = _read_checkpoint(artifacts, name=f"candidate/{lineage}", input_sha256=lineage,
                             model_type=_AdaptWorkCheckpoint)
    saved_work = None
    if isinstance(saved, _AdaptWorkCheckpoint):
        if (saved.candidate == artifacts.read_failed_adaptation_candidate()
                and tuple(u for part in saved.shards for u in part) == tuple(u.id for u in source.units)):
            _partition_reviewed_candidate(saved.candidate, saved.shards)
            saved_work = saved
            if saved.pending_repair is not None:
                return saved

    candidate = _reviewed_candidate_for_resume(
        source, story_bible, brief, artifacts=artifacts, model=model, story_instruction=instruction,
    )
    if candidate is None:
        return saved_work
    review = artifacts.read_narrative_review("adapt")
    shards = saved_work.shards if saved_work else _adaptation_shards(source, model=review.model)
    work = _AdaptWorkCheckpoint(candidate=candidate, shards=shards)
    drafts = _partition_reviewed_candidate(candidate, shards)
    _, beat_to_shard = _merged_draft(drafts)
    validation = AdaptationValidation(invariant_failures=review.failures)
    affected = _affected_shards(validation, beat_to_shard=beat_to_shard, shard_source_ids=shards)
    if not affected:
        return work
    scopes = [_closed_repair_scope(drafts[index], _repair_source_scope(source, shards[index], validation),
                                   shards[index]) for index in affected]
    prompts = _repair_prompts_for_candidate(source, story_bible, brief, candidate, shards,
                                           validation, affected, scopes, instruction)
    # A fully saved batch may predate the candidate checkpoint (e.g. a splice
    # crash). Recover only exact requests, under their original model identity.
    for round_number in range(1, _MAX_ADAPT_ATTEMPTS):
        names = _repair_checkpoint_names(
            artifacts, prompts=prompts, model=review.model, shard_indices=list(affected),
            round_number=round_number, fresh_namespace="repairs/unavailable",
        )
        repairs = [_read_checkpoint(artifacts, name=name, model_type=_BookDraft,
                   input_sha256=_checkpoint_key(model=review.model, feature="adapt.book", prompt=prompt))
                   for name, prompt in zip(names, prompts, strict=True)]
        if any(repair is None for repair in repairs):
            continue
        try:
            for repair, scope in zip(repairs, scopes, strict=True):
                _validate_book_draft_lettering(repair, known_speaker_ids={c.id for c in story_bible.characters})
                _validate_draft_source_scope(repair, scope)
                _validate_repair_requirements(repair, _repair_required_requirements(candidate, scope))
        except ValueError:
            # Keep the reviewed candidate. Generation reuses valid siblings and
            # repairs the rejected cached payload within the existing allowance.
            continue
        materialized = [_canonicalize_draft_requirements(_materialize_draft_ledger(repair, scope), brief)
                        for repair, scope in zip(repairs, scopes, strict=True)]
        combined = _splice_draft_repairs(
            _BookDraft(beats=candidate.beats, ledger=candidate.ledger),
            list(zip(materialized, scopes, strict=True)), {u.id: u.ordinal for u in source.units},
        )
        repaired = BookAdaptation.model_validate({**candidate.model_dump(), "content_sha256": "",
                                                  "beats": combined.beats, "ledger": combined.ledger})
        _partition_reviewed_candidate(repaired, shards)
        return _AdaptWorkCheckpoint(candidate=repaired, shards=shards,
            pending_repair=_PendingRepairBatch(names=tuple(names), prompts=tuple(prompts), model=review.model))
    return work


def _save_adaptation_work(artifacts, work, source, story_bible, brief, instruction):
    from novel_to_comic.generation_budget import generation_lineage
    lineage = generation_lineage(_adaptation_work_inputs(source, story_bible, brief, instruction))
    artifacts.write_failed_adaptation_candidate(work.candidate)
    _write_checkpoint(artifacts, name=f"candidate/{lineage}", input_sha256=lineage, payload=work)


def _published_adaptation_for_review(artifacts, instruction):
    """Resume a published script without rebuilding it from generation checkpoints."""
    if (artifacts is None or instruction.strip()
            or artifacts.failed_adaptation_candidate_path.exists()
            or not artifacts.adaptation_path.exists()):
        return None
    return artifacts.read_adaptation()


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
    max_generation_calls: int | None = None,
) -> BookAdaptation:
    """Generate, validate, cost, and persist Adapt's one canonical artifact."""

    # An explicitly applied story change travels inside every Adapt prompt so
    # the owning stage regenerates from the approved revision. The suffix is
    # part of each prompt string before any checkpoint key is derived, so a
    # changed instruction never reuses a stale paid response.
    instruction_suffix = story_instruction_section(story_instruction, stage="adapt")
    require_approved_brief(brief)
    published = _published_adaptation_for_review(artifacts, story_instruction)
    if published is not None:
        from novel_to_comic.generation_budget import budgeted_generator

        # A review-policy change invalidates the receipt, not the authored book.
        # Revalidate current authorities and review the exact published script;
        # do not renumber beats or change its hash (Plan checkpoints bind to it).
        with ctx.execute(total=1, estimated_cost_usd=estimate_book_adaptation_cost(
            source, story_bible, brief, model=model, artifacts=artifacts,
        )):
            validation = validate_book_adaptation(source, brief, published, story_bible=story_bible)
            context = adaptation_context(source, brief, published)
            if not validation.invariant_failures:
                try:
                    require_narrative_review(artifacts, "adapt", context)
                    failures = ()
                except ValueError:
                    generate = budgeted_generator(
                        generate, artifacts=artifacts, stage="adapt", model=model,
                        inputs=_adaptation_work_inputs(source, story_bible, brief, story_instruction),
                        override_limit=max_generation_calls is not None,
                        max_calls=max_generation_calls if max_generation_calls is not None else
                        2 * (1 + 2 * len(_adaptation_shards(source, model=model))
                             + 2 * _adapt_review_window_count(source)),
                    )
                    ctx.log("Refreshing the review of the saved adaptation; the script is retained.")
                    failures = await review_narrative(
                        context, generate=generate, ctx=ctx, artifacts=artifacts, model=model,
                    )
                validation = reviewed_validation(
                    validation, failures, artifacts=artifacts, phase="adapt", context=context,
                )
            _persist_validation(artifacts, validation, attempts=1)
            if validation.invariant_failures:
                raise AdaptationInvariantError(validation)
            ctx.record_item_done()
            ctx.progress(1, 1)
        return published
    recovered_candidate = recoverable_adaptation_candidate(
        source, story_bible, brief, artifacts=artifacts,
        story_instruction=story_instruction,
    )
    if recovered_candidate is not None:
        recovered_validation = validate_book_adaptation(
            source, brief, recovered_candidate, story_bible=story_bible,
        )
        with ctx.execute(total=1, estimated_cost_usd=0):
            _persist_validation(artifacts, recovered_validation, attempts=1)
            artifacts.write_adaptation(recovered_candidate)
            artifacts.clear_failed_adaptation_candidate()
            ctx.record_item_done()
            ctx.progress(1, 1)
        return recovered_candidate

    # An explicit resume gets a fresh bounded repair attempt even if a prior
    # repair returned the same invalid draft. Initial paid shards stay reusable.
    repair_namespace = (
        f"repairs/resume_{uuid4().hex}"
        if artifacts.failed_adaptation_candidate_path.exists()
        else "repairs"
    )

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
        artifacts=artifacts,
        story_instruction=story_instruction,
    )
    resume_work = _resume_adaptation_work(
        source, story_bible, brief, artifacts=artifacts, model=model, instruction=story_instruction,
    )
    shards = resume_work.shards if resume_work else _adaptation_shards(source, model=model)
    total_steps = 1 + (2 * len(shards))
    from novel_to_comic.generation_budget import budgeted_generator
    # Clean graph: treatment, blueprint+lettering per shard, source-window
    # reviews and one missing-context verification per window. A third pass is
    # reserved for fewer blocking codes or a changed narrative-review finding
    # after the ordinary repair.
    review_windows = _adapt_review_window_count(source)
    generate = budgeted_generator(
        generate, artifacts=artifacts, stage="adapt", model=model,
        inputs=_adaptation_work_inputs(source, story_bible, brief, story_instruction),
        override_limit=max_generation_calls is not None,
        max_calls=max_generation_calls if max_generation_calls is not None
        else 2 * (total_steps + 2 * review_windows),
    )

    resume_candidate = resume_work.candidate if resume_work else None

    with ctx.execute(total=total_steps, estimated_cost_usd=initial_estimate):
        if resume_candidate is not None:
            treatment = resume_candidate.treatment
            drafts = _partition_reviewed_candidate(resume_candidate, shards)
            unit_by_id = {unit.id: unit for unit in source.units}
            shard_requirements = partition_requirements_by_shard(source, brief, shards)
            known_speaker_ids = {character.id for character in story_bible.characters}
            ctx.log("Continuing from the latest reviewed candidate; completed editorial repairs are retained.")
            for _ in range(total_steps):
                ctx.record_item_done()
            ctx.progress(total_steps, total_steps)
        else:
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
                    with ai_source_context("treatment", tuple(unit.id for unit in source.units)), stream_observer(
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
                ctx.stage_state.cost_usd + estimate_book_adaptation_cost(
                    source,
                    story_bible,
                    brief,
                    model=model,
                    artifacts=artifacts,
                    treatment=treatment,
                    story_instruction=story_instruction,
                )
            )
            candidate: BookAdaptation | None = None
            validation = AdaptationValidation()
            known_speaker_ids = {character.id for character in story_bible.characters}

            async def generate_blueprint(index: int) -> _BlueprintDraft:
                with ai_source_context("blueprint/shard_" + f"{index + 1:03d}", shards[index]):
                    blueprint = await _generate_blueprint(
                        prompt=blueprint_prompts[index],
                        brief=brief,
                        story_bible=story_bible,
                        source_unit_ids=shards[index],
                        owned_requirement_ids=shard_requirements[index],
                        checkpoint_name=f"blueprint/shard_{index + 1:03d}",
                        model=model,
                        artifacts=artifacts,
                        generate=generate,
                        ctx=ctx,
                    )
                ctx.record_item_done()
                ctx.progress(ctx.stage_state.items_done, total_steps)
                return blueprint

            async def generate_lettering(index: int, blueprint: _BlueprintDraft) -> _BookDraft:
                prompt = build_locked_lettering_prompt(
                    source, story_bible, brief, treatment, blueprint,
                    primary_source_unit_ids=shards[index],
                    shard_index=index + 1, shard_count=len(shards),
                ) + instruction_suffix
                with ai_source_context("lettering/shard_" + f"{index + 1:03d}", shards[index]):
                    draft = await _generate_locked_lettering(
                        prompt=prompt,
                        blueprint=blueprint,
                        known_speaker_ids=known_speaker_ids,
                        checkpoint_name=f"lettering/shard_{index + 1:03d}",
                        model=model,
                        artifacts=artifacts,
                        generate=generate,
                        ctx=ctx,
                    )
                ctx.record_item_done()
                ctx.progress(
                    ctx.stage_state.items_done,
                    total_steps,
                )
                return draft

            ctx.activity(detail="locking structure and writing ready shards", force=True)
            generated_drafts = await run_paid_pipeline(
                [lambda index=index: generate_blueprint(index) for index in range(len(shards))],
                generate_lettering,
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
        pending_repair_batch = resume_work.pending_repair if resume_work else None
        for validation_attempt in range(1, _MAX_ADAPT_VALIDATION_ATTEMPTS + 1):
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
                story_bible=story_bible,
            )
            validation = validate_book_adaptation(
                source,
                brief,
                candidate,
                story_bible=story_bible,
            )
            if not validation.invariant_failures:
                # Preserve the exact candidate even if review transport stops.
                _save_adaptation_work(artifacts, _AdaptWorkCheckpoint(
                    candidate=candidate, shards=shards, pending_repair=pending_repair_batch,
                ), source, story_bible, brief, story_instruction)
                review_failures = await review_narrative(
                    adaptation_context(source, brief, candidate), generate=generate,
                    ctx=ctx, artifacts=artifacts, model=model, instruction=story_instruction,
                )
                validation = reviewed_validation(validation, review_failures, artifacts=artifacts, phase="adapt", context=adaptation_context(source, brief, candidate))
            history.append(_attempt_record(validation_attempt, validation))
            if pending_repair_batch is not None:
                _record_repair_batch_outcome(
                    artifacts, pending_repair_batch.names, pending_repair_batch.prompts,
                    pending_repair_batch.model, candidate, validation,
                )
                pending_repair_batch = None
                _save_adaptation_work(artifacts, _AdaptWorkCheckpoint(candidate=candidate, shards=shards),
                                      source, story_bible, brief, story_instruction)
            if not validation.invariant_failures:
                break
            artifacts.write_failed_adaptation_candidate(candidate)
            _persist_validation(artifacts, validation, attempts=validation_attempt, history=tuple(history))
            if (
                not _may_repair_validation_attempt(validation_attempt, history)
                or any(f.code == "narrative_review_invalid" for f in validation.invariant_failures)
            ):
                # Malformed editorial evidence cannot justify rewriting story.
                break
            drafts = _partition_reviewed_candidate(candidate, shards)
            affected = _affected_shards(
                validation,
                beat_to_shard=beat_to_shard,
                shard_source_ids=shards,
            )
            if not affected:
                break
            repair_scopes = [
                _closed_repair_scope(
                    drafts[shard_index],
                    _repair_source_scope(source, shards[shard_index], validation),
                    shards[shard_index],
                )
                for shard_index in affected
            ]
            for shard_index, scope in zip(affected, repair_scopes, strict=True):
                cited = {u for f in validation.invariant_failures for u in f.source_unit_ids
                         if u in shards[shard_index]}
                ctx.log(
                    f"Adapt repair shard {shard_index + 1}: {len(cited)} cited source units; "
                    f"{len(scope)} units after scene, provenance and beat-order closure "
                    f"(of {len(shards[shard_index])} owned units)."
                )
            repair_prompts = _repair_prompts_for_candidate(
                source, story_bible, brief, candidate, shards, validation,
                affected, repair_scopes, story_instruction,
            )
            repair_checkpoint_names = _repair_checkpoint_names(
                artifacts, prompts=repair_prompts, model=model,
                shard_indices=list(affected), round_number=validation_attempt,
                fresh_namespace=repair_namespace,
            )
            generated_repairs = await _generate_book_drafts(
                prompts=repair_prompts,
                source_scopes=repair_scopes,
                required_requirements=[_repair_required_requirements(candidate, scope) for scope in repair_scopes],
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
                checkpoint_names=repair_checkpoint_names,
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
            combined = _splice_draft_repairs(
                _BookDraft(beats=candidate.beats, ledger=candidate.ledger),
                list(zip(repaired, repair_scopes, strict=True)), source_order,
            )
            repaired_candidate = BookAdaptation.model_validate({
                **candidate.model_dump(mode="json"), "content_sha256": "",
                "beats": combined.beats, "ledger": combined.ledger,
            })
            drafts = _partition_reviewed_candidate(repaired_candidate, shards)
            pending_repair_batch = _PendingRepairBatch(
                names=tuple(repair_checkpoint_names), prompts=tuple(repair_prompts), model=model,
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
        "contract. Correct the reported fields while preserving all unaffected "
        "structure, wording, provenance, requirement citations, and exceptions. "
        "A missing citation or accounting reason is a metadata correction; do not "
        "invent or restage an event to supply its ID. Return one complete JSON "
        "object: use JSON arrays for "
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
    retained_neighbors: dict,
) -> str:
    local_source_ids = {entry.source_unit_id for entry in previous_draft.ledger}
    local_source_ids.update(u for beat in previous_draft.beats for u in beat.source_unit_ids)
    relevant = [
        failure
        for failure in validation.invariant_failures
        if (
            bool(local_source_ids.intersection(failure.source_unit_ids))
            or any(
                beat_to_shard.get(artifact_id) == shard_index
                for artifact_id in failure.artifact_ids
            )
            or (not failure.source_unit_ids and not any(
                artifact_id in beat_to_shard for artifact_id in failure.artifact_ids
            ))
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
        f"{book_prompt}\n\n{_DISPLAY_EXCERPT_CONTRACT}"
        "Your previous book adaptation violated these blocking "
        "contract requirements. Return one complete corrected JSON object that "
        "resolves every one of them without dropping content you already had. "
        "Keep unaffected wording, facts, requirement citations, and source "
        "accounting unchanged. If a required event is already present, add its "
        "missing citation to that beat instead of staging it again. When removing "
        "a repeated or unsupported beat, transfer supported provenance and "
        "requirement IDs only to the surviving beat that actually realizes them; "
        "author explicit reasoned exceptions for any remaining uncited source. "
        "Source order can contain "
        "retrospective narration: distinguish the narrating self's later knowledge "
        "from what the experiencing character knew then. Preserve supported "
        "foreshadowing with explicit reader-visible time framing rather than "
        "silently moving knowledge earlier or deleting the source fact. Preserve "
        "date exceptions in montages; do not fold later echoes into an earlier "
        "synchronized event. Treat structural validation failures as structural "
        "edits, not just prose edits: for unknown_entity, remove each named unknown "
        "ID from entity_ids and use only visible Story Bible entity IDs; for "
        "faithful_rushed_reaction_or_aftermath, retain the cited reveal and mark its "
        "source-backed response beat with story_functions=reaction or aftermath. "
        "An on-beat source-cited thought or realization is that response: preserve it "
        "and add reaction rather than deleting the reveal or inventing a new event. "
        "Otherwise add a source-backed response beat before the next transition. "
        "Beat and lettering IDs below are the exact global "
        "IDs used by the findings:\n"
        f"{failures}\n\nREAD-ONLY RETAINED NEIGHBORS:\n"
        "These beats remain outside your replacement. Preserve their exact words "
        "and event ownership. Do not include them in your output or restage their "
        "completed events inside the replacement. Source summaries and foreshadowing "
        "must not become a second enactment of a scene already shown here. Return "
        "only replacement beats and ledger exceptions for your owned source scope.\n"
        f"{json.dumps(retained_neighbors, separators=(',', ':'), ensure_ascii=False)}"
        "\n\nYOUR PREVIOUS SHARD JSON:\n"
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


def _may_repair_validation_attempt(
    attempt: int,
    history: list[ValidationAttempt],
) -> bool:
    """Keep repair bounded while handling a newly exposed review defect.

    The first repair is available to every blocking validation failure.  A
    second repair is available when blocking codes strictly decrease or a
    changed set of evidence-backed narrative review failures appears. This avoids
    a manual Resume when a correction makes demonstrable progress. Repeating the
    same review result cannot consume another provider call.
    """
    if attempt < _MAX_ADAPT_ATTEMPTS:
        return True
    if attempt != _MAX_ADAPT_ATTEMPTS or len(history) < 2:
        return False
    current = set(history[-1].invariant_codes)
    previous = set(history[-2].invariant_codes)
    return (
        current != previous
        and bool(current)
        and (current < previous or all(code.startswith("narrative_review_") for code in current))
        and current != {"narrative_review_invalid"}
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
            citing_beats = tuple(
                beat for beat in adaptation.beats
                if unknown_entities.intersection(beat.entity_ids)
            )
            failures.append(InvariantFailure(
                id="adapt_failure_unknown_entity", owner_stage="adapt", code="unknown_entity",
                message="Visible entity citations must resolve in the Story Bible.",
                # Preserve the bad IDs for an actionable diagnostic, but also
                # cite their beats and source.  Repair routing understands beat
                # IDs and source IDs; entity IDs alone previously left this
                # failure with no shard to correct.
                source_unit_ids=tuple(dict.fromkeys(
                    source_id for beat in citing_beats for source_id in beat.source_unit_ids
                )),
                artifact_ids=tuple([
                    *(beat.id for beat in citing_beats),
                    *sorted(unknown_entities),
                ]),
                evidence=(f"Unknown entity IDs: {sorted(unknown_entities)!r}",),
            ))
        failures.extend(_appearance_state_authority_failures(adaptation, story_bible))
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
            _contains_protected_language(wording, phrase) for wording in complete_wording
        )
    ]
    for phrase_index, phrase in enumerate(missing_protected):
        missing_source_ids = tuple(
            unit.id for unit in source.units
            if _contains_protected_language(_protected_source_key(unit.text), phrase)
        )
        missing_beats = tuple(dict.fromkeys(
            beat_id for entry in adaptation.ledger
            if entry.source_unit_id in missing_source_ids
            for beat_id in entry.adapted_beat_ids
        ))
        failures.append(
            InvariantFailure(
                id="adapt_failure_protected_language_missing" + (f"_{phrase_index}" if phrase_index else ""),
                owner_stage="adapt",
                code="protected_language_missing",
                message="Protected language must survive verbatim in publishable wording.",
                source_unit_ids=missing_source_ids,
                artifact_ids=missing_beats,
                evidence=[
                    "Missing exact protected phrase: " + repr(phrase)
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
                    source_unit_ids=item.source_unit_ids,
                    artifact_ids=[item.id, *(beat.id for beat in adaptation.beats
                                             if any(owned.id == item.id for owned in beat.lettering))],
                    evidence=[f"Incomplete display text: {text!r}"],
                )
            )
        # A source-backed book title is complete display copy without a full
        # stop. Keep the clipping check for prose and all other captions.
        is_book_title = (
            story_bible is not None
            and item.kind == "caption"
            and item.delivery == "quoted_text"
            and text == story_bible.title
            and text in brief.protected_language
            and any(
                unit.id in item.source_unit_ids and text in unit.text
                for unit in source.units
            )
        )
        # Exact approved narration can intentionally be a phrase without a
        # final stop. Adding punctuation would violate protected wording.
        is_protected_narration = (
            item.kind == "caption"
            and item.delivery == "narration"
            and text in brief.protected_language
            and any(unit.id in item.source_unit_ids for unit in source.units)
        )
        if (
            not _has_terminal_display_punctuation(text)
            and not is_book_title
            and not is_protected_narration
        ):
            # Missing punctuation cannot prove truncation: date cards, headings,
            # chants, and quoted phrases may be complete without a final stop.
            # Preserve the evidence for editorial review rather than forcing
            # regeneration or changing approved wording to satisfy a heuristic.
            issues.append(
                EditorialIssue(
                    id=f"adapt_issue_possible_clipped_display_text_{item.id}",
                    owner_stage="adapt",
                    code="possible_clipped_display_text",
                    message="Check whether unpunctuated display text is intentionally complete.",
                    source_unit_ids=item.source_unit_ids,
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
        # A reveal can itself contain the character's supported internal
        # response.  An explicit character_turn on that same beat is a
        # reaction with its own narrative weight; do not require a redundant
        # extra beat merely because the response and revelation are inseparable.
        # A character turn that appears only after the next transition remains
        # insufficient, preserving the guard against rushed aftermath.
        if _has_explicit_reveal_response(beat):
            carried_functions.add("reaction")
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
        dropped = [phrase for phrase in protected if _contains_protected_language(unit_text, phrase)]
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
