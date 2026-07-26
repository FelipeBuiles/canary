"""Book-level Adapt production for the full-page pipeline."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

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
from novel_to_comic.models.validation import EditorialIssue, InvariantFailure
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, estimate_text_cost


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
        "and relative narrative emphasis. Use the approved target page range only "
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
        "appearance-state changes explicitly. Cite source-unit provenance and "
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
        treatment_result = await generate(
            system_prompt=(
                "You are the book-level narrative architect for a comic adaptation."
            ),
            user_content=treatment_prompt,
            json_schema=NarrativeTreatment.model_json_schema(),
            feature="adapt.narrative_treatment",
        )
        treatment = NarrativeTreatment.model_validate(treatment_result.value)
        ctx.record_item_done(usage=treatment_result.usage)
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
        book_result = await generate(
            system_prompt=(
                "You are the sole book-level Adapt writer. Return complete JSON."
            ),
            user_content=book_prompt,
            json_schema=_BookDraft.model_json_schema(),
            feature="adapt.book",
        )
        draft = _BookDraft.model_validate(book_result.value)
        ctx.record_item_done(usage=book_result.usage)
        ctx.progress(2, 2)

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
    complete_wording = "\n".join(item.text for item in lettering)
    missing_protected = [
        phrase
        for phrase in brief.protected_language
        if phrase not in complete_wording
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

    covered_requirements = {
        requirement
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
        missing_requirements = [
            requirement
            for requirement in requirements
            if (
                requirement not in treatment_requirements
                or requirement not in covered_requirements
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

    for entry in adaptation.ledger:
        if entry.disposition == "intentionally_omitted":
            issues.append(
                EditorialIssue(
                    id=f"adapt_issue_questionable_omission_{entry.source_unit_id}",
                    owner_stage="adapt",
                    code="questionable_omission",
                    message="An intentional omission is ready for editorial review.",
                    source_unit_ids=[entry.source_unit_id],
                    evidence=[
                        entry.reason or "No omission reason was recorded.",
                        entry.preserved_function,
                    ],
                )
            )

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
