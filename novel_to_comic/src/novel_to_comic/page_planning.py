"""Global semantic page planning for the full-page pipeline."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from novel_to_comic.json_contract import describe_json_contract
from novel_to_comic.models.adaptation import BookAdaptation, LetteringItem
from novel_to_comic.models.page import (
    ApprovedPageRange,
    ApprovedVisualReferenceInventory,
    AuthorGeometryPin,
    BookPlan,
    ComicPage,
    PageContent,
    PinnedGeometry,
    PlannedPageRevision,
)
from novel_to_comic.models.validation import (
    EditorialIssue,
    InvariantFailure,
    StageValidation,
    ValidationAttempt,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, estimate_text_cost


_MAX_PLAN_ATTEMPTS = 2


class PlanValidation(BaseModel):
    """Plan-owned blocking failures and reviewable rhythm concerns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invariant_failures: tuple[InvariantFailure, ...] = ()
    editorial_issues: tuple[EditorialIssue, ...] = ()


class PlanInvariantError(ValueError):
    """Raised when a proposed global plan violates a Plan invariant."""

    def __init__(self, validation: PlanValidation) -> None:
        codes = ", ".join(
            failure.code for failure in validation.invariant_failures
        )
        super().__init__(f"Book plan has invariant failures: {codes}")
        self.validation = validation


class _PageContentDraft(BaseModel):
    """Plan allocates lettering by ID; the wording itself is never restated.

    Asking a model to copy every LetteringItem "byte-for-byte" made exact
    lettering a validation problem. Citing IDs and letting code copy the
    canonical item makes it a property of the artifact instead.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    beat_ids: tuple[str, ...] = Field(min_length=1)
    panel_role: Literal[
        "establishing",
        "standard",
        "detail",
        "reaction",
        "action",
        "transition",
        "splash",
        "inset",
    ] = "standard"
    visual_intent: str = Field(min_length=1)
    lettering_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    appearance_state_ids: tuple[str, ...] = ()


class _PageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    page_turn_role: Literal[
        "none", "setup", "reveal", "cliffhanger", "release", "transition"
    ] = "none"
    spread_role: Literal["single", "left", "right", "spread"] = "single"
    emphasis: Literal[
        "establisher",
        "initial",
        "prolongation",
        "peak",
        "release",
        "transition",
    ]
    density_intent: Literal["sparse", "standard", "dense"]
    rhythm_intent: str = Field(min_length=1)
    layout_intent: str = Field(min_length=1)
    content: tuple[_PageContentDraft, ...] = Field(min_length=1)
    reading_order: tuple[str, ...] = Field(min_length=1)


class _BookPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rhythm_summary: str = Field(min_length=1)
    pages: tuple[_PageDraft, ...] = Field(min_length=1)
    editorial_issues: tuple[EditorialIssue, ...] = ()

    @model_validator(mode="after")
    def _validate_issue_ownership(self) -> "_BookPlanDraft":
        if any(issue.owner_stage != "plan" for issue in self.editorial_issues):
            raise ValueError("book-plan editorial issues must be owned by Plan")
        return self


def _normalize_book_plan_draft(
    value: Mapping[str, Any],
    references: ApprovedVisualReferenceInventory,
) -> Mapping[str, Any]:
    """Canonicalize deterministic Plan-owned metadata before validation."""

    normalized = dict(value)
    issues = normalized.get("editorial_issues")
    if isinstance(issues, (list, tuple)):
        normalized["editorial_issues"] = [
            {**issue, "owner_stage": "plan"}
            if isinstance(issue, Mapping)
            else issue
            for issue in issues
        ]
    pages = normalized.get("pages")
    if not isinstance(pages, (list, tuple)):
        return normalized
    normalized["pages"] = _normalize_draft_references(pages, references)
    return normalized


def _normalize_draft_references(
    pages: list[Any] | tuple[Any, ...],
    references: ApprovedVisualReferenceInventory,
) -> list[Any]:
    reference_states = {
        reference.id: reference.appearance_state_id
        for reference in references.references
    }
    known_states = {
        state_id for state_id in reference_states.values() if state_id is not None
    }
    normalized_pages: list[Any] = []
    for page in pages:
        if not isinstance(page, Mapping):
            normalized_pages.append(page)
            continue
        normalized_page = dict(page)
        content_items = normalized_page.get("content")
        if not isinstance(content_items, (list, tuple)):
            normalized_pages.append(normalized_page)
            continue
        normalized_content: list[Any] = []
        for content in content_items:
            if not isinstance(content, Mapping):
                normalized_content.append(content)
                continue
            normalized_item = dict(content)
            state_ids = normalized_item.get("appearance_state_ids")
            if isinstance(state_ids, (list, tuple)):
                canonical_states: list[Any] = []
                for state_id in state_ids:
                    if state_id in known_states:
                        canonical = state_id
                    elif state_id in reference_states:
                        canonical = reference_states[state_id]
                    else:
                        canonical = state_id
                    if canonical is not None and canonical not in canonical_states:
                        canonical_states.append(canonical)
                normalized_item["appearance_state_ids"] = canonical_states
            normalized_content.append(normalized_item)
        normalized_page["content"] = normalized_content
        normalized_pages.append(normalized_page)
    return normalized_pages


StructuredGenerator = Callable[
    ...,
    Awaitable[ApiResult[Mapping[str, Any]]],
]


def build_book_plan_prompt(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    target_range: ApprovedPageRange,
) -> str:
    """Compile Plan's complete book-level allocation context."""

    context = {
        "book_adaptation": adaptation.model_dump(mode="json"),
        "approved_visual_reference_inventory": references.model_dump(mode="json"),
        "approved_target_page_range": target_range.model_dump(mode="json"),
    }
    page_range_instruction = (
        "The approved minimum is a narrative floor. Because this adaptation is "
        "allowed to expand for fidelity, keep every page needed for safe, legible "
        "storytelling even when the allocation exceeds the approved maximum. "
        if target_range.allow_expansion
        else "Stay within the approved target page range unless the complete safe "
        "allocation proves that the range is insufficient. "
    )
    overflow_instruction = (
        "Do not compress required content to fit the approved maximum; return the "
        "complete safe allocation and let the resulting page count expand. "
        if target_range.allow_expansion
        else "If required content cannot fit safely inside the approved range, "
        "return the complete safe allocation even when it exceeds the maximum; "
        "Plan will report the evidenced conflict and recommended minimum. "
    )
    return (
        "Allocate the single ordered BookAdaptation globally into canonical comic "
        "pages. Each content item is one planned semantic panel in reading order, "
        "not an independently generated image. Allocate every adapted beat at least "
        "once and in order. A panel may cite an adapted beat again only on an "
        "immediately adjacent panel or page when decompression reveals a distinct "
        "visual submoment supported by that beat and its source; never return to a "
        "beat after advancing beyond it. Allocate "
        "lettering by citing LetteringItem IDs in lettering_ids, on the same page "
        "content item as the beat that owns them, in reading order; never copy, "
        "rewrite, shorten, clip, or omit the wording itself. Every lettering ID of "
        "an allocated beat must be cited exactly once. Pages may bridge "
        "source-scene boundaries. Group adjacent story beats into varied multi-panel "
        "pages when that preserves action, reaction, detail, causality, and rhythm. "
        "Reserve one-panel pages and splash panels for exceptional peaks, reveals, "
        "or deliberate pauses; do not make them the default page grammar. Author a "
        "panel_role for every content item and ensure layout_intent describes those "
        "same ordered panels. appearance_state_ids contains only the inventory's "
        "appearance_state_id values (for example, feverish), never reference IDs "
        "(for example, char_003:feverish); omit base references because base is not "
        "an appearance state. Own actual page count, "
        + page_range_instruction
        + " "
        "page and spread rhythm, page-turn intent, explicit reading order, narrative "
        "emphasis, semantic density and layout intent, and page-scoped approved "
        "entity and appearance-state IDs. Sparse, standard, and dense are semantic "
        "intent, not panel-count or word-count caps. "
        + overflow_instruction
        + "Do not use templates, split beats mechanically, "
        "assign fixed character positions, create scene-local pagination, add exact "
        "coordinates, reconcile scene plans, or write image provider prompts. "
        "Return only the global page-plan JSON object.\n"
        + describe_json_contract(_BookPlanDraft)
        + "\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


async def produce_book_plan(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    target_range: ApprovedPageRange,
    /,
    *,
    artifacts: TargetArtifacts,
    ctx: StageRuntime,
    model: str,
    generate: StructuredGenerator,
    author_pins: tuple[AuthorGeometryPin, ...] | list[AuthorGeometryPin] = (),
) -> BookPlan:
    """Generate, validate, and persist one global canonical book plan."""

    pin_by_beat = _validate_author_pins(adaptation, author_pins)
    prompt = build_book_plan_prompt(adaptation, references, target_range)
    estimate = estimate_text_cost(
        model,
        prompt,
        output_chars=max(8_000, len(adaptation.beats) * 2_000),
    )
    with ctx.execute(total=1, estimated_cost_usd=estimate):
        attempt_prompt = prompt
        pages: tuple[ComicPage, ...] = ()
        validation = PlanValidation()
        valid_fallback: (
            tuple[_BookPlanDraft, tuple[ComicPage, ...], PlanValidation] | None
        ) = None
        history: list[ValidationAttempt] = []
        for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
            result = await generate(
                system_prompt=(
                    "You are the sole global page architect for a complete comic book."
                ),
                user_content=attempt_prompt,
                feature="plan.book",
            )
            # A retried attempt was still paid for, so its usage is recorded
            # without counting a completed item.
            if result.usage is not None:
                ctx.record_api_usage(result.usage)
            try:
                draft = _BookPlanDraft.model_validate(
                    _normalize_book_plan_draft(
                        result.value,
                        references,
                    )
                )
            except ValidationError as error:
                if attempt == _MAX_PLAN_ATTEMPTS:
                    if valid_fallback is not None:
                        draft, pages, validation = valid_fallback
                        ctx.record_item_done()
                        break
                    raise
                attempt_prompt = _schema_repair_prompt(prompt, result.value, error)
                continue
            try:
                pages = _canonical_pages(adaptation, draft, pin_by_beat)
            except PlanInvariantError as allocation_error:
                validation = allocation_error.validation
            except ValidationError as error:
                validation = _canonical_page_validation(error)
            else:
                validation = validate_book_plan(
                    adaptation,
                    references,
                    target_range,
                    pages,
                )
                validation = PlanValidation(
                    invariant_failures=validation.invariant_failures,
                    editorial_issues=_merged_editorial_issues(
                        validation.editorial_issues,
                        draft.editorial_issues,
                        adaptation=adaptation,
                        pages=pages,
                    ),
                )
            history.append(_attempt_record(attempt, validation))
            if not validation.invariant_failures:
                retryable_issues = tuple(
                    issue
                    for issue in validation.editorial_issues
                    if issue.code
                    in {
                        "repetitive_page_composition",
                        "density_mismatch",
                    }
                )
                if retryable_issues and attempt < _MAX_PLAN_ATTEMPTS:
                    valid_fallback = (draft, pages, validation)
                    attempt_prompt = _editorial_repair_prompt(
                        prompt,
                        result.value,
                        retryable_issues,
                    )
                    continue
                ctx.record_item_done()
                break
            if attempt < _MAX_PLAN_ATTEMPTS:
                attempt_prompt = _repair_prompt(prompt, result.value, validation)
        if validation.invariant_failures and valid_fallback is not None:
            draft, pages, validation = valid_fallback
            ctx.record_item_done()
        ctx.progress(1, 1)

        _persist_validation(
            artifacts, validation, attempts=attempt, history=tuple(history)
        )
        if validation.invariant_failures:
            raise PlanInvariantError(validation)

        plan = BookPlan(
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            # With expansion approved, the recorded range follows the allocation
            # in both directions: the beats decide the page count, not an
            # estimate made before they existed. The shortfall is reported as an
            # editorial issue instead of failing the stage.
            target_page_min=(
                min(target_range.minimum, len(pages))
                if target_range.allow_expansion
                else target_range.minimum
            ),
            target_page_max=(
                max(target_range.maximum, len(pages))
                if target_range.allow_expansion
                else target_range.maximum
            ),
            rhythm_summary=draft.rhythm_summary,
            pages=[
                PlannedPageRevision(
                    page_number=page.page_number,
                    revision=page.revision,
                    content_sha256=page.content_sha256,
                )
                for page in pages
            ],
            editorial_issues=validation.editorial_issues,
        )
        for page in pages:
            artifacts.write_page(page)
        artifacts.write_plan(plan)
    return plan


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
    prompt: str,
    raw: object,
    validation: PlanValidation,
) -> str:
    failures = "\n".join(
        f"- [{failure.code}] {failure.message} " + " ".join(failure.evidence)
        for failure in validation.invariant_failures
    )
    return (
        f"{prompt}\n\nYour previous global page plan violated these blocking "
        "contract requirements. Return one complete corrected JSON object that "
        "preserves its valid decisions and resolves every failure.\n\n"
        "YOUR PREVIOUS JSON:\n"
        f"{json.dumps(raw, indent=2, default=str)}\n\n"
        "BLOCKING CONTRACT FAILURES:\n"
        f"{failures}"
    )


def _editorial_repair_prompt(
    prompt: str,
    raw: object,
    issues: tuple[EditorialIssue, ...],
) -> str:
    concerns = "\n".join(
        f"- [{issue.code}] {issue.message} " + " ".join(issue.evidence)
        for issue in issues
    )
    return (
        f"{prompt}\n\nYour previous global page plan is contract-valid but its "
        "page grammar has these evidence-backed editorial concerns. Return one "
        "complete corrected JSON object that preserves all story content, exact "
        "lettering allocation, page order, and valid rhythm decisions while "
        "introducing purposeful semantic panel variety. Do not add panels merely "
        "to satisfy a count; each added panel must depict a distinct visual "
        "submoment supported by its cited beat and source.\n\n"
        "YOUR PREVIOUS JSON:\n"
        f"{json.dumps(raw, indent=2, default=str)}\n\n"
        "EDITORIAL CONCERNS:\n"
        f"{concerns}"
    )


def _canonical_page_validation(error: ValidationError) -> PlanValidation:
    """Translate canonical model errors into repairable Plan-owned failures."""

    return PlanValidation(
        invariant_failures=(
            InvariantFailure(
                id="plan_failure_canonical_page_contract",
                owner_stage="plan",
                code="canonical_page_contract",
                message="The proposed allocation does not form valid canonical pages.",
                evidence=[str(error)],
            ),
        )
    )


def _attempt_record(attempt: int, validation: PlanValidation) -> ValidationAttempt:
    return ValidationAttempt(
        attempt=attempt,
        invariant_codes=tuple(
            failure.code for failure in validation.invariant_failures
        ),
        editorial_codes=tuple(issue.code for issue in validation.editorial_issues),
    )


def _persist_validation(
    artifacts: TargetArtifacts,
    validation: PlanValidation,
    *,
    attempts: int,
    history: tuple[ValidationAttempt, ...] = (),
) -> None:
    """Persist Plan's verdict, including any page-range recommendation.

    A range conflict is the one blocking failure the user can actually act on,
    and its recommendation only exists inside the failure evidence — so it is
    written down before the stage raises.
    """

    # A range conflict is the one blocking failure the user can act on. A floor
    # shortfall under approved expansion is not blocking, but it is still a
    # brief decision, so its recommendation is surfaced the same way.
    recommendations = tuple(
        evidence
        for failure in validation.invariant_failures
        if failure.code == "target_page_range_conflict"
        for evidence in failure.evidence
    ) + tuple(
        evidence
        for issue in validation.editorial_issues
        if issue.code == "page_count_below_floor"
        for evidence in issue.evidence
    )
    artifacts.write_validation(
        StageValidation(
            owner_stage="plan",
            attempts=attempts,
            invariant_failures=validation.invariant_failures,
            editorial_issues=validation.editorial_issues,
            recommendations=recommendations,
            attempt_history=history,
        )
    )


def _merged_editorial_issues(
    derived: tuple[EditorialIssue, ...],
    authored: tuple[EditorialIssue, ...],
    *,
    adaptation: BookAdaptation,
    pages: tuple[ComicPage, ...],
) -> tuple[EditorialIssue, ...]:
    """Keep model-authored issues only when their citations actually resolve.

    A reviewable exception is only useful if the user can open what it cites,
    and a derived issue always wins an ID collision.
    """

    known_ids = {
        *(beat.id for beat in adaptation.beats),
        *(f"page_{page.page_number:03d}" for page in pages),
        *(content.id for page in pages for content in page.content),
        *(
            lettering.id
            for page in pages
            for content in page.content
            for lettering in content.lettering
        ),
    }
    known_units = {
        source_unit_id
        for beat in adaptation.beats
        for source_unit_id in beat.source_unit_ids
    }
    merged = {issue.id: issue for issue in derived}
    upstream_issue_ids = {issue.id for issue in adaptation.editorial_issues}
    for issue in authored:
        if issue.id in merged or issue.id in upstream_issue_ids:
            continue
        if any(artifact_id not in known_ids for artifact_id in issue.artifact_ids):
            continue
        if any(unit_id not in known_units for unit_id in issue.source_unit_ids):
            continue
        merged[issue.id] = issue
    return tuple(merged.values())


def _canonical_pages(
    adaptation: BookAdaptation,
    draft: "_BookPlanDraft",
    pin_by_beat: dict[str, AuthorGeometryPin],
) -> tuple[ComicPage, ...]:
    """Materialize canonical pages, copying Adapt's lettering by ID."""

    canonical_lettering: dict[str, LetteringItem] = {
        item.id: item for beat in adaptation.beats for item in beat.lettering
    }
    owning_beat: dict[str, str] = {
        item.id: beat.id for beat in adaptation.beats for item in beat.lettering
    }
    claimed: set[str] = set()
    pages: list[ComicPage] = []
    for page in draft.pages:
        content_items: list[PageContent] = []
        for content in page.content:
            lettering: list[LetteringItem] = []
            for lettering_id in content.lettering_ids:
                item = canonical_lettering.get(lettering_id)
                if item is None:
                    raise PlanInvariantError(
                        PlanValidation(
                            invariant_failures=(
                                InvariantFailure(
                                    id=f"plan_failure_unknown_lettering_{lettering_id}",
                                    owner_stage="plan",
                                    code="unknown_lettering",
                                    message=(
                                        "Page content cites lettering absent from the "
                                        "BookAdaptation."
                                    ),
                                    artifact_ids=[content.id, lettering_id],
                                    evidence=[
                                        f"Lettering {lettering_id!r} does not exist in "
                                        f"Adapt revision {adaptation.revision}."
                                    ],
                                ),
                            )
                        )
                    )
                if lettering_id in claimed:
                    raise PlanInvariantError(
                        PlanValidation(
                            invariant_failures=(
                                InvariantFailure(
                                    id=f"plan_failure_duplicate_lettering_{lettering_id}",
                                    owner_stage="plan",
                                    code="duplicate_lettering",
                                    message="Lettering may be allocated to one page only.",
                                    artifact_ids=[content.id, lettering_id],
                                    evidence=[
                                        f"Lettering {lettering_id!r} was already "
                                        "allocated earlier in the book."
                                    ],
                                ),
                            )
                        )
                    )
                if owning_beat[lettering_id] not in content.beat_ids:
                    raise PlanInvariantError(
                        PlanValidation(
                            invariant_failures=(
                                InvariantFailure(
                                    id=f"plan_failure_lettering_owner_{lettering_id}",
                                    owner_stage="plan",
                                    code="lettering_beat_mismatch",
                                    message=(
                                        "Lettering must be allocated with the beat that "
                                        "owns it."
                                    ),
                                    artifact_ids=[
                                        content.id,
                                        lettering_id,
                                        owning_beat[lettering_id],
                                    ],
                                    evidence=[
                                        f"Lettering {lettering_id!r} belongs to beat "
                                        f"{owning_beat[lettering_id]!r}, which content "
                                        f"{content.id!r} does not carry."
                                    ],
                                ),
                            )
                        )
                    )
                claimed.add(lettering_id)
                lettering.append(item)
            payload = content.model_dump(exclude={"lettering_ids"})
            content_items.append(
                PageContent(
                    **payload,
                    lettering=tuple(lettering),
                    pinned_geometry=_geometry_for_content(
                        content.beat_ids,
                        pin_by_beat,
                    ),
                )
            )
        pages.append(
            ComicPage(
                revision=1,
                page_number=page.page_number,
                adaptation_revision=adaptation.revision,
                adaptation_sha256=adaptation.content_sha256,
                page_turn_role=page.page_turn_role,
                spread_role=page.spread_role,
                emphasis=page.emphasis,
                density_intent=page.density_intent,
                rhythm_intent=page.rhythm_intent,
                layout_intent=page.layout_intent,
                content=content_items,
                reading_order=_canonical_reading_order(
                    page.reading_order,
                    content_items,
                ),
            )
        )
    return tuple(pages)


def _canonical_reading_order(
    authored: tuple[str, ...],
    content: list[PageContent],
) -> tuple[str, ...]:
    """Complete mechanically required IDs without replacing authored order."""

    expected = [
        ordered_id
        for item in content
        for ordered_id in (item.id, *(lettering.id for lettering in item.lettering))
    ]
    known = set(expected)
    reading_order: list[str] = []
    for ordered_id in authored:
        if ordered_id in known and ordered_id not in reading_order:
            reading_order.append(ordered_id)

    for expected_index, ordered_id in enumerate(expected):
        if ordered_id in reading_order:
            continue
        preceding = next(
            (
                candidate
                for candidate in reversed(expected[:expected_index])
                if candidate in reading_order
            ),
            None,
        )
        if preceding is not None:
            reading_order.insert(reading_order.index(preceding) + 1, ordered_id)
            continue
        following = next(
            (
                candidate
                for candidate in expected[expected_index + 1 :]
                if candidate in reading_order
            ),
            None,
        )
        if following is None:
            reading_order.append(ordered_id)
        else:
            reading_order.insert(reading_order.index(following), ordered_id)
    return tuple(reading_order)


def _validate_author_pins(
    adaptation: BookAdaptation,
    author_pins: tuple[AuthorGeometryPin, ...] | list[AuthorGeometryPin],
) -> dict[str, AuthorGeometryPin]:
    known_beats = {beat.id for beat in adaptation.beats}
    pin_by_beat: dict[str, AuthorGeometryPin] = {}
    for pin in author_pins:
        if pin.beat_id not in known_beats:
            raise ValueError(f"author pin references unknown beat {pin.beat_id!r}")
        if pin.beat_id in pin_by_beat:
            raise ValueError(f"adapted beat {pin.beat_id!r} has multiple author pins")
        pin_by_beat[pin.beat_id] = pin
    return pin_by_beat


def _geometry_for_content(
    beat_ids: tuple[str, ...],
    pin_by_beat: dict[str, AuthorGeometryPin],
) -> PinnedGeometry | None:
    geometries = [
        pin_by_beat[beat_id].geometry
        for beat_id in beat_ids
        if beat_id in pin_by_beat
    ]
    if not geometries:
        return None
    if any(geometry != geometries[0] for geometry in geometries[1:]):
        raise ValueError("one page-content item cannot contain conflicting author pins")
    return geometries[0]


def validate_book_plan(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    target_range: ApprovedPageRange,
    pages: tuple[ComicPage, ...] | list[ComicPage],
) -> PlanValidation:
    """Validate canonical pages against Plan's three authoritative inputs."""

    failures: list[InvariantFailure] = []
    issues: list[EditorialIssue] = []
    for page in pages:
        if (
            page.adaptation_revision != adaptation.revision
            or page.adaptation_sha256 != adaptation.content_sha256
        ):
            failures.append(
                InvariantFailure(
                    id=(
                        "plan_failure_adaptation_authority_mismatch_"
                        f"page_{page.page_number:03d}"
                    ),
                    owner_stage="plan",
                    code="adaptation_authority_mismatch",
                    message="Canonical pages must cite the current BookAdaptation.",
                    artifact_ids=[f"page_{page.page_number:03d}"],
                    evidence=[
                        f"Expected Adapt revision/hash {adaptation.revision}/"
                        f"{adaptation.content_sha256}; found "
                        f"{page.adaptation_revision}/"
                        f"{page.adaptation_sha256}."
                    ],
                )
            )

    expected_beats = [beat.id for beat in adaptation.beats]
    actual_beats = [
        beat_id
        for page in pages
        for content in page.content
        for beat_id in content.beat_ids
    ]
    expected_position = {
        beat_id: position for position, beat_id in enumerate(expected_beats)
    }
    actual_positions = [
        expected_position[beat_id]
        for beat_id in actual_beats
        if beat_id in expected_position
    ]
    allocation_is_complete_and_monotonic = (
        len(actual_positions) == len(actual_beats)
        and set(actual_beats) == set(expected_beats)
        and actual_positions == sorted(actual_positions)
    )
    if not allocation_is_complete_and_monotonic:
        failures.append(
            InvariantFailure(
                id="plan_failure_beat_allocation",
                owner_stage="plan",
                code="beat_allocation",
                message=(
                    "Every adapted beat must be allocated at least once and remain "
                    "in story order."
                ),
                artifact_ids=actual_beats,
                evidence=[
                    f"Expected complete monotonic beat order {expected_beats!r}; "
                    f"found {actual_beats!r}."
                ],
            )
        )

    expected_lettering = [
        item.model_dump(mode="json")
        for beat in adaptation.beats
        for item in beat.lettering
    ]
    actual_lettering = [
        item.model_dump(mode="json")
        for page in pages
        for content in page.content
        for item in content.lettering
    ]
    if actual_lettering != expected_lettering:
        failures.append(
            InvariantFailure(
                id="plan_failure_lettering_changed",
                owner_stage="plan",
                code="lettering_changed",
                message="Plan must allocate Adapt lettering without changing it.",
                artifact_ids=[
                    item["id"] for item in expected_lettering + actual_lettering
                ],
                evidence=[
                    "The ordered LetteringItem records differ from BookAdaptation."
                ],
            )
        )

    # Ordered equality above proves no wording changed, but it flattens across
    # pages: moving a balloon onto a neighbouring beat's content item preserves
    # the flat order while lettering the wrong panel. Association is checked
    # separately against the beat that owns each item.
    owning_beat = {
        item.id: beat.id for beat in adaptation.beats for item in beat.lettering
    }
    for page in pages:
        for content in page.content:
            misattached = [
                item.id
                for item in content.lettering
                if owning_beat.get(item.id) not in content.beat_ids
            ]
            if misattached:
                failures.append(
                    InvariantFailure(
                        id=f"plan_failure_lettering_beat_mismatch_{content.id}",
                        owner_stage="plan",
                        code="lettering_beat_mismatch",
                        message="Lettering must stay with the beat that owns it.",
                        artifact_ids=[
                            content.id,
                            *misattached,
                            *(
                                owning_beat[item_id]
                                for item_id in misattached
                                if item_id in owning_beat
                            ),
                        ],
                        evidence=[
                            f"Content {content.id!r} carries beats "
                            f"{list(content.beat_ids)!r} but letters "
                            f"{misattached!r}, owned by "
                            + repr(
                                [owning_beat.get(item_id) for item_id in misattached]
                            )
                            + "."
                        ],
                    )
                )

    page_numbers = [page.page_number for page in pages]
    if page_numbers != list(range(1, len(pages) + 1)):
        failures.append(
            InvariantFailure(
                id="plan_failure_page_order",
                owner_stage="plan",
                code="page_order",
                message="Canonical page numbers must be consecutive and ordered.",
                artifact_ids=[str(number) for number in page_numbers],
                evidence=[f"Found page order {page_numbers!r}."],
            )
        )

    for previous, current in zip(pages, pages[1:], strict=False):
        if (
            previous.spread_role in {"left", "right"}
            and current.spread_role == previous.spread_role
        ):
            failures.append(
                InvariantFailure(
                    id=(
                        "plan_failure_page_spread_order_"
                        f"{previous.page_number:03d}_{current.page_number:03d}"
                    ),
                    owner_stage="plan",
                    code="page_spread_order",
                    message="Facing-page spread sides must remain ordered.",
                    artifact_ids=[
                        f"page_{previous.page_number:03d}",
                        f"page_{current.page_number:03d}",
                    ],
                    evidence=[
                        f"Pages {previous.page_number} and {current.page_number} "
                        f"both declare spread side {current.spread_role!r}."
                    ],
                )
            )

    for page in pages:
        expected_content_order = [content.id for content in page.content]
        expected_lettering_order = [
            lettering.id
            for content in page.content
            for lettering in content.lettering
        ]
        content_ids = set(expected_content_order)
        lettering_ids = set(expected_lettering_order)
        actual_content_order = [
            ordered_id
            for ordered_id in page.reading_order
            if ordered_id in content_ids
        ]
        actual_lettering_order = [
            ordered_id
            for ordered_id in page.reading_order
            if ordered_id in lettering_ids
        ]
        if (
            actual_content_order != expected_content_order
            or actual_lettering_order != expected_lettering_order
        ):
            failures.append(
                InvariantFailure(
                    id=f"plan_failure_reading_order_page_{page.page_number:03d}",
                    owner_stage="plan",
                    code="reading_order",
                    message=(
                        "Canonical reading order must preserve page content and "
                        "Adapt lettering order."
                    ),
                    artifact_ids=[f"page_{page.page_number:03d}"],
                    evidence=[
                        f"Expected content order {expected_content_order!r} "
                        f"and lettering order {expected_lettering_order!r}; "
                        f"found content order {actual_content_order!r} and "
                        f"lettering order {actual_lettering_order!r}."
                    ],
                )
            )

    if (
        not target_range.allow_expansion
        and not target_range.minimum <= len(pages) <= target_range.maximum
    ):
        failures.append(
            InvariantFailure(
                id="plan_failure_target_page_range",
                owner_stage="plan",
                code="target_page_range_conflict",
                message="Required content cannot fit safely in the approved page range.",
                artifact_ids=expected_beats,
                evidence=[
                    f"The complete allocation requires {len(pages)} pages; "
                    f"the approved range is {target_range.minimum}-"
                    f"{target_range.maximum}. Recommend a minimum of {len(pages)} pages."
                ],
            )
        )
    elif target_range.allow_expansion and len(pages) < target_range.minimum:
        # The floor was approved before any beats existed; Plan allocated the
        # adaptation that actually got written. Padding to reach a stale
        # estimate would manufacture pages the story does not have, so this is
        # recorded for review rather than repaired — but recorded by us, not
        # left to whether the model volunteers it.
        issues.append(
            EditorialIssue(
                id="plan_issue_page_count_below_floor",
                owner_stage="plan",
                code="page_count_below_floor",
                message="The complete allocation is below the approved page floor.",
                artifact_ids=["plan_book"],
                evidence=[
                    f"The complete allocation is {len(pages)} pages; the "
                    f"approved floor is {target_range.minimum}. Recommend "
                    f"lowering the approved minimum to {len(pages)} pages."
                ],
            )
        )

    single_panel_run: list[ComicPage] = []
    for page in (*pages, None):
        if page is not None and len(page.content) == 1:
            single_panel_run.append(page)
            continue
        if len(single_panel_run) >= 4:
            page_ids = [
                f"page_{candidate.page_number:03d}"
                for candidate in single_panel_run
            ]
            issues.append(
                EditorialIssue(
                    id=(
                        "plan_issue_repetitive_page_composition_"
                        f"{single_panel_run[0].page_number:03d}_"
                        f"{single_panel_run[-1].page_number:03d}"
                    ),
                    owner_stage="plan",
                    code="repetitive_page_composition",
                    message=(
                        "A long run of one-panel pages may rush story detail while "
                        "giving every beat the same visual weight."
                    ),
                    artifact_ids=page_ids,
                    evidence=[
                        f"Pages {single_panel_run[0].page_number}-"
                        f"{single_panel_run[-1].page_number} each contain one "
                        "planned panel.",
                        "Single-panel and splash pages should be deliberate "
                        "exceptions within the book's broader page rhythm.",
                    ],
                )
            )
        single_panel_run = []

    for page in pages:
        if page.density_intent == "dense" and len(page.content) == 1:
            issues.append(
                EditorialIssue(
                    id=f"plan_issue_density_mismatch_page_{page.page_number:03d}",
                    owner_stage="plan",
                    code="density_mismatch",
                    message=(
                        "A dense page declares only one planned panel, so its "
                        "structured composition may not express its density intent."
                    ),
                    artifact_ids=[f"page_{page.page_number:03d}", page.content[0].id],
                    evidence=[
                        f"Page {page.page_number} is dense but contains one "
                        f"{page.content[0].panel_role!r} panel."
                    ],
                )
            )

    known_entities = {reference.entity_id for reference in references.references}
    known_states = {
        reference.appearance_state_id
        for reference in references.references
        if reference.appearance_state_id is not None
    }
    state_owners = {
        reference.appearance_state_id: reference.entity_id
        for reference in references.references
        if reference.appearance_state_id is not None
    }
    unknown_entities = sorted(
        {
            entity_id
            for page in pages
            for content in page.content
            for entity_id in content.entity_ids
            if entity_id not in known_entities
        }
    )
    unknown_states = sorted(
        {
            state_id
            for page in pages
            for content in page.content
            for state_id in content.appearance_state_ids
            if state_id not in known_states
        }
    )
    if unknown_entities or unknown_states:
        failures.append(
            InvariantFailure(
                id="plan_failure_reference_authority",
                owner_stage="plan",
                code="reference_authority",
                message="Page-scoped references must resolve in the approved inventory.",
                artifact_ids=unknown_entities + unknown_states,
                evidence=[
                    f"Unknown entity IDs: {unknown_entities!r}.",
                    f"Unknown appearance-state IDs: {unknown_states!r}.",
                ],
            )
        )

    for page in pages:
        for content in page.content:
            for state_id in content.appearance_state_ids:
                owner_id = state_owners.get(state_id)
                if owner_id is not None and owner_id not in content.entity_ids:
                    failures.append(
                        InvariantFailure(
                            id=(
                                "plan_failure_reference_state_owner_"
                                f"{content.id}_{state_id}"
                            ),
                            owner_stage="plan",
                            code="reference_authority",
                            message=(
                                "A page-scoped appearance state must cite its "
                                "authoritative entity."
                            ),
                            artifact_ids=[content.id, owner_id, state_id],
                            evidence=[
                                f"Appearance state {state_id!r} belongs to "
                                f"{owner_id!r}, which is absent from content "
                                f"{content.id!r}."
                            ],
                        )
                    )

    beat_by_id = {beat.id: beat for beat in adaptation.beats}
    for page in pages:
        for content in page.content:
            for beat_id in content.beat_ids:
                beat = beat_by_id.get(beat_id)
                if beat is None:
                    continue
                for change in beat.appearance_changes:
                    if (
                        change.entity_id not in content.entity_ids
                        or change.to_state_id not in content.appearance_state_ids
                    ):
                        failures.append(
                            InvariantFailure(
                                id=(
                                    "plan_failure_appearance_state_allocation_"
                                    f"{beat.id}"
                                ),
                                owner_stage="plan",
                                code="appearance_state_allocation",
                                message=(
                                    "Appearance-state changes must be explicit in "
                                    "the page-scoped references."
                                ),
                                source_unit_ids=beat.source_unit_ids,
                                artifact_ids=[
                                    beat.id,
                                    change.entity_id,
                                    change.to_state_id,
                                    content.id,
                                ],
                                evidence=[
                                    f"Beat {beat.id!r} activates "
                                    f"{change.to_state_id!r} for "
                                    f"{change.entity_id!r}, but content "
                                    f"{content.id!r} does not cite both IDs."
                                ],
                            )
                        )

    for page_index, page in enumerate(pages):
        page_beats = [
            beat_by_id[beat_id]
            for content in page.content
            for beat_id in content.beat_ids
            if beat_id in beat_by_id
        ]
        peak_beats = [
            beat for beat in page_beats if beat.narrative_function == "peak"
        ]
        release_beats = [
            beat
            for beat in page_beats
            if beat.narrative_function == "release"
            or "aftermath" in beat.story_functions
        ]
        represented_emphasis = {
            beat.narrative_function for beat in page_beats
        }
        if page_beats and page.emphasis not in represented_emphasis:
            issues.append(
                EditorialIssue(
                    id=(
                        "plan_issue_emphasis_mismatch_"
                        f"page_{page.page_number:03d}"
                    ),
                    owner_stage="plan",
                    code="emphasis_mismatch",
                    message="Page emphasis may not match its adapted beats.",
                    source_unit_ids=[
                        source_unit_id
                        for beat in page_beats
                        for source_unit_id in beat.source_unit_ids
                    ],
                    artifact_ids=[
                        f"page_{page.page_number:03d}",
                        *(beat.id for beat in page_beats),
                    ],
                    evidence=[
                        f"Page {page.page_number} declares emphasis "
                        f"{page.emphasis!r}; its beats declare "
                        f"{sorted(represented_emphasis)!r}."
                    ],
                )
            )
        # A page holding both a Peak and its Release is only a proportion
        # problem when neither gets room of its own: sharing one content item,
        # or a page with no space to separate them. Flagging every
        # co-occurrence buries the pages that genuinely rush the beat.
        shares_content = any(
            any(beat_by_id.get(beat_id) in peak_beats for beat_id in content.beat_ids)
            and any(
                beat_by_id.get(beat_id) in release_beats
                for beat_id in content.beat_ids
            )
            for content in page.content
        )
        crowded = (
            shares_content
            or page.density_intent == "dense"
            or len(page.content) <= 2
        )
        if peak_beats and release_beats and crowded:
            peak_ids = [beat.id for beat in peak_beats]
            release_ids = [beat.id for beat in release_beats]
            issues.append(
                EditorialIssue(
                    id=(
                        "plan_issue_poor_peak_release_proportion_"
                        f"page_{page.page_number:03d}"
                    ),
                    owner_stage="plan",
                    code="poor_peak_release_proportion",
                    message="Peak and Release may not have distinct page weight.",
                    source_unit_ids=[
                        source_unit_id
                        for beat in (*peak_beats, *release_beats)
                        for source_unit_id in beat.source_unit_ids
                    ],
                    artifact_ids=[
                        f"page_{page.page_number:03d}",
                        *peak_ids,
                        *release_ids,
                    ],
                    evidence=[
                        f"Page {page.page_number} combines Peak beat(s) "
                        f"{peak_ids!r} with Release/aftermath beat(s) "
                        f"{release_ids!r}."
                    ],
                )
            )
        reveal_beats = [
            beat
            for beat in page_beats
            if "reveal" in beat.story_functions
            and beat.narrative_function == "peak"
        ]
        if not reveal_beats or page_index == 0:
            continue
        previous = pages[page_index - 1]
        if (
            previous.page_turn_role not in {"setup", "cliffhanger"}
            and page.page_turn_role != "reveal"
        ):
            for beat in reveal_beats:
                issues.append(
                    EditorialIssue(
                        id=f"plan_issue_weak_page_turn_{beat.id}",
                        owner_stage="plan",
                        code="weak_page_turn",
                        message="A reveal lacks an intentional page-turn setup.",
                        source_unit_ids=beat.source_unit_ids,
                        artifact_ids=[beat.id, f"page_{page.page_number:03d}"],
                        evidence=[
                            f"Reveal beat {beat.id!r} starts page "
                            f"{page.page_number}, but page "
                            f"{previous.page_number} has page-turn role "
                            f"{previous.page_turn_role!r} and page "
                            f"{page.page_number} has role "
                            f"{page.page_turn_role!r}."
                        ],
                    )
                )

    return PlanValidation(
        invariant_failures=failures,
        editorial_issues=issues,
    )
