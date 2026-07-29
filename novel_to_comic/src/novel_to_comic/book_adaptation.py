"""Book-level Adapt production for the full-page pipeline."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from novel_to_comic.ai.context import stream_observer
from novel_to_comic.briefing import require_approved_brief
from novel_to_comic.json_contract import describe_json_contract
from novel_to_comic.model_costs import get_pricing_resolver
from novel_to_comic.models.adaptation import (
    AdaptationBrief,
    AdaptationLedgerEntry,
    AdaptedBeat,
    BookAdaptation,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.models.validation import (
    EditorialIssue,
    InvariantFailure,
    StageValidation,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.text_utils import normalize_display_text
from novel_to_comic.usage import ApiResult, estimate_text_cost


_MAX_ADAPT_ATTEMPTS = 2
_ADAPT_SHARD_MAX_UNITS = 180
_ADAPT_MAX_CONCURRENCY = 4
_ADAPT_OUTPUT_BUDGET_RATIO = 0.65
_ADAPT_OUTPUT_TOKENS_PER_SOURCE_CHAR = 1.5


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


class _BookDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    beats: tuple[AdaptedBeat, ...]
    ledger: tuple[AdaptationLedgerEntry, ...]


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
    """Reconcile exact approved wording and stable IDs on adapted beats."""

    registry = _requirement_registry(brief)
    id_by_requirement = {
        requirement: requirement_id for requirement_id, requirement in registry.items()
    }
    beats: list[AdaptedBeat] = []
    for beat in draft.beats:
        requirement_ids = list(beat.brief_requirement_ids)
        requirement_ids.extend(
            id_by_requirement[requirement]
            for requirement in beat.brief_requirements
            if requirement in id_by_requirement
        )
        requirement_ids = list(dict.fromkeys(requirement_ids))

        requirements = list(beat.brief_requirements)
        requirements.extend(
            registry[requirement_id]
            for requirement_id in requirement_ids
            if requirement_id in registry
        )
        beats.append(
            beat.model_copy(
                update={
                    "brief_requirement_ids": tuple(requirement_ids),
                    "brief_requirements": tuple(dict.fromkeys(requirements)),
                }
            )
        )
    return draft.model_copy(update={"beats": tuple(beats)})


def _canonicalize_candidate_requirements(
    candidate: BookAdaptation,
    source: SourceDocument,
    brief: AdaptationBrief,
) -> BookAdaptation:
    draft = _canonicalize_draft_requirements(
        _BookDraft(beats=candidate.beats, ledger=candidate.ledger),
        brief,
    )
    beats = list(draft.beats)
    registry = _requirement_registry(brief)
    for requirement_id, requirement in registry.items():
        if any(
            requirement_id in beat.brief_requirement_ids
            for beat in beats
        ):
            continue
        prefix, raw_index = requirement_id.rsplit("_", 1)
        candidates = beats
        if prefix == "essential_event":
            requirement_index = int(raw_index)
            lower = max(
                (
                    beat.order
                    for beat in beats
                    for assigned_id in beat.brief_requirement_ids
                    if assigned_id.startswith("essential_event_")
                    and int(assigned_id.rsplit("_", 1)[1]) < requirement_index
                ),
                default=1,
            )
            upper = min(
                (
                    beat.order
                    for beat in beats
                    for assigned_id in beat.brief_requirement_ids
                    if assigned_id.startswith("essential_event_")
                    and int(assigned_id.rsplit("_", 1)[1]) > requirement_index
                ),
                default=len(beats),
            )
            candidates = [
                beat for beat in beats if lower <= beat.order <= upper
            ]
        best, overlap = _closest_requirement_beat(
            candidates,
            requirement=requirement,
            story_function=(
                "causal_event"
                if prefix == "essential_event"
                else "character_turn"
            ),
        )
        if best is None or overlap < 2:
            continue
        beat_index = beats.index(best)
        beats[beat_index] = best.model_copy(
            update={
                "brief_requirement_ids": (
                    *best.brief_requirement_ids,
                    requirement_id,
                ),
                "brief_requirements": (
                    *best.brief_requirements,
                    requirement,
                ),
            }
        )

    canonical = BookAdaptation.model_validate(
        {
            **candidate.model_dump(mode="json"),
            "content_sha256": "",
            "treatment": _canonicalize_treatment_requirements(
                candidate.treatment,
                brief,
            ).model_dump(mode="json"),
            "beats": [beat.model_dump(mode="json") for beat in beats],
            "ledger": [entry.model_dump(mode="json") for entry in draft.ledger],
        }
    )
    return _materialize_protected_lettering(canonical, source, brief)


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
                *beat.brief_requirements,
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


def _materialize_protected_lettering(
    candidate: BookAdaptation,
    source: SourceDocument,
    brief: AdaptationBrief,
) -> BookAdaptation:
    """Copy ledgered protected source wording into canonical lettering."""

    beats = list(candidate.beats)
    existing_keys = {
        _protected_language_key(item.text)
        for beat in beats
        for item in beat.lettering
    }
    source_by_id = {unit.id: unit for unit in source.units}
    ledger_by_source = {
        entry.source_unit_id: entry for entry in candidate.ledger
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
        entry = ledger_by_source.get(source_unit.id)
        kind = kind_by_disposition.get(entry.disposition) if entry else None
        destination = entry.adapted_beat_ids[0] if entry and entry.adapted_beat_ids else None
        if kind is None or destination is None:
            continue
        beat_index = next(
            (index for index, beat in enumerate(beats) if beat.id == destination),
            None,
        )
        if beat_index is None:
            continue
        text = phrase if phrase in source_by_id[source_unit.id].text else source_unit.text.strip()
        lettering = LetteringItem(
            id=f"lettering_{next_lettering_number:04d}",
            kind=kind,
            text=text,
            source_unit_ids=(source_unit.id,),
        )
        next_lettering_number += 1
        beat = beats[beat_index]
        beats[beat_index] = beat.model_copy(
            update={"lettering": (*beat.lettering, lettering)}
        )
        existing_keys.add(_protected_language_key(text))

    return BookAdaptation.model_validate(
        {
            **candidate.model_dump(mode="json"),
            "content_sha256": "",
            "beats": [beat.model_dump(mode="json") for beat in beats],
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


def build_narrative_treatment_prompt(
    source: SourceDocument,
    story_bible: StoryBible,
    brief: AdaptationBrief,
) -> str:
    """Compile the book-wide dramatic-reasoning prompt from canonical inputs."""

    context = {
        "source_sha256": source.source_sha256,
        "source_units": [unit.model_dump(mode="json") for unit in source.units],
        "source_scenes": [scene.model_dump(mode="json") for scene in source.scenes],
        "story_bible": story_bible.model_dump(mode="json"),
        "approved_adaptation_brief": brief.model_dump(mode="json"),
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
        "work. Return only the narrative-treatment JSON object.\n"
        + describe_json_contract(NarrativeTreatment)
        + "\n"
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
) -> str:
    """Compile the single ordered book-adaptation prompt contract."""

    primary_ids = primary_source_unit_ids or tuple(unit.id for unit in source.units)
    primary_id_set = set(primary_ids)
    source_units = [
        unit.model_dump(mode="json")
        for unit in source.units
        if unit.id in primary_id_set
    ]
    source_scenes = [
        scene.model_dump(mode="json")
        for scene in source.scenes
        if primary_id_set.intersection(scene.unit_ids(source))
    ]
    context = {
        "source_sha256": source.source_sha256,
        "adaptation_scope": {
            "shard_index": shard_index,
            "shard_count": shard_count,
            "primary_source_unit_ids": primary_ids,
        },
        "source_units": source_units,
        "source_scenes": source_scenes,
        "story_bible": story_bible.model_dump(mode="json"),
        "approved_adaptation_brief": brief.model_dump(mode="json"),
        "approved_requirement_registry": _requirement_registry(brief),
        "narrative_treatment": treatment.model_dump(mode="json"),
    }
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
    faithful_instruction = ""
    if brief.transformation_level == "faithful":
        faithful_instruction = (
            "This is a faithful adaptation. Treat narrative completeness as a "
            "blocking requirement: every reveal must receive an explicit reaction "
            "or aftermath before the next transition, and do not compress a "
            "multi-step explanation into a single visual beat when separate beats "
            "would preserve the causal chain. "
        )
    return (
        scope_instruction
        + faithful_instruction
        + "Write the globally ordered AdaptedBeats for the supplied source scope. "
        "Own complete, publishable dialogue, thought, caption, and SFX wording; "
        "never return fragments or trailing-clipped display text. Preserve every "
        "protected-language string verbatim. Record causal events, reveals, "
        "reactions, consequences, transitions, aftermath, character turns, and "
        "appearance-state changes explicitly. Every continuity transition must "
        "set scope_id to a stable Story Bible entity ID for knowledge/emotion, or "
        "a stable narrative-thread ID for time/place. Copy each approved essential "
        "event and character turn from the brief into brief_requirements on the "
        "beat that carries it, and copy its stable registry key into "
        "brief_requirement_ids. The target page range is not a beat-count target: "
        "derive granularity from the story rather than producing one beat per page. "
        "Each adapted beat should carry one drawable story moment. Split compound "
        "action, reaction, transition, reveal, consequence, and aftermath into "
        "separate visual beats whenever each moment needs distinct visual weight; "
        "never pad by duplicating content. "
        "For every ledger entry marked dialogue, thought, or caption, cite its "
        "source unit on a matching source-linked canonical LetteringItem; a beat "
        "summary alone does not realize a lettering disposition. Cite source-unit "
        "provenance and "
        "assign exactly one ledger disposition for every source unit. Compression "
        "requires a reason and an existing adapted-beat destination. Intentional "
        "omission requires a reason, the function intentionally removed, and no "
        "adapted-beat destination. Use the target page range only for proportional "
        "selection. Do not allocate pages, panels, layouts, or geometry. Do not "
        "create scene-parallel screenplays or reconciliation work. Return one JSON "
        "object containing only beats and ledger.\n"
        + describe_json_contract(_BookDraft)
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
) -> float:
    """Estimate one clean sharded pass plus a bounded repair allowance."""

    treatment_prompt = build_narrative_treatment_prompt(source, story_bible, brief)
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
    prompts = [
        build_book_adaptation_prompt(
            source,
            story_bible,
            brief,
            treatment,
            primary_source_unit_ids=source_ids,
            shard_index=index,
            shard_count=len(shards),
        )
        for index, source_ids in enumerate(shards, 1)
    ]
    clean_pass = estimate_text_cost(
        model,
        treatment_prompt,
        output_chars=max(12_000, len(source.text)),
    ) + sum(
        estimate_text_cost(
            model,
            prompt,
            output_chars=_shard_output_chars(unit_by_id, source_ids),
        )
        for prompt, source_ids in zip(prompts, shards, strict=True)
    )
    return clean_pass * 1.25


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


async def _generate_book_draft(
    *,
    prompt: str,
    generate: StructuredGenerator,
    ctx: StageRuntime,
) -> _BookDraft:
    attempt_prompt = prompt
    for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
        result = await generate(
            system_prompt=(
                "You are the sole book-level Adapt writer. Return complete JSON."
            ),
            user_content=attempt_prompt,
            feature="adapt.book",
            json_schema=_BookDraft.model_json_schema(),
        )
        _record_result_usage(ctx, result)
        try:
            return _BookDraft.model_validate(result.value)
        except ValidationError as error:
            if attempt == _MAX_ADAPT_ATTEMPTS:
                raise
            attempt_prompt = _schema_repair_prompt(prompt, result.value, error)
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
) -> list[_BookDraft]:
    semaphore = asyncio.Semaphore(_ADAPT_MAX_CONCURRENCY)
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
        async with semaphore:
            with stream_observer(lambda chars: report(index, chars)):
                draft = await _generate_book_draft(
                    prompt=prompt,
                    generate=generate,
                    ctx=ctx,
                )
        if record_progress:
            ctx.record_item_done()
            completed += 1
            ctx.progress(progress_offset + completed, progress_total)
        return draft

    ctx.activity(fraction=0.0, detail=detail, force=True)
    drafts = list(
        await asyncio.gather(
            *(generate_one(index, prompt) for index, prompt in enumerate(prompts))
        )
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
) -> BookAdaptation:
    """Generate, validate, cost, and persist Adapt's one canonical artifact."""

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
    )
    initial_estimate = estimate_book_adaptation_cost(
        source,
        story_bible,
        brief,
        model=model,
    )
    shards = _adaptation_shards(source, model=model)
    total_steps = 1 + len(shards)

    with ctx.execute(total=total_steps, estimated_cost_usd=initial_estimate):
        treatment_prompt_attempt = treatment_prompt
        treatment: NarrativeTreatment | None = None
        for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
            # Heartbeat only — the treatment's output size isn't predictable
            # enough from the source to make a fraction honest.
            with stream_observer(lambda chars: ctx.activity(detail="writing treatment")):
                treatment_result = await generate(
                    system_prompt=(
                        "You are the book-level narrative architect for a comic "
                        "adaptation."
                    ),
                    user_content=treatment_prompt_attempt,
                    feature="adapt.narrative_treatment",
                    json_schema=NarrativeTreatment.model_json_schema(),
                )
            # A retried attempt was still paid for, so its usage is recorded
            # without counting a completed item.
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
            ctx.record_item_done()
            break
        assert treatment is not None  # the loop either binds it or raises
        ctx.progress(1, total_steps)

        unit_by_id = {unit.id: unit for unit in source.units}
        shard_chars = [
            _shard_output_chars(unit_by_id, source_unit_ids)
            for source_unit_ids in shards
        ]
        book_prompts = [
            build_book_adaptation_prompt(
                source,
                story_bible,
                brief,
                treatment,
                primary_source_unit_ids=source_unit_ids,
                shard_index=shard_index,
                shard_count=len(shards),
            )
            for shard_index, source_unit_ids in enumerate(shards, 1)
        ]
        ctx.set_estimated_cost(
            estimate_book_adaptation_cost(
                source,
                story_bible,
                brief,
                model=model,
                treatment=treatment,
            )
        )
        candidate: BookAdaptation | None = None
        validation = AdaptationValidation()
        drafts = [
            _canonicalize_draft_requirements(draft, brief)
            for draft in await _generate_book_drafts(
                prompts=book_prompts,
                generate=generate,
                ctx=ctx,
                progress_offset=1,
                progress_total=total_steps,
                record_progress=True,
                expected_chars=shard_chars,
                detail=f"drafting {len(book_prompts)} shards",
            )
        ]
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
            validation = validate_book_adaptation(source, brief, candidate)
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
            repair_prompts = [
                _repair_prompt(
                    book_prompts[shard_index],
                    drafts[shard_index],
                    validation,
                    shard_index=shard_index,
                    beat_to_shard=beat_to_shard,
                )
                for shard_index in affected
            ]
            repaired = [
                _canonicalize_draft_requirements(draft, brief)
                for draft in await _generate_book_drafts(
                    prompts=repair_prompts,
                    generate=generate,
                    ctx=ctx,
                    progress_offset=1,
                    progress_total=total_steps,
                    record_progress=False,
                    expected_chars=[shard_chars[index] for index in affected],
                    detail=(
                        f"repairing {len(affected)} of {len(shards)} shards "
                        f"(round {validation_attempt})"
                    ),
                )
            ]
            for shard_index, repaired_draft in zip(affected, repaired, strict=True):
                drafts[shard_index] = repaired_draft

        assert candidate is not None  # validation loop runs at least once
        _persist_validation(
            artifacts,
            validation,
            attempts=validation_attempt,
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
        )
    ]
    failures = "\n".join(
        f"- [{failure.code}] {failure.message} " + " ".join(failure.evidence)
        for failure in relevant
    )
    return (
        f"{book_prompt}\n\nYour previous book adaptation violated these blocking "
        "contract requirements. Return one complete corrected JSON object that "
        "resolves every one of them without dropping content you already had:\n"
        f"{failures}\n\nYOUR PREVIOUS SHARD JSON:\n"
        f"{previous_draft.model_dump_json(indent=2)}"
    )


def _persist_validation(
    artifacts: TargetArtifacts,
    validation: AdaptationValidation,
    *,
    attempts: int,
) -> None:
    artifacts.write_validation(
        StageValidation(
            owner_stage="adapt",
            attempts=attempts,
            invariant_failures=validation.invariant_failures,
            editorial_issues=validation.editorial_issues,
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
                *beat.brief_requirements,
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
) -> AdaptationValidation:
    """Validate a candidate only against Adapt-owned canonical inputs."""

    failures: list[InvariantFailure] = []
    issues: list[EditorialIssue] = []
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
    complete_wording = tuple(
        _protected_language_key(item.text) for item in lettering
    )
    missing_protected = [
        phrase
        for phrase in brief.protected_language
        if not any(
            _protected_language_key(phrase) in wording
            for wording in complete_wording
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

    # Stable IDs carry identity; the accompanying strings remain editorial
    # wording and may be paraphrased without manufacturing a missing requirement.
    registry = _requirement_registry(brief)
    covered_requirement_ids = {
        requirement_id
        for beat in adaptation.beats
        for requirement_id in beat.brief_requirement_ids
    }
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
