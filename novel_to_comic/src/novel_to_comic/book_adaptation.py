"""Book-level Adapt production for the full-page pipeline."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from novel_to_comic.briefing import require_approved_brief
from novel_to_comic.models.adaptation import (
    AdaptationBrief,
    AdaptationLedgerEntry,
    AdaptedBeat,
    BookAdaptation,
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
from novel_to_comic.text_utils import normalize_display_text, normalize_requirement
from novel_to_comic.usage import ApiResult, estimate_text_cost


_MAX_ADAPT_ATTEMPTS = 2


class AdaptationValidation(BaseModel):
    """Adapt-owned blocking failures and reviewable creative concerns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invariant_failures: tuple[InvariantFailure, ...] = ()
    editorial_issues: tuple[EditorialIssue, ...] = ()


class _BookDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    beats: tuple[AdaptedBeat, ...]
    ledger: tuple[AdaptationLedgerEntry, ...]


class AdaptationInvariantError(ValueError):
    """Raised when model output violates a blocking Adapt invariant."""

    def __init__(self, validation: AdaptationValidation) -> None:
        codes = ", ".join(
            failure.code for failure in validation.invariant_failures
        )
        super().__init__(f"Book adaptation has invariant failures: {codes}")
        self.validation = validation


StructuredGenerator = Callable[
    ...,
    Awaitable[ApiResult[Mapping[str, Any]]],
]


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
    }
    return (
        "Create one book-wide narrative treatment for the complete adaptation. "
        "Account for the causal spine, essential events, character turns, reveals, "
        "reactions, consequences, transitions, aftermath, motifs, narrator voice, "
        "and relative narrative emphasis. Carry every approved essential event and "
        "character turn from the brief into the matching treatment field using the "
        "brief's own wording. Use the approved target page range only "
        "to guide proportional selection. Do not allocate pages, panels, layouts, "
        "or geometry. Do not create parallel per-scene adaptations or reconciliation "
        "work. Return only the narrative-treatment JSON object.\n"
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
) -> str:
    """Compile the single ordered book-adaptation prompt contract."""

    context = {
        "source_sha256": source.source_sha256,
        "source_units": [unit.model_dump(mode="json") for unit in source.units],
        "source_scenes": [scene.model_dump(mode="json") for scene in source.scenes],
        "story_bible": story_bible.model_dump(mode="json"),
        "approved_adaptation_brief": brief.model_dump(mode="json"),
        "narrative_treatment": treatment.model_dump(mode="json"),
    }
    return (
        "Write one globally ordered sequence of AdaptedBeats for the whole book. "
        "Own complete, publishable dialogue, thought, caption, and SFX wording; "
        "never return fragments or trailing-clipped display text. Preserve every "
        "protected-language string verbatim. Record causal events, reveals, "
        "reactions, consequences, transitions, aftermath, character turns, and "
        "appearance-state changes explicitly. Copy each approved essential event "
        "and character turn from the brief into brief_requirements on the beat "
        "that carries it, using the brief's own wording. Cite source-unit "
        "provenance and "
        "assign exactly one ledger disposition for every source unit. Compression "
        "requires a reason and an existing adapted-beat destination. Intentional "
        "omission requires a reason, the function intentionally removed, and no "
        "adapted-beat destination. Use the target page range only for proportional "
        "selection. Do not allocate pages, panels, layouts, or geometry. Do not "
        "create scene-parallel screenplays or reconciliation work. Return one JSON "
        "object containing only beats and ledger.\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
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
) -> BookAdaptation:
    """Generate, validate, cost, and persist Adapt's one canonical artifact."""

    require_approved_brief(brief)
    treatment_prompt = build_narrative_treatment_prompt(
        source,
        story_bible,
        brief,
    )
    initial_estimate = estimate_text_cost(
        model,
        treatment_prompt,
        output_chars=max(4_000, len(source.text)),
    ) + estimate_text_cost(
        model,
        treatment_prompt,
        output_chars=max(8_000, len(source.text) * 2),
    )

    with ctx.execute(total=2, estimated_cost_usd=initial_estimate):
        treatment_prompt_attempt = treatment_prompt
        treatment: NarrativeTreatment | None = None
        for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
            treatment_result = await generate(
                system_prompt=(
                    "You are the book-level narrative architect for a comic adaptation."
                ),
                user_content=treatment_prompt_attempt,
                json_schema=NarrativeTreatment.model_json_schema(),
                feature="adapt.narrative_treatment",
            )
            # A retried attempt was still paid for, so its usage is recorded
            # without counting a completed item.
            if treatment_result.usage is not None:
                ctx.record_api_usage(treatment_result.usage)
            try:
                treatment = NarrativeTreatment.model_validate(treatment_result.value)
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
        ctx.progress(1, 2)

        book_prompt = build_book_adaptation_prompt(
            source,
            story_bible,
            brief,
            treatment,
        )
        ctx.set_estimated_cost(
            estimate_text_cost(
                model,
                treatment_prompt,
                output_chars=max(4_000, len(source.text)),
            )
            + estimate_text_cost(
                model,
                book_prompt,
                output_chars=max(8_000, len(source.text) * 2),
            )
        )
        attempt_prompt = book_prompt
        candidate: BookAdaptation | None = None
        validation = AdaptationValidation()
        for attempt in range(1, _MAX_ADAPT_ATTEMPTS + 1):
            book_result = await generate(
                system_prompt=(
                    "You are the sole book-level Adapt writer. Return complete JSON."
                ),
                user_content=attempt_prompt,
                json_schema=_BookDraft.model_json_schema(),
                feature="adapt.book",
            )
            if book_result.usage is not None:
                ctx.record_api_usage(book_result.usage)
            try:
                draft = _BookDraft.model_validate(book_result.value)
            except ValidationError as error:
                # A shape slip is not a contract violation the user can act on;
                # it is a formatting mistake, and re-running the whole stage by
                # hand costs the full generation again.
                if attempt == _MAX_ADAPT_ATTEMPTS:
                    raise
                attempt_prompt = _schema_repair_prompt(
                    book_prompt,
                    book_result.value,
                    error,
                )
                continue
            candidate = BookAdaptation(
                revision=1,
                source_sha256=source.source_sha256,
                brief_revision=brief.revision,
                brief_sha256=brief.content_sha256,
                treatment=treatment,
                beats=draft.beats,
                ledger=draft.ledger,
            )
            validation = validate_book_adaptation(source, brief, candidate)
            if not validation.invariant_failures:
                ctx.record_item_done()
                break
            if attempt < _MAX_ADAPT_ATTEMPTS:
                # One repair pass with the exact failures. Most Adapt invariants
                # are satisfiable by the same model given the specific evidence,
                # and re-running the whole stage by hand costs the user the full
                # generation again.
                attempt_prompt = _repair_prompt(book_prompt, validation)
        ctx.progress(2, 2)

        assert candidate is not None  # loop runs at least once
        _persist_validation(artifacts, validation, attempts=attempt)
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


def _repair_prompt(book_prompt: str, validation: AdaptationValidation) -> str:
    failures = "\n".join(
        f"- [{failure.code}] {failure.message} " + " ".join(failure.evidence)
        for failure in validation.invariant_failures
    )
    return (
        f"{book_prompt}\n\nYour previous book adaptation violated these blocking "
        "contract requirements. Return one complete corrected JSON object that "
        "resolves every one of them without dropping content you already had:\n"
        f"{failures}"
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
                        "Unknown source provenance: "
                        + ", ".join(unknown_provenance)
                    ],
                )
            )

    lettering = [
        item
        for beat in adaptation.beats
        for item in beat.lettering
    ]
    # Both sides are model output: the Brief inferred the phrase, Adapt wrote the
    # balloon. They routinely disagree on quote style, dash form, and line
    # wrapping while carrying identical words, so compare under the shared
    # display-text policy instead of raw substring identity.
    complete_wording = "\n".join(
        normalize_display_text(item.text) for item in lettering
    )
    missing_protected = [
        phrase
        for phrase in brief.protected_language
        if normalize_display_text(phrase) not in complete_wording
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

    # Requirement strings are echoed by a model two hops away from the Brief, so
    # identity is compared on the normalized requirement, not the exact string.
    # A reworded essential event is not a missing one.
    covered_requirements = {
        normalize_requirement(requirement)
        for beat in adaptation.beats
        for requirement in beat.brief_requirements
    }
    for requirements, treatment_requirements, code, label in (
        (
            brief.essential_events,
            adaptation.treatment.essential_events,
            "missing_essential_event",
            "essential event",
        ),
        (
            brief.character_turns,
            adaptation.treatment.character_turns,
            "missing_character_turn",
            "character turn",
        ),
    ):
        treated = {
            normalize_requirement(requirement)
            for requirement in treatment_requirements
        }
        missing_requirements = [
            requirement
            for requirement in requirements
            if (
                normalize_requirement(requirement) not in treated
                or normalize_requirement(requirement) not in covered_requirements
            )
        ]
        if missing_requirements:
            failures.append(
                InvariantFailure(
                    id=f"adapt_failure_{code}",
                    owner_stage="adapt",
                    code=code,
                    message=f"Every approved {label} must be carried by a beat.",
                    evidence=[
                        f"Uncovered approved {label}: {requirement!r}"
                        for requirement in missing_requirements
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
    continuity_states: dict[str, str] = {}
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
            previous = continuity_states.get(transition.dimension)
            if previous is not None and transition.from_state != previous:
                failures.append(
                    InvariantFailure(
                        id=f"adapt_failure_transition_continuity_{beat.id}",
                        owner_stage="adapt",
                        code="transition_continuity",
                        message="A continuity transition does not begin from prior state.",
                        artifact_ids=[beat.id],
                        evidence=[
                            f"Expected {transition.dimension!r} transition from "
                            f"{previous!r}; found {transition.from_state!r}."
                        ],
                    )
                )
            continuity_states[transition.dimension] = transition.to_state

    issues.extend(_omission_issues(source, brief, adaptation))

    for index, beat in enumerate(adaptation.beats):
        if "reveal" not in beat.story_functions:
            continue
        follow_through = [beat]
        for later in adaptation.beats[index + 1 :]:
            if "transition" in later.story_functions:
                break
            follow_through.append(later)
        carried_functions = {
            function
            for candidate in follow_through
            for function in candidate.story_functions
        }
        missing = [
            function
            for function in ("reaction", "aftermath")
            if function not in carried_functions
        ]
        if missing:
            issues.append(
                EditorialIssue(
                    id=f"adapt_issue_rushed_reaction_or_aftermath_{beat.id}",
                    owner_stage="adapt",
                    code="rushed_reaction_or_aftermath",
                    message="A reveal reaches the next transition without full follow-through.",
                    source_unit_ids=beat.source_unit_ids,
                    artifact_ids=[beat.id],
                    evidence=[
                        "The reveal sequence has no explicit "
                        + " or ".join(missing)
                        + " beat before the next transition."
                    ],
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
