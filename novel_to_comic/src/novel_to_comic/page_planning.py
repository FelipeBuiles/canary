"""Global semantic page planning for the full-page pipeline."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from novel_to_comic.ai.context import ai_source_context
from novel_to_comic.narrative_instructions import PLAN_DEPICTION_GUIDANCE
from novel_to_comic.editorial import story_instruction_section
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
from novel_to_comic.narrative_review import planning_context, review_narrative
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.paid_shards import run_paid_shards
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, estimate_text_cost


_MAX_PLAN_ATTEMPTS = 2
_TWO_PASS_PLAN_MIN_BEATS = 24
_PLAN_DETAIL_BATCH_PAGES = 8


class PlanValidation(BaseModel):
    """Plan-owned blocking failures and reviewable rhythm concerns."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invariant_failures: tuple[InvariantFailure, ...] = ()
    editorial_issues: tuple[EditorialIssue, ...] = ()


class PlanInvariantError(ValueError):
    """Raised when a proposed global plan violates a Plan invariant."""

    def __init__(self, validation: PlanValidation) -> None:
        codes = ", ".join(failure.code for failure in validation.invariant_failures)
        super().__init__(f"Book plan has invariant failures: {codes}")
        self.validation = validation


class _AppearanceStateBinding(BaseModel):
    """One entity-scoped appearance citation in the private LLM draft."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(min_length=1)
    state_id: str = Field(min_length=1)


class _PageContentDraft(BaseModel):
    """Plan allocates lettering by ID; the wording itself is never restated.

    Asking a model to copy every LetteringItem "byte-for-byte" made exact
    lettering a validation problem. Citing IDs and letting code copy the
    canonical item makes it a property of the artifact instead.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = "auto"
    order: int = 1
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
    continuity_intent: str = ""
    lettering_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    appearance_states: tuple[_AppearanceStateBinding, ...] = ()

    @model_validator(mode="after")
    def _validate_appearance_state_bindings(self) -> "_PageContentDraft":
        seen: set[str] = set()
        for binding in self.appearance_states:
            if binding.entity_id in seen:
                raise ValueError(
                    "appearance state bindings must have unique entity IDs"
                )
            seen.add(binding.entity_id)
        return self


class _PageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = 1
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
    reading_order: tuple[str, ...] = ()


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


class _PageMapEntry(BaseModel):
    """Compact global rhythm decision; local panel detail is authored later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = 1
    beat_ids: tuple[str, ...] = Field(min_length=1)
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


class _BookPageMap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rhythm_summary: str = Field(min_length=1)
    pages: tuple[_PageMapEntry, ...] = Field(min_length=1)


def _normalize_book_plan_draft(
    value: Mapping[str, Any],
    adaptation: BookAdaptation,
    *,
    page_number_offset: int = 0,
) -> Mapping[str, Any]:
    """Canonicalize deterministic Plan-owned metadata before validation."""

    normalized = dict(value)
    issues = normalized.get("editorial_issues")
    if isinstance(issues, (list, tuple)):
        normalized["editorial_issues"] = [
            {**issue, "owner_stage": "plan"} if isinstance(issue, Mapping) else issue
            for issue in issues
        ]
    pages = normalized.get("pages")
    if not isinstance(pages, (list, tuple)):
        return normalized
    normalized_pages = list(pages)
    lettering_by_beat = {
        beat.id: tuple(item.id for item in beat.lettering) for beat in adaptation.beats
    }
    lettering_order = {
        item.id: position
        for position, item in enumerate(
            item for beat in adaptation.beats for item in beat.lettering
        )
    }
    explicitly_placed = {
        lettering_id
        for page in normalized_pages
        if isinstance(page, Mapping)
        for content in page.get("content", ())
        if isinstance(content, Mapping)
        for lettering_id in content.get("lettering_ids", ())
    }
    allocated_lettering: set[str] = set()
    for local_page_number, page in enumerate(normalized_pages, 1):
        if not isinstance(page, Mapping):
            continue
        page_number = page_number_offset + local_page_number
        normalized_page = dict(page)
        normalized_page["page_number"] = page_number
        content_items = normalized_page.get("content")
        if not isinstance(content_items, list):
            continue
        normalized_content: list[Any] = []
        reading_order: list[str] = []
        for order, content in enumerate(content_items, 1):
            if not isinstance(content, Mapping):
                normalized_content.append(content)
                continue
            normalized_item = dict(content)
            content_id = f"page_{page_number:03d}_content_{order:03d}"
            normalized_item["id"] = content_id
            normalized_item["order"] = order
            cited = list(
                dict.fromkeys(normalized_item.get("lettering_ids") or ())
            )
            cited = [
                lettering_id
                for lettering_id in cited
                if lettering_id not in allocated_lettering
            ]
            for beat_id in normalized_item.get("beat_ids") or ():
                for lettering_id in lettering_by_beat.get(beat_id, ()):
                    if (
                        lettering_id not in allocated_lettering
                        and lettering_id not in explicitly_placed
                        and lettering_id not in cited
                    ):
                        cited.append(lettering_id)
            cited.sort(
                key=lambda lettering_id: lettering_order.get(
                    lettering_id,
                    len(lettering_order),
                )
            )
            normalized_item["lettering_ids"] = cited
            allocated_lettering.update(cited)
            reading_order.extend((content_id, *cited))
            normalized_content.append(normalized_item)
        normalized_page["content"] = normalized_content
        normalized_page["reading_order"] = reading_order
        normalized_pages[local_page_number - 1] = normalized_page
    _canonicalize_lettering_placement_order(normalized_pages, lettering_by_beat)
    normalized["pages"] = normalized_pages
    return normalized


def _canonicalize_lettering_placement_order(
    pages: list[Any],
    lettering_by_beat: Mapping[str, tuple[str, ...]],
) -> None:
    """Keep each beat's lettering in Adapt order across repeated panels.

    A repeated beat may legitimately span multiple adjacent content items. The
    model can therefore cite that beat's lettering on different items, but it
    must not be able to reverse the canonical records between those items. The
    slots are kept where the model placed them; only IDs owned by the same beat
    are redistributed in Adapt order. If a malformed response is missing a
    slot, leave it for the existing invariant path to attribute and report.
    """

    owner_by_lettering = {
        lettering_id: beat_id
        for beat_id, lettering_ids in lettering_by_beat.items()
        for lettering_id in lettering_ids
    }
    for beat_id, canonical_ids in lettering_by_beat.items():
        if not canonical_ids:
            continue
        slots: list[tuple[list[Any], int]] = []
        for page in pages:
            if not isinstance(page, Mapping):
                continue
            content_items = page.get("content")
            if not isinstance(content_items, list):
                continue
            for content in content_items:
                if not isinstance(content, Mapping):
                    continue
                ids = content.get("lettering_ids")
                if not isinstance(ids, list):
                    continue
                for index, lettering_id in enumerate(ids):
                    if owner_by_lettering.get(lettering_id) == beat_id:
                        slots.append((ids, index))
        if len(slots) != len(canonical_ids):
            continue
        for (ids, index), lettering_id in zip(slots, canonical_ids, strict=True):
            ids[index] = lettering_id
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        content_items = page.get("content")
        if not isinstance(content_items, list):
            continue
        reading_order: list[str] = []
        for content in content_items:
            if not isinstance(content, Mapping):
                continue
            content_id = content.get("id")
            if isinstance(content_id, str):
                reading_order.append(content_id)
            lettering_ids = content.get("lettering_ids")
            if isinstance(lettering_ids, list):
                reading_order.extend(
                    lettering_id
                    for lettering_id in lettering_ids
                    if isinstance(lettering_id, str)
                )
        page["reading_order"] = reading_order


StructuredGenerator = Callable[
    ...,
    Awaitable[ApiResult[Mapping[str, Any]]],
]


def _planning_view(adaptation: BookAdaptation) -> dict[str, Any]:
    """Compile only the narrative authority Plan actually reasons over."""

    return {
        "treatment": adaptation.treatment.model_dump(
            mode="json",
            exclude={
                "essential_events",
                "character_turns",
            },
        ),
        "beats": [
            {
                "id": beat.id,
                "summary": beat.summary,
                "entity_ids": beat.entity_ids,
                "narrative_function": beat.narrative_function,
                "story_functions": beat.story_functions,
                "brief_requirement_ids": beat.brief_requirement_ids,
                "lettering": [
                    item.model_dump(
                        mode="json",
                        exclude={"source_unit_ids"},
                    )
                    for item in beat.lettering
                ],
                "transitions": [
                    transition.model_dump(mode="json")
                    for transition in beat.transitions
                ],
                "appearance_changes": [
                    change.model_dump(mode="json") for change in beat.appearance_changes
                ],
            }
            for beat in adaptation.beats
        ],
    }


def _reference_view(
    references: ApprovedVisualReferenceInventory,
    entity_ids: set[str] | None = None,
) -> list[dict[str, str | None]]:
    """Keep the identity mapping Plan needs while excluding approval metadata."""

    return [
        {
            "id": reference.id,
            "entity_id": reference.entity_id,
            "appearance_state_id": reference.appearance_state_id,
            "label": reference.label,
            "visual_anchor": reference.visual_anchor,
            "continuity_guard": reference.continuity_guard,
        }
        for reference in references.references
        if entity_ids is None or reference.entity_id in entity_ids
    ]

_SEMANTIC_PAGE_CONTRACT = (
    "For each panel author continuity_intent as non-lettering direction: the established "
    "start and resulting end scene, actor staging, and important held-object ownership, "
    "using only the ordered Adapt summaries and transitions. Carry completed arrivals, "
    "departures, and transfers forward across panels and pages until changed; do not "
    "re-enact a completed entrance. Do not invent positions, possessions, or transitions "
    "where the source is silent; leave unestablished composition to Draw. Never use "
    "previous generated pixels as continuity authority. "
    "appearance_states is an ordered list of bindings, each with entity_id and "
    'state_id, for example [{"entity_id":"character_1","state_id":"injured"}]. '
    "Bind each visible entity at most once to its approved entity-scoped state ID; "
    "different entities may share the same state ID. Omit base appearances from "
    "the list and use [] when no explicit bindings are needed. "
    "Explicit Adapt appearance changes own activation timing "
    "and persist until changed. visual_intent and continuity_intent must agree with "
    "that state, including time of day: do not introduce dusk before its activation. "
    "Keep approved anchors and continuity guards verbatim and respect their action "
    "constraints. Describe relative composition, narrative emphasis, and panel roles; "
    "do not prescribe templates, fixed positions, exact boxes or coordinates, or "
    "provider prompts. Only explicit author geometry pins own exact placement. "
    "Code assigns each beat's complete exact lettering to its first occurrence. "
    "Supply lettering_ids only to move items to another adjacent occurrence of "
    "the same beat; each item must occur once, in Adapt order, without rewriting. "
    "Stage on-screen speakers visibly; off-screen speech must not point at a visible "
    "character. Silent sequences are valid when action, causality, and transitions "
    "remain self-explanatory; otherwise regroup complete beats or report missing "
    "canonical narrative context, never invent copy. "
)



def build_book_plan_prompt(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    target_range: ApprovedPageRange,
) -> str:
    """Compile Plan's complete book-level allocation context."""

    context = {
        "planning_view": _planning_view(adaptation),
        "approved_visual_reference_inventory": _reference_view(references),
        "approved_target_page_range": target_range.model_dump(mode="json"),
    }
    page_range_instruction = (
        "The target page range is advisory, not a floor or ceiling. Choose the "
        "length the story earns, even below the minimum or above the maximum. "
        "Never pad the ending or compress essential context to hit a number. "
    )
    overflow_instruction = (
        "Explain the actual allocation in rhythm_summary, including any departure "
        "from the target. Distribute space by dramatic importance across the whole "
        "book; one beat does not imply one page. "
    )
    return (
        "Allocate the single ordered BookAdaptation globally into canonical comic "
        "pages. Each content item is one planned semantic panel in reading order, "
        "not an independently generated image. Allocate every adapted beat at least "
        "once and in order. A panel may cite an adapted beat again only on an "
        "immediately adjacent panel or page when decompression reveals a distinct "
        "visual submoment supported by that beat and its source; never return to a "
        "beat after advancing beyond it. "
        + _SEMANTIC_PAGE_CONTRACT
        + "Pages may bridge "
        "source-scene boundaries. Group adjacent story beats into varied multi-panel "
        "pages when that preserves action, reaction, detail, causality, and rhythm. "
        "Reserve one-panel pages and splash panels for exceptional peaks, reveals, "
        "or deliberate pauses; do not make them the default page grammar. Author a "
        "panel_role for every content item and ensure layout_intent describes those "
        "same ordered panels. Cite visible entities beyond explicit appearance changes. "
        "Own actual page count, "
        + page_range_instruction
        + " "
        "page and spread rhythm, page-turn intent, narrative "
        "emphasis, semantic density and layout intent, and page-scoped approved "
        "entity and appearance-state IDs. Sparse, standard, and dense are semantic "
        "intent, not panel-count or word-count caps. "
        + overflow_instruction
        + "Page numbers, content IDs, content order, and reading_order are "
        "deterministic: omit them or return provisional values because code "
        "canonicalizes them. Return only the global page-plan JSON object. "
        + PLAN_DEPICTION_GUIDANCE
        + "\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _build_page_map_prompt(
    adaptation: BookAdaptation,
    target_range: ApprovedPageRange,
) -> str:
    return (
        "Create the compact global page map for this complete graphic novel. "
        "Allocate every beat at least once, in order, without returning to an "
        "earlier beat after advancing. Own book-wide page count, page turns, "
        "spreads, emphasis, density, and rhythm. The target range is advisory, "
        "not a floor or ceiling. Use fewer or more pages when the story requires. "
        "Never pad a closing beat to meet a minimum. Preserve investigation, causality, reactions, and "
        "aftermath rather than compressing toward the maximum. A repeated beat "
        "is allowed only on an immediately adjacent page when decompression "
        "creates a distinct visual submoment. Do not author panels, visual "
        "intent, entity placement, lettering allocation, or geometry yet. Page "
        "numbers are canonicalized by code. Return only the page-map JSON. "
        + PLAN_DEPICTION_GUIDANCE
        + "\n"
        + json.dumps(
            {
                "planning_view": _planning_view(adaptation),
                "approved_target_page_range": target_range.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _canonicalize_page_map(value: Mapping[str, Any]) -> _BookPageMap:
    normalized = dict(value)
    pages = normalized.get("pages")
    if isinstance(pages, (list, tuple)):
        normalized["pages"] = [
            {**page, "page_number": page_number} if isinstance(page, Mapping) else page
            for page_number, page in enumerate(pages, 1)
        ]
    return _BookPageMap.model_validate(normalized)


def _validate_page_map(
    adaptation: BookAdaptation,
    target_range: ApprovedPageRange,
    page_map: _BookPageMap,
) -> PlanValidation:
    expected = tuple(beat.id for beat in adaptation.beats)
    allocated = tuple(beat_id for page in page_map.pages for beat_id in page.beat_ids)
    failures: list[InvariantFailure] = []
    unknown = tuple(
        dict.fromkeys(beat_id for beat_id in allocated if beat_id not in expected)
    )
    positions = {beat_id: index for index, beat_id in enumerate(expected)}
    known_positions = [
        positions[beat_id] for beat_id in allocated if beat_id in positions
    ]
    if (
        unknown
        or set(allocated) != set(expected)
        or any(
            later < earlier
            for earlier, later in zip(known_positions, known_positions[1:])
        )
    ):
        failures.append(
            InvariantFailure(
                id="plan_map_failure_beat_allocation",
                owner_stage="plan",
                code="beat_allocation",
                message="The global page map must allocate every beat in order.",
                artifact_ids=expected,
                evidence=[
                    f"Expected ordered beats {list(expected)!r}; page map allocated "
                    f"{list(allocated)!r}. Unknown beats: {list(unknown)!r}."
                ],
            )
        )
    return PlanValidation(invariant_failures=tuple(failures))


def _detail_batch_prompt(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    page_map: _BookPageMap,
    *,
    start: int,
    stop: int,
    concerns: tuple[InvariantFailure | EditorialIssue, ...] = (),
) -> str:
    target_pages = page_map.pages[start:stop]
    context_start = max(0, start - 1)
    context_stop = min(len(page_map.pages), stop + 1)
    target_beat_ids = {beat_id for page in target_pages for beat_id in page.beat_ids}
    planning = _planning_view(adaptation)
    first_target = next(
        (index for index, beat in enumerate(planning["beats"]) if beat["id"] in target_beat_ids),
        len(planning["beats"]),
    )
    planning["established_continuity"] = [
        {key: beat[key] for key in ("id", "summary", "transitions", "appearance_changes")}
        for beat in planning["beats"][:first_target]
    ]
    planning["beats"] = [
        beat for beat in planning["beats"] if beat["id"] in target_beat_ids
    ]
    # Only prune when every target beat has an authored entity scope. Empty
    # scopes need the complete inventory so a visual-only scene is not starved.
    scoped = planning["beats"]
    entity_scope = ({entity_id for beat in scoped for entity_id in beat["entity_ids"]}
                    if scoped and all(beat["entity_ids"] for beat in scoped) else None)
    if entity_scope is not None:
        for beat in scoped:
            entity_scope.update(change["entity_id"] for change in beat["appearance_changes"])
            entity_scope.update(item["speaker_entity_id"] for item in beat["lettering"] if item.get("speaker_entity_id"))
    concern_text = ""
    if concerns:
        concern_text = (
            " Repair these evidence-backed concerns while preserving the fixed "
            "page map: "
            + " ".join(
                f"[{concern.code}] {concern.message} {' '.join(concern.evidence)}"
                for concern in concerns
            )
        )
    return (
        f"Expand only page-map entries {start + 1}-{stop} into semantic comic "
        "panels. The global page count, beat allocation, page turns, emphasis, "
        "density, and rhythm are fixed authority. Return exactly the target pages, "
        "not the neighboring context pages. Each target page's panels must jointly "
        "carry exactly that page-map entry's beat_ids in order. Group or repeat a "
        "beat within the page only for distinct supported visual submoments. Author "
        "panel_role, visual_intent, continuity_intent, visible entity_ids, and layout_intent. "
        "Code canonicalizes page numbers, content IDs/order, and reading order. "
        + _SEMANTIC_PAGE_CONTRACT
        + "Reserve one-panel pages for exceptional moments."
        + concern_text
        + " "
        + PLAN_DEPICTION_GUIDANCE
        + "\n"
        + json.dumps(
            {
                "global_rhythm_summary": page_map.rhythm_summary,
                "neighboring_page_map_context": [
                    page.model_dump(mode="json")
                    for page in page_map.pages[context_start:context_stop]
                ],
                "target_page_numbers": [page.page_number for page in target_pages],
                "planning_view": planning,
                "approved_visual_reference_inventory": _reference_view(references, entity_scope),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def estimate_book_plan_cost(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    target_range: ApprovedPageRange,
    *,
    model: str,
    story_instruction: str = "",
) -> float:
    """Estimate the selected internal workflow, including bounded detail calls."""

    instruction_suffix = story_instruction_section(story_instruction, stage="plan")
    review_allowance = estimate_text_cost(
        model, adaptation.model_dump_json() * 2,
        output_chars=max(10_000, len(adaptation.beats) * 2_000),
    ) * 2
    if len(adaptation.beats) < _TWO_PASS_PLAN_MIN_BEATS:
        prompt = build_book_plan_prompt(
            adaptation, references, target_range
        ) + instruction_suffix
        return estimate_text_cost(
            model,
            prompt,
            output_chars=max(8_000, len(adaptation.beats) * 2_000),
        ) + review_allowance
    page_count = max(
        target_range.minimum,
        (len(adaptation.beats) + 1) // 2,
    )
    beats = adaptation.beats
    projected_pages: list[_PageMapEntry] = []
    for index in range(page_count):
        start = min(len(beats) - 1, (index * len(beats)) // page_count)
        stop = min(
            len(beats),
            max(start + 1, ((index + 1) * len(beats)) // page_count),
        )
        carried = beats[start:stop]
        authority = carried[-1]
        projected_pages.append(
            _PageMapEntry(
                page_number=index + 1,
                beat_ids=tuple(beat.id for beat in carried),
                emphasis=authority.narrative_function,
                density_intent="standard",
                rhythm_intent=authority.summary,
            )
        )
    page_map = _BookPageMap(
        rhythm_summary="Projected cost map.",
        pages=tuple(projected_pages),
    )
    map_prompt = _build_page_map_prompt(
        adaptation, target_range
    ) + instruction_suffix
    total = estimate_text_cost(
        model,
        map_prompt,
        output_chars=max(4_000, page_count * 350),
    )
    for start in range(0, page_count, _PLAN_DETAIL_BATCH_PAGES):
        stop = min(start + _PLAN_DETAIL_BATCH_PAGES, page_count)
        total += estimate_text_cost(
            model,
            _detail_batch_prompt(
                adaptation,
                references,
                page_map,
                start=start,
                stop=stop,
            )
            + instruction_suffix,
            output_chars=max(4_000, (stop - start) * 1_600),
        )
    return total + review_allowance


def _validate_plan_draft(adaptation, references, target_range, draft, pin_by_beat):
    pages = _canonical_pages(adaptation, draft, pin_by_beat, references)
    validation = validate_book_plan(adaptation, references, target_range, pages)
    return pages, PlanValidation(
        invariant_failures=validation.invariant_failures,
        editorial_issues=_merged_editorial_issues(validation.editorial_issues,
            draft.editorial_issues, adaptation=adaptation, pages=pages),
    )


def _write_valid_plan(*, artifacts, adaptation, target_range, pages, rhythm_summary, validation) -> BookPlan:
    """Publish the same canonical contract for small and batched books."""
    plan = BookPlan(
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        target_page_min=target_range.minimum,
        target_page_max=target_range.maximum,
        rhythm_summary=rhythm_summary,
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


async def _produce_book_plan_one_shot(
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
    story_instruction: str = "",
) -> BookPlan:
    """Generate, validate, and persist one global canonical book plan."""

    pin_by_beat = _validate_author_pins(adaptation, author_pins)
    prompt = build_book_plan_prompt(
        adaptation, references, target_range
    ) + story_instruction_section(story_instruction, stage="plan")
    estimate = estimate_book_plan_cost(adaptation, references, target_range,
                                      model=model, story_instruction=story_instruction)
    with ctx.execute(total=1, estimated_cost_usd=estimate):
        attempt_prompt = prompt
        pages: tuple[ComicPage, ...] = ()
        validation = PlanValidation()
        valid_fallback: (
            tuple[_BookPlanDraft, tuple[ComicPage, ...], PlanValidation] | None
        ) = None
        history: list[ValidationAttempt] = []
        for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
            with ai_source_context("book", tuple(dict.fromkeys(
                unit_id for beat in adaptation.beats for unit_id in beat.source_unit_ids
            ))):
                result = await generate(
                    system_prompt=(
                        "You are the sole global page architect for a complete comic book."
                    ),
                    user_content=attempt_prompt,
                    feature="plan.book",
                    json_schema=_BookPlanDraft.model_json_schema(),
                )
            # A retried attempt was still paid for, so its usage is recorded
            # without counting a completed item.
            if result.usage is not None:
                ctx.record_api_usage(result.usage)
            try:
                draft = _BookPlanDraft.model_validate(
                    _normalize_book_plan_draft(
                        result.value,
                        adaptation,
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
                pages, validation = _validate_plan_draft(adaptation, references, target_range, draft, pin_by_beat)
            except PlanInvariantError as allocation_error:
                validation = allocation_error.validation
            except ValidationError as error:
                validation = _canonical_page_validation(error)
            if not validation.invariant_failures:
                review_failures = await review_narrative(
                    planning_context(adaptation, pages), generate=generate, ctx=ctx,
                    artifacts=artifacts, model=model, instruction=story_instruction,
                )
                validation = validation.model_copy(update={"invariant_failures": review_failures})
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
            if any(f.code == "narrative_review_invalid" for f in validation.invariant_failures):
                break
            if all(
                failure.owner_stage != "plan"
                for failure in validation.invariant_failures
            ):
                # Nothing Plan can re-allocate would clear these, so stop paying
                # for attempts and let the owning stage be re-run instead.
                break
            if attempt < _MAX_PLAN_ATTEMPTS:
                attempt_prompt = _repair_prompt(prompt, result.value, validation)
        if validation.invariant_failures and valid_fallback is not None:
            draft, pages, validation = valid_fallback
            ctx.record_item_done()
        ctx.progress(1, 1)

        if not validation.invariant_failures:
            review_failures = await review_narrative(
                planning_context(adaptation, pages), generate=generate, ctx=ctx,
                artifacts=artifacts, model=model, instruction=story_instruction,
            )
            validation = validation.model_copy(update={"invariant_failures": review_failures})
        _persist_validation(
            artifacts, validation, attempts=attempt, history=tuple(history)
        )
        if validation.invariant_failures:
            raise PlanInvariantError(validation)

        plan = _write_valid_plan(artifacts=artifacts, adaptation=adaptation,
            target_range=target_range, pages=pages, rhythm_summary=draft.rhythm_summary,
            validation=validation)
    return plan


def _record_plan_usage(ctx: StageRuntime, result: ApiResult[Any]) -> None:
    for usage in (result.usage, *result.additional_usage):
        if usage is not None:
            ctx.record_api_usage(usage)


async def _generate_page_map(
    adaptation: BookAdaptation,
    target_range: ApprovedPageRange,
    *,
    generate: StructuredGenerator,
    ctx: StageRuntime,
    artifacts: TargetArtifacts,
    model: str,
    story_instruction: str = "",
    review_instruction: str | None = None,
) -> tuple[_BookPageMap, list[ValidationAttempt]]:
    prompt = _build_page_map_prompt(
        adaptation, target_range
    ) + story_instruction_section(story_instruction, stage="plan")
    attempt_prompt = prompt
    history: list[ValidationAttempt] = []
    page_map: _BookPageMap | None = None
    for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
        with ai_source_context("page_map", tuple(dict.fromkeys(
            unit_id for beat in adaptation.beats for unit_id in beat.source_unit_ids
        ))):
            result = await generate(
                system_prompt=(
                    "You are the global rhythm architect for a complete comic book."
                ),
                user_content=attempt_prompt,
                feature="plan.map",
                json_schema=_BookPageMap.model_json_schema(),
            )
        _record_plan_usage(ctx, result)
        try:
            page_map = _canonicalize_page_map(result.value)
        except ValidationError as error:
            if attempt == _MAX_PLAN_ATTEMPTS:
                raise
            attempt_prompt = _schema_repair_prompt(prompt, result.value, error)
            continue
        validation = _validate_page_map(adaptation, target_range, page_map)
        if not validation.invariant_failures:
            review_failures = await review_narrative(
                planning_context(adaptation, page_map.pages, phase="plan_map"),
                generate=generate, ctx=ctx, artifacts=artifacts, model=model, instruction=story_instruction if review_instruction is None else review_instruction,
            )
            validation = validation.model_copy(update={"invariant_failures": review_failures})
        history.append(_attempt_record(attempt, validation))
        if not validation.invariant_failures:
            return page_map, history
        if any(f.owner_stage != "plan" or f.code == "narrative_review_invalid" for f in validation.invariant_failures):
            raise PlanInvariantError(validation)
        if attempt == _MAX_PLAN_ATTEMPTS:
            raise PlanInvariantError(validation)
        attempt_prompt = (
            prompt
            + "\n\nRepair the compact page map. Return a complete corrected map, "
            "preserving valid global rhythm decisions.\nPREVIOUS PAGE MAP:\n"
            + page_map.model_dump_json()
            + "\nFAILURES:\n"
            + "\n".join(
                f"[{failure.code}] {failure.message} " + " ".join(failure.evidence)
                for failure in validation.invariant_failures
            )
        )
    raise AssertionError("page-map loop must return or raise")


def _detail_matches_map(
    draft: _BookPlanDraft,
    target_pages: tuple[_PageMapEntry, ...],
) -> tuple[str, ...]:
    errors: list[str] = []
    if len(draft.pages) != len(target_pages):
        errors.append(
            f"Expected {len(target_pages)} pages; received {len(draft.pages)}."
        )
        return tuple(errors)
    for page, mapped in zip(draft.pages, target_pages, strict=True):
        actual = tuple(
            beat_id for content in page.content for beat_id in content.beat_ids
        )
        allocated = tuple(
            dict.fromkeys(actual)
        )
        if allocated != mapped.beat_ids:
            errors.append(
                f"Page {mapped.page_number} must carry {list(mapped.beat_ids)!r}; "
                f"detail carried {list(allocated)!r}."
            )
            continue
        positions = {
            beat_id: position for position, beat_id in enumerate(mapped.beat_ids)
        }
        actual_positions = [positions[beat_id] for beat_id in actual]
        if any(
            later < earlier
            for earlier, later in zip(actual_positions, actual_positions[1:])
        ):
            errors.append(
                f"Page {mapped.page_number} must carry its mapped beats in "
                f"monotonic order; detail cited {list(actual)!r}."
            )
    return tuple(errors)


async def _generate_detail_batch(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    page_map: _BookPageMap,
    *,
    start: int,
    stop: int,
    generate: StructuredGenerator,
    ctx: StageRuntime,
    concerns: tuple[InvariantFailure | EditorialIssue, ...] = (),
    story_instruction: str = "",
) -> _BookPlanDraft:
    base_prompt = _detail_batch_prompt(
        adaptation,
        references,
        page_map,
        start=start,
        stop=stop,
        concerns=concerns,
    ) + story_instruction_section(story_instruction, stage="plan")
    attempt_prompt = base_prompt
    target_beat_ids = {
        beat_id for page in page_map.pages[start:stop] for beat_id in page.beat_ids
    }
    source_unit_ids = tuple(dict.fromkeys(
        unit_id
        for beat in adaptation.beats if beat.id in target_beat_ids
        for unit_id in beat.source_unit_ids
    ))
    for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
        with ai_source_context(f"pages_{start + 1}-{stop}", source_unit_ids):
            result = await generate(
                system_prompt=(
                    "You are the local page-composition architect working under a "
                    "fixed global comic-book page map."
                ),
                user_content=attempt_prompt,
                feature="plan.detail",
                json_schema=_BookPlanDraft.model_json_schema(),
            )
        _record_plan_usage(ctx, result)
        try:
            draft = _BookPlanDraft.model_validate(result.value)
        except ValidationError as error:
            if attempt == _MAX_PLAN_ATTEMPTS:
                raise
            attempt_prompt = _schema_repair_prompt(
                base_prompt,
                result.value,
                error,
            )
            continue
        errors = _detail_matches_map(draft, page_map.pages[start:stop])
        if not errors:
            return draft
        if attempt == _MAX_PLAN_ATTEMPTS:
            raise PlanInvariantError(
                PlanValidation(
                    invariant_failures=(
                        InvariantFailure(
                            id=f"plan_detail_failure_{start + 1}_{stop}",
                            owner_stage="plan",
                            code="beat_allocation",
                            message=(
                                "Page detail must preserve its fixed global "
                                "page-map allocation."
                            ),
                            artifact_ids=[
                                f"page_{number:03d}"
                                for number in range(start + 1, stop + 1)
                            ],
                            evidence=errors,
                        ),
                    )
                )
            )
        attempt_prompt = (
            base_prompt
            + "\n\nYour previous detail changed the fixed page map. Return only "
            "corrected target-page detail.\nERRORS:\n" + "\n".join(errors)
        )
    raise AssertionError("detail loop must return or raise")


def _merge_detail_drafts(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    page_map: _BookPageMap,
    batches: list[tuple[int, int, _BookPlanDraft]],
) -> _BookPlanDraft:
    raw_pages: list[dict[str, Any]] = []
    authored_issues: list[EditorialIssue] = []
    for start, stop, batch in sorted(batches):
        authored_issues.extend(batch.editorial_issues)
        for mapped, page in zip(
            page_map.pages[start:stop],
            batch.pages,
            strict=True,
        ):
            raw_pages.append(
                {
                    **page.model_dump(mode="json"),
                    "page_number": mapped.page_number,
                    "page_turn_role": mapped.page_turn_role,
                    "spread_role": mapped.spread_role,
                    "emphasis": mapped.emphasis,
                    "density_intent": mapped.density_intent,
                    "rhythm_intent": mapped.rhythm_intent,
                }
            )
    normalized = _normalize_book_plan_draft(
        {
            "rhythm_summary": page_map.rhythm_summary,
            "pages": raw_pages,
            "editorial_issues": [
                issue.model_dump(mode="json") for issue in authored_issues
            ],
        },
        adaptation,
    )
    return _BookPlanDraft.model_validate(normalized)


def _concern_batch_indexes(
    concerns: tuple[InvariantFailure | EditorialIssue, ...],
    *,
    page_count: int,
) -> dict[int, list[InvariantFailure | EditorialIssue]]:
    grouped: dict[int, list[InvariantFailure | EditorialIssue]] = {}
    for concern in concerns:
        page_numbers = {
            int(match.group(1))
            for artifact_id in concern.artifact_ids
            if (match := re.fullmatch(r"page_(\d{3})(?:_content_\d{3})?", artifact_id))
        }
        for page_number in page_numbers:
            if 1 <= page_number <= page_count:
                index = (page_number - 1) // _PLAN_DETAIL_BATCH_PAGES
                grouped.setdefault(index, []).append(concern)
    return grouped


async def _produce_book_plan_two_pass(
    adaptation: BookAdaptation,
    references: ApprovedVisualReferenceInventory,
    target_range: ApprovedPageRange,
    *,
    artifacts: TargetArtifacts,
    ctx: StageRuntime,
    model: str,
    generate: StructuredGenerator,
    author_pins: tuple[AuthorGeometryPin, ...] | list[AuthorGeometryPin],
    story_instruction: str = "",
) -> BookPlan:
    author_instruction = story_instruction
    pin_by_beat = _validate_author_pins(adaptation, author_pins)
    estimate = estimate_book_plan_cost(
        adaptation,
        references,
        target_range,
        model=model,
        story_instruction=story_instruction,
    )
    with ctx.execute(total=0, estimated_cost_usd=estimate):
        prior_history: list[ValidationAttempt] = []
        for global_attempt in range(1, 3):
            try:
                page_map, history = await _generate_page_map(
                    adaptation,
                    target_range,
                    generate=generate,
                    ctx=ctx,
                    artifacts=artifacts,
                    model=model,
                    review_instruction=author_instruction,
                    story_instruction=story_instruction,
                )
            except PlanInvariantError as error:
                _persist_validation(
                    artifacts,
                    error.validation,
                    attempts=1,
                )
                raise
            ranges = [
                (start, min(start + _PLAN_DETAIL_BATCH_PAGES, len(page_map.pages)))
                for start in range(0, len(page_map.pages), _PLAN_DETAIL_BATCH_PAGES)
            ]
            # One step is reserved for canonicalization, validation, and artifact
            # persistence so the stage cannot report completion while that work is
            # still running.
            total_steps = ctx.stage_state.items_done + 2 + len(ranges)
            ctx.set_progress_total(total_steps)
            ctx.record_item_done()
            ctx.progress(ctx.stage_state.items_done, total_steps)

            async def generate_batch(
                start: int, stop: int
            ) -> tuple[int, int, _BookPlanDraft]:
                draft = await _generate_detail_batch(
                    adaptation,
                    references,
                    page_map,
                    start=start,
                    stop=stop,
                    generate=generate,
                    ctx=ctx,
                    story_instruction=story_instruction,
                )
                ctx.record_item_done()
                return start, stop, draft

            try:
                batches = await run_paid_shards(
                    [lambda start=start, stop=stop: generate_batch(start, stop)
                     for start, stop in ranges],
                    limit=4,
                )
            except PlanInvariantError as error:
                _persist_validation(
                    artifacts,
                    error.validation,
                    attempts=_MAX_PLAN_ATTEMPTS,
                )
                raise
            draft = _merge_detail_drafts(
                adaptation,
                references,
                page_map,
                batches,
            )
            pages, validation = _validate_plan_draft(adaptation, references, target_range, draft, pin_by_beat)
            if not validation.invariant_failures:
                review_failures = await review_narrative(
                    planning_context(adaptation, pages), generate=generate, ctx=ctx,
                    artifacts=artifacts, model=model, instruction=author_instruction,
                )
                validation = validation.model_copy(update={"invariant_failures": review_failures})


            repairable = (
                *(f for f in validation.invariant_failures if f.owner_stage == "plan"
                  and not f.code.startswith("narrative_review_")),
                *(
                    issue
                    for issue in validation.editorial_issues
                    if issue.code
                    in {
                        "repetitive_page_composition",
                        "density_mismatch",
                    }
                ),
            )
            grouped = _concern_batch_indexes(
                tuple(repairable),
                page_count=len(page_map.pages),
            )
            if grouped:
                total_steps += len(grouped)
                ctx.set_progress_total(total_steps)
                by_index = {
                    start // _PLAN_DETAIL_BATCH_PAGES: (start, stop, batch)
                    for start, stop, batch in batches
                }
                for index, concerns in grouped.items():
                    start, stop, _ = by_index[index]
                    repaired = await _generate_detail_batch(
                        adaptation,
                        references,
                        page_map,
                        start=start,
                        stop=stop,
                        generate=generate,
                        ctx=ctx,
                        concerns=tuple(concerns),
                        story_instruction=story_instruction,
                    )
                    ctx.record_item_done()
                    ctx.progress(ctx.stage_state.items_done, total_steps)
                    by_index[index] = (start, stop, repaired)
                batches = list(by_index.values())
                draft = _merge_detail_drafts(
                    adaptation,
                    references,
                    page_map,
                    batches,
                )
                pages, validation = _validate_plan_draft(adaptation, references, target_range, draft, pin_by_beat)

            if not validation.invariant_failures:
                review_failures = await review_narrative(
                    planning_context(adaptation, pages), generate=generate, ctx=ctx,
                    artifacts=artifacts, model=model, instruction=author_instruction,
                )
                validation = validation.model_copy(update={"invariant_failures": review_failures})
            history.append(_attempt_record(1 + bool(grouped), validation))
            if (global_attempt == 1 and validation.invariant_failures
                    and any(f.owner_stage == "plan" and f.code.startswith("narrative_review_")
                            and f.code != "narrative_review_invalid" for f in validation.invariant_failures)):
                # A structural defect must be allowed to change the global map,
                # not merely add panels inside the already defective allocation.
                prior_history.extend(history)
                story_instruction += "\nRepair the global narrative allocation, including page count and beat distribution:\n" + "\n".join(
                    " ".join(f.evidence) for f in validation.invariant_failures
                )
                continue
            history = [*prior_history, *history]
            _persist_validation(
                artifacts,
                validation,
                attempts=1 + bool(grouped),
                history=tuple(history),
            )
            if validation.invariant_failures:
                raise PlanInvariantError(validation)
            plan = _write_valid_plan(artifacts=artifacts, adaptation=adaptation,
                target_range=target_range, pages=pages, rhythm_summary=page_map.rhythm_summary,
                validation=validation)
            ctx.record_item_done()
            ctx.progress(total_steps, total_steps)
            break
    return plan


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
    story_instruction: str = "",
) -> BookPlan:
    """Produce one canonical plan through the cheapest quality-safe workflow."""

    from novel_to_comic.generation_checkpoints import checkpointed_generator
    generate = checkpointed_generator(generate, artifacts=artifacts, stage="plan", model=model)

    if len(adaptation.beats) < _TWO_PASS_PLAN_MIN_BEATS:
        return await _produce_book_plan_one_shot(
            adaptation,
            references,
            target_range,
            artifacts=artifacts,
            ctx=ctx,
            model=model,
            generate=generate,
            author_pins=author_pins,
            story_instruction=story_instruction,
        )
    return await _produce_book_plan_two_pass(
        adaptation,
        references,
        target_range,
        artifacts=artifacts,
        ctx=ctx,
        model=model,
        generate=generate,
        author_pins=author_pins,
        story_instruction=story_instruction,
    )


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
        "resolves every failure. Redistribute beats and lettering across the whole book, "
        "remove padding, and change page count when needed. Preserve exact words, "
        "story order, and source-supported events, not the defective allocation.\n\n"
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

    recommendations = tuple(
        evidence
        for failure in validation.invariant_failures
        if failure.code == "target_page_range_conflict"
        for evidence in failure.evidence
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


def _approved_state_pairs(
    references: ApprovedVisualReferenceInventory,
) -> set[tuple[str, str]]:
    """The (entity, appearance state) authorities Cast actually approved."""

    return {
        (reference.entity_id, reference.appearance_state_id)
        for reference in references.references
        if reference.appearance_state_id is not None
    }


def _derived_state_citations(
    content: "_PageContentDraft",
    beat_by_id: Mapping[str, Any],
    approved_pairs: set[tuple[str, str]],
) -> tuple[tuple[str, ...], dict[str, str], list[tuple[str, str, str]]]:
    """Fold each carried beat's appearance changes into the content citations.

    Which entity changes into which state on which beat is Adapt's decision,
    already recorded in the adaptation. Asking Plan to restate it made a
    derivable fact a blocking invariant (``appearance_state_allocation``) that
    a repair round had to pay for. Only pairs Cast approved are derived: an
    unapproved pair is a genuine Adapt/Cast disagreement, returned separately
    so it is attributed to the stage that can actually fix it.
    """

    entity_ids = list(content.entity_ids)
    states = {
        binding.entity_id: binding.state_id for binding in content.appearance_states
    }
    unapproved: list[tuple[str, str, str]] = []
    for beat_id in content.beat_ids:
        beat = beat_by_id.get(beat_id)
        if beat is None:
            continue
        for change in beat.appearance_changes:
            if (change.entity_id, change.to_state_id) not in approved_pairs:
                unapproved.append((beat_id, change.entity_id, change.to_state_id))
                continue
            if change.entity_id not in entity_ids:
                entity_ids.append(change.entity_id)
            states[change.entity_id] = change.to_state_id
    return tuple(entity_ids), states, unapproved


def _derived_speaker_citations(
    entity_ids: tuple[str, ...],
    lettering: tuple[LetteringItem, ...],
) -> tuple[str, ...]:
    """Make Adapt's on-screen speaker placement mechanically visible.

    ``speaker_entity_id`` and ``delivery`` are canonical Adapt decisions. The
    planner still authors the visual intent, but it must not pay for a repair
    merely because the model omitted the speaker from its derived entity list.
    """

    visible_entities = list(entity_ids)
    for item in lettering:
        if (
            item.delivery == "onscreen"
            and item.speaker_entity_id is not None
            and item.speaker_entity_id not in visible_entities
        ):
            visible_entities.append(item.speaker_entity_id)
    return tuple(visible_entities)


def _canonical_pages(
    adaptation: BookAdaptation,
    draft: "_BookPlanDraft",
    pin_by_beat: dict[str, AuthorGeometryPin],
    references: ApprovedVisualReferenceInventory,
) -> tuple[ComicPage, ...]:
    """Materialize canonical pages, copying Adapt's lettering by ID."""

    canonical_lettering: dict[str, LetteringItem] = {
        item.id: item for beat in adaptation.beats for item in beat.lettering
    }
    owning_beat: dict[str, str] = {
        item.id: beat.id for beat in adaptation.beats for item in beat.lettering
    }
    beat_by_id = {beat.id: beat for beat in adaptation.beats}
    approved_pairs = _approved_state_pairs(references)
    unapproved_changes: list[tuple[str, str, str]] = []
    claimed: set[str] = set()
    active_state_by_entity: dict[str, str] = {}
    applied_state_change_beats: set[str] = set()
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
            entity_ids, states, unapproved = _derived_state_citations(
                content,
                beat_by_id,
                approved_pairs,
            )
            entity_ids = _derived_speaker_citations(entity_ids, tuple(lettering))
            for beat_id in content.beat_ids:
                beat = beat_by_id.get(beat_id)
                if beat is None or beat_id in applied_state_change_beats:
                    continue
                for change in beat.appearance_changes:
                    if (change.entity_id, change.to_state_id) in approved_pairs:
                        active_state_by_entity[change.entity_id] = change.to_state_id
                applied_state_change_beats.add(beat_id)

            # Appearance changes are Adapt's canonical chronology. Once a
            # state is active, later page content that depicts the entity must
            # keep using that state authority until the next change. An
            # explicit state citation remains authoritative so timeline or
            # composite imagery can intentionally show an earlier look.
            for entity_id in entity_ids:
                if entity_id in active_state_by_entity:
                    states.setdefault(entity_id, active_state_by_entity[entity_id])
            unapproved_changes.extend(unapproved)
            payload = content.model_dump(
                exclude={"lettering_ids", "entity_ids", "appearance_states", "continuity_intent"}
            )
            content_items.append(
                PageContent(
                    **payload,
                    entity_ids=entity_ids,
                    appearance_states=states,
                    lettering=tuple(lettering),
                    pinned_geometry=_geometry_for_content(
                        content.beat_ids,
                        pin_by_beat,
                    ),
                )
            )
        continuity = [
            f"Panel {content.order}: {content.continuity_intent}"
            for content in sorted(page.content, key=lambda content: content.order)
            if content.continuity_intent.strip()
        ]
        layout_intent = page.layout_intent
        if continuity:
            layout_intent += "\n\nCanonical staging (non-lettering):\n" + "\n".join(continuity)
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
                layout_intent=layout_intent,
                content=content_items,
                reading_order=_canonical_reading_order(
                    page.reading_order,
                    content_items,
                ),
            )
        )
    if unapproved_changes:
        raise PlanInvariantError(
            PlanValidation(
                invariant_failures=tuple(
                    InvariantFailure(
                        id=(
                            "adapt_failure_unapproved_appearance_state_"
                            f"{beat_id}_{state_id}"
                        ),
                        # Owned by Adapt on purpose: no page allocation can make an
                        # unapproved (entity, state) pair valid, so repairing Plan
                        # would just burn another expensive attempt.
                        owner_stage="adapt",
                        code="unapproved_appearance_state",
                        message=(
                            "An adapted appearance change must cite a Cast-approved "
                            "entity appearance state."
                        ),
                        artifact_ids=[beat_id, entity_id, state_id],
                        evidence=[
                            f"Beat {beat_id!r} changes {entity_id!r} into "
                            f"{state_id!r}, which the approved reference "
                            "inventory does not contain."
                        ],
                    )
                    for beat_id, entity_id, state_id in unapproved_changes
                )
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
        pin_by_beat[beat_id].geometry for beat_id in beat_ids if beat_id in pin_by_beat
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
            for item in content.lettering:
                if (
                    item.delivery == "onscreen"
                    and item.speaker_entity_id not in content.entity_ids
                ):
                    failures.append(
                        InvariantFailure(
                            id=(
                                "plan_failure_lettering_speaker_visibility_"
                                f"{content.id}_{item.id}"
                            ),
                            owner_stage="plan",
                            code="lettering_speaker_visibility",
                            message=(
                                "On-screen lettering must be allocated to content "
                                "that visibly includes its speaker."
                            ),
                            source_unit_ids=item.source_unit_ids,
                            artifact_ids=[
                                content.id,
                                item.id,
                                item.speaker_entity_id or "<missing>",
                            ],
                            evidence=[
                                f"Lettering {item.id!r} identifies on-screen "
                                f"speaker {item.speaker_entity_id!r}, but content "
                                f"{content.id!r} cites visible entities "
                                f"{list(content.entity_ids)!r}."
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
            lettering.id for content in page.content for lettering in content.lettering
        ]
        content_ids = set(expected_content_order)
        lettering_ids = set(expected_lettering_order)
        actual_content_order = [
            ordered_id for ordered_id in page.reading_order if ordered_id in content_ids
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

    single_panel_run: list[ComicPage] = []
    for page in (*pages, None):
        if page is not None and len(page.content) == 1:
            single_panel_run.append(page)
            continue
        if len(single_panel_run) >= 4:
            page_ids = [
                f"page_{candidate.page_number:03d}" for candidate in single_panel_run
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
    known_states = _approved_state_pairs(references)
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
            f"{entity_id}:{state_id}"
            for page in pages
            for content in page.content
            for entity_id, state_id in content.appearance_states.items()
            if (entity_id, state_id) not in known_states
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
                        or content.appearance_states.get(change.entity_id) != change.to_state_id
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
        peak_beats = [beat for beat in page_beats if beat.narrative_function == "peak"]
        release_beats = [
            beat
            for beat in page_beats
            if beat.narrative_function == "release"
            or "aftermath" in beat.story_functions
        ]
        represented_emphasis = {beat.narrative_function for beat in page_beats}
        if page_beats and page.emphasis not in represented_emphasis:
            issues.append(
                EditorialIssue(
                    id=(f"plan_issue_emphasis_mismatch_page_{page.page_number:03d}"),
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
                beat_by_id.get(beat_id) in release_beats for beat_id in content.beat_ids
            )
            for content in page.content
        )
        crowded = (
            shares_content or page.density_intent == "dense" or len(page.content) <= 2
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
            if "reveal" in beat.story_functions and beat.narrative_function == "peak"
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
