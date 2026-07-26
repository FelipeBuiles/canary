from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from novel_to_comic.models.adaptation import (
    AdaptationLedgerEntry,
    AdaptedBeat,
    AppearanceChange,
    BookAdaptation,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.page import (
    ApprovedPageRange,
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
    AuthorGeometryPin,
    ComicPage,
    PageContent,
    PinnedGeometry,
)
from novel_to_comic.page_planning import (
    PlanInvariantError,
    produce_book_plan,
    validate_book_plan,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def _adaptation() -> BookAdaptation:
    lettering = (
        LetteringItem(
            id="lettering_0001",
            kind="caption",
            text="The reef rose before us.",
            source_unit_ids=["source_000001"],
        ),
        LetteringItem(
            id="lettering_0002",
            kind="dialogue",
            text="“Hard to port!”",
            speaker="Johansen",
            source_unit_ids=["source_000002"],
        ),
    )
    beats = (
        AdaptedBeat(
            id="beat_0001",
            order=1,
            summary="The Alert approaches the risen city.",
            narrative_function="prolongation",
            source_unit_ids=["source_000001"],
            lettering=[lettering[0]],
        ),
        AdaptedBeat(
            id="beat_0002",
            order=2,
            summary="Johansen turns the yacht away.",
            narrative_function="release",
            story_functions=["reaction"],
            source_unit_ids=["source_000002"],
            lettering=[lettering[1]],
        ),
    )
    return BookAdaptation(
        revision=2,
        source_sha256="a" * 64,
        brief_revision=3,
        brief_sha256="b" * 64,
        treatment=NarrativeTreatment(
            causal_spine=[
                "The Alert approaches the city.",
                "Johansen turns the yacht away.",
            ],
            reactions=["Johansen flees."],
            relative_emphasis=["Let the approach breathe before the escape."],
        ),
        beats=beats,
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id="source_000001",
                disposition="caption",
                adapted_beat_ids=["beat_0001"],
                preserved_function="The approach remains explicit.",
            ),
            AdaptationLedgerEntry(
                source_unit_id="source_000002",
                disposition="dialogue",
                adapted_beat_ids=["beat_0002"],
                preserved_function="The escape remains explicit.",
            ),
        ],
    )


def _inventory() -> ApprovedVisualReferenceInventory:
    return ApprovedVisualReferenceInventory(
        references=[
            ApprovedVisualReference(
                id="ref_johansen_base",
                entity_id="character_johansen",
                visual_anchor="gaunt Norwegian sailor; rain-dark pea coat",
            ),
            ApprovedVisualReference(
                id="ref_alert",
                entity_id="location_alert",
                visual_anchor="small steam yacht; black hull; single funnel",
            ),
        ]
    )


def test_producer_allocates_global_book_once_and_persists_canonical_artifacts(
    tmp_path: Path,
) -> None:
    adaptation = _adaptation()
    response = {
        "rhythm_summary": "approach → escape",
        "pages": [
            {
                "page_number": 1,
                "page_turn_role": "release",
                "spread_role": "single",
                "emphasis": "release",
                "density_intent": "standard",
                "rhythm_intent": "approach gives way to escape",
                "layout_intent": "A long approach gives way to one decisive turn.",
                "content": [
                    {
                        "id": "page_001_content_001",
                        "order": 1,
                        "beat_ids": ["beat_0001", "beat_0002"],
                        "visual_intent": (
                            "The yacht approaches the risen city, then wheels away."
                        ),
                        "lettering": [
                            item.model_dump(mode="json")
                            for beat in adaptation.beats
                            for item in beat.lettering
                        ],
                        "entity_ids": ["character_johansen", "location_alert"],
                    }
                ],
                "reading_order": [
                    "page_001_content_001",
                    "lettering_0001",
                    "lettering_0002",
                ],
            }
        ]
    }

    async def generate(**_kwargs):
        return ApiResult(
            value=response,
            usage=UsageRecord(
                provider="test",
                model="test-planner",
                operation="plan.book",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.0,
            ),
        )

    artifacts = TargetArtifacts(tmp_path)
    state = PipelineState(
        project_name="cthulhu",
        novel_path="novel.txt",
        created_at=datetime.now(timezone.utc),
    )
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=2),
            artifacts=artifacts,
            ctx=StageRuntime("plan", state, tmp_path),
            model="test-planner",
            generate=generate,
        )
    )

    page = artifacts.read_page(1)
    assert [beat_id for item in page.content for beat_id in item.beat_ids] == [
        "beat_0001",
        "beat_0002",
    ]
    assert artifacts.read_plan() == plan
    assert plan.pages[0].content_sha256 == page.content_sha256
    assert artifacts.plan_path == tmp_path / "plan" / "book.json"
    assert artifacts.page_path(1) == tmp_path / "plan" / "pages" / "page_001.json"


def test_validation_separates_changed_lettering_from_broken_global_allocation() -> None:
    adaptation = _adaptation()
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="release",
        spread_role="single",
        emphasis="release",
        density_intent="standard",
        layout_intent="The escape receives the page.",
        content=[
            PageContent(
                id="page_001_content_001",
                order=1,
                beat_ids=["beat_0002"],
                visual_intent="The Alert turns away.",
                lettering=[
                    LetteringItem(
                        id="lettering_0002",
                        kind="dialogue",
                        text="Hard to starboard!",
                        speaker="Johansen",
                        source_unit_ids=["source_000002"],
                    )
                ],
                entity_ids=["character_johansen", "location_alert"],
            )
        ],
        reading_order=["page_001_content_001", "lettering_0002"],
    )

    validation = validate_book_plan(
        adaptation,
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=2),
        [page],
    )

    assert {failure.code for failure in validation.invariant_failures} == {
        "beat_allocation",
        "lettering_changed",
    }
    assert validation.editorial_issues == ()
    assert all(failure.blocking for failure in validation.invariant_failures)
    assert all(
        "score" not in failure.model_dump()
        for failure in validation.invariant_failures
    )


def test_coordinates_are_absent_unless_the_author_explicitly_pins_a_beat(
    tmp_path: Path,
) -> None:
    adaptation = _adaptation()
    response = {
        "rhythm_summary": "approach → escape",
        "pages": [
            {
                "page_number": 1,
                "page_turn_role": "release",
                "spread_role": "single",
                "emphasis": "release",
                "density_intent": "standard",
                "rhythm_intent": "approach gives way to escape",
                "layout_intent": "Approach, then escape.",
                "content": [
                    {
                        "id": "page_001_content_001",
                        "order": 1,
                        "beat_ids": ["beat_0001"],
                        "visual_intent": "The yacht approaches.",
                        "lettering": [
                            adaptation.beats[0].lettering[0].model_dump(mode="json")
                        ],
                        "entity_ids": ["location_alert"],
                    },
                    {
                        "id": "page_001_content_002",
                        "order": 2,
                        "beat_ids": ["beat_0002"],
                        "visual_intent": "The yacht escapes.",
                        "lettering": [
                            adaptation.beats[1].lettering[0].model_dump(mode="json")
                        ],
                        "entity_ids": ["character_johansen", "location_alert"],
                    },
                ],
                "reading_order": [
                    "page_001_content_001",
                    "lettering_0001",
                    "page_001_content_002",
                    "lettering_0002",
                ],
            }
        ]
    }

    async def generate(**_kwargs):
        return ApiResult(
            value=response,
            usage=UsageRecord(
                provider="test",
                model="test-planner",
                operation="plan.book",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.0,
            ),
        )

    state = PipelineState(
        project_name="cthulhu",
        novel_path="novel.txt",
        created_at=datetime.now(timezone.utc),
    )
    artifacts = TargetArtifacts(tmp_path)
    asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=2),
            artifacts=artifacts,
            ctx=StageRuntime("plan", state, tmp_path),
            model="test-planner",
            generate=generate,
            author_pins=[
                AuthorGeometryPin(
                    beat_id="beat_0001",
                    geometry=PinnedGeometry(
                        x=0.0,
                        y=0.0,
                        width=1.0,
                        height=0.4,
                    ),
                )
            ],
        )
    )

    content = artifacts.read_page(1).content
    assert content[0].pinned_geometry is not None
    assert content[1].pinned_geometry is None
    assert "pinned_geometry" not in content[1].model_dump(exclude_none=True)


def test_range_conflict_recommends_more_pages_with_allocation_evidence() -> None:
    adaptation = _adaptation()
    pages = [
        ComicPage(
            page_number=index,
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            page_turn_role="setup" if index == 1 else "release",
            spread_role="single",
            emphasis=beat.narrative_function,
            density_intent="sparse",
            layout_intent="Give this complete beat enough space to remain legible.",
            content=[
                PageContent(
                    id=f"page_{index:03d}_content_001",
                    order=1,
                    beat_ids=[beat.id],
                    visual_intent=beat.summary,
                    lettering=beat.lettering,
                    entity_ids=["location_alert"],
                )
            ],
            reading_order=[
                f"page_{index:03d}_content_001",
                beat.lettering[0].id,
            ],
        )
        for index, beat in enumerate(adaptation.beats, start=1)
    ]

    validation = validate_book_plan(
        adaptation,
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=1),
        pages,
    )

    conflict = next(
        failure
        for failure in validation.invariant_failures
        if failure.code == "target_page_range_conflict"
    )
    assert conflict.blocking is True
    assert conflict.artifact_ids == ("beat_0001", "beat_0002")
    assert conflict.evidence == (
        "The complete allocation requires 2 pages; the approved range is 1-1. "
        "Recommend a minimum of 2 pages.",
    )
    assert issubclass(PlanInvariantError, ValueError)


def test_reveal_without_page_turn_setup_is_an_evidence_backed_editorial_issue() -> None:
    payload = _adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][1]["story_functions"] = ["reveal", "reaction"]
    adaptation = BookAdaptation.model_validate(payload)
    pages = [
        ComicPage(
            page_number=index,
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            page_turn_role="none",
            spread_role="single",
            emphasis=beat.narrative_function,
            density_intent="standard",
            layout_intent="One complete beat.",
            content=[
                PageContent(
                    id=f"page_{index:03d}_content_001",
                    order=1,
                    beat_ids=[beat.id],
                    visual_intent=beat.summary,
                    lettering=beat.lettering,
                    entity_ids=["location_alert"],
                )
            ],
            reading_order=[
                f"page_{index:03d}_content_001",
                beat.lettering[0].id,
            ],
        )
        for index, beat in enumerate(adaptation.beats, start=1)
    ]

    validation = validate_book_plan(
        adaptation,
        _inventory(),
        ApprovedPageRange(minimum=2, maximum=2),
        pages,
    )

    issue = next(
        issue
        for issue in validation.editorial_issues
        if issue.code == "weak_page_turn"
    )
    assert issue.blocking is False
    assert issue.artifact_ids == ("beat_0002", "page_002")
    assert issue.evidence == (
        "Reveal beat 'beat_0002' starts page 2, but page 1 has page-turn role 'none' "
        "and page 2 has role 'none'.",
    )
    assert "score" not in issue.model_dump()


def test_cthulhu_plan_preserves_approach_peak_escape_release_and_aftermath_rhythm(
    tmp_path: Path,
) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "cthulhu_plan_rhythm.json"
        ).read_text()
    )
    adaptation = BookAdaptation.model_validate(fixture["adaptation"])
    inventory = ApprovedVisualReferenceInventory.model_validate(
        fixture["references"]
    )
    target_range = ApprovedPageRange.model_validate(fixture["target_range"])

    async def generate(**_kwargs):
        return ApiResult(
            value=fixture["plan_response"],
            usage=UsageRecord(
                provider="test",
                model="test-planner",
                operation="plan.book",
                input_tokens=500,
                output_tokens=500,
                cost_usd=0.0,
            ),
        )

    artifacts = TargetArtifacts(tmp_path)
    state = PipelineState(
        project_name="cthulhu",
        novel_path="novel.txt",
        created_at=datetime.now(timezone.utc),
    )
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            inventory,
            target_range,
            artifacts=artifacts,
            ctx=StageRuntime("plan", state, tmp_path),
            model="test-planner",
            generate=generate,
        )
    )

    pages = [artifacts.read_page(number) for number in range(1, 6)]
    assert plan.rhythm_summary == (
        "approach → Peak → escape → Release → aftermath"
    )
    assert [page.rhythm_intent for page in pages] == [
        "approach",
        "Peak",
        "escape",
        "Release",
        "aftermath",
    ]
    assert [page.emphasis for page in pages] == [
        "prolongation",
        "peak",
        "initial",
        "release",
        "release",
    ]
    assert plan.editorial_issues == ()


def test_reading_order_cannot_reorder_adapt_lettering() -> None:
    adaptation = _adaptation()
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="release",
        spread_role="single",
        emphasis="release",
        density_intent="standard",
        layout_intent="Approach gives way to escape.",
        content=[
            PageContent(
                id="page_001_content_001",
                order=1,
                beat_ids=["beat_0001", "beat_0002"],
                visual_intent="The Alert approaches and turns away.",
                lettering=[
                    item
                    for beat in adaptation.beats
                    for item in beat.lettering
                ],
                entity_ids=["character_johansen", "location_alert"],
            )
        ],
        reading_order=[
            "page_001_content_001",
            "lettering_0002",
            "lettering_0001",
        ],
    )

    validation = validate_book_plan(
        adaptation,
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=1),
        [page],
    )

    failure = next(
        failure
        for failure in validation.invariant_failures
        if failure.code == "reading_order"
    )
    assert failure.artifact_ids == ("page_001",)
    assert failure.evidence == (
        "Expected content order ['page_001_content_001'] and lettering order "
        "['lettering_0001', 'lettering_0002']; found content order "
        "['page_001_content_001'] and lettering order "
        "['lettering_0002', 'lettering_0001'].",
    )


def test_page_scoped_appearance_state_must_follow_the_adapted_change() -> None:
    payload = _adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["appearance_changes"] = [
        AppearanceChange(
            entity_id="character_johansen",
            to_state_id="johansen_soaked",
            description="Spray soaks Johansen's coat.",
        ).model_dump(mode="json")
    ]
    adaptation = BookAdaptation.model_validate(payload)
    inventory = ApprovedVisualReferenceInventory(
        references=[
            *_inventory().references,
            ApprovedVisualReference(
                id="ref_johansen_soaked",
                entity_id="character_johansen",
                appearance_state_id="johansen_soaked",
                visual_anchor="gaunt Norwegian sailor; soaked rain-dark pea coat",
            ),
        ]
    )
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="release",
        spread_role="single",
        emphasis="release",
        density_intent="standard",
        layout_intent="Approach gives way to escape.",
        content=[
            PageContent(
                id="page_001_content_001",
                order=1,
                beat_ids=["beat_0001", "beat_0002"],
                visual_intent="Johansen turns the Alert through heavy spray.",
                lettering=[
                    item
                    for beat in adaptation.beats
                    for item in beat.lettering
                ],
                entity_ids=["character_johansen", "location_alert"],
            )
        ],
        reading_order=[
            "page_001_content_001",
            "lettering_0001",
            "lettering_0002",
        ],
    )

    validation = validate_book_plan(
        adaptation,
        inventory,
        ApprovedPageRange(minimum=1, maximum=1),
        [page],
    )

    failure = next(
        failure
        for failure in validation.invariant_failures
        if failure.code == "appearance_state_allocation"
    )
    assert failure.artifact_ids == (
        "beat_0001",
        "character_johansen",
        "johansen_soaked",
        "page_001_content_001",
    )


@pytest.mark.parametrize("density", ["sparse", "standard", "dense"])
def test_density_is_semantic_intent_without_a_universal_content_cap(
    density: str,
) -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "cthulhu_plan_rhythm.json"
        ).read_text()
    )
    adaptation = BookAdaptation.model_validate(fixture["adaptation"])
    inventory = ApprovedVisualReferenceInventory.model_validate(
        fixture["references"]
    )
    content = [
        PageContent(
            id=f"page_001_content_{index:03d}",
            order=index,
            beat_ids=[beat.id],
            visual_intent=beat.summary,
            lettering=beat.lettering,
            entity_ids=[],
        )
        for index, beat in enumerate(adaptation.beats, start=1)
    ]
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="reveal",
        spread_role="single",
        emphasis="peak",
        density_intent=density,
        rhythm_intent="compressed rhythm study",
        layout_intent=(
            "Five ordered semantic units; density is authored, not counted."
        ),
        content=content,
        reading_order=[
            ordered_id
            for item in content
            for ordered_id in (item.id, *(letter.id for letter in item.lettering))
        ],
    )

    validation = validate_book_plan(
        adaptation,
        inventory,
        ApprovedPageRange(minimum=1, maximum=1),
        [page],
    )

    assert validation.invariant_failures == ()
    assert len(page.content) == 5


def test_peak_and_release_on_one_page_report_proportion_evidence() -> None:
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "cthulhu_plan_rhythm.json"
        ).read_text()
    )
    adaptation = BookAdaptation.model_validate(fixture["adaptation"])
    content = [
        PageContent(
            id=f"page_001_content_{index:03d}",
            order=index,
            beat_ids=[beat.id],
            visual_intent=beat.summary,
            lettering=beat.lettering,
        )
        for index, beat in enumerate(adaptation.beats, start=1)
    ]
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="reveal",
        spread_role="single",
        emphasis="peak",
        density_intent="dense",
        rhythm_intent="Peak and Release collapse together",
        layout_intent="All five rhythm phases share one crowded page.",
        content=content,
        reading_order=[
            ordered_id
            for item in content
            for ordered_id in (item.id, *(letter.id for letter in item.lettering))
        ],
    )

    validation = validate_book_plan(
        adaptation,
        ApprovedVisualReferenceInventory(),
        ApprovedPageRange(minimum=1, maximum=1),
        [page],
    )

    issue = next(
        issue
        for issue in validation.editorial_issues
        if issue.code == "poor_peak_release_proportion"
    )
    assert issue.artifact_ids == (
        "page_001",
        "beat_peak",
        "beat_release",
        "beat_aftermath",
    )
    assert issue.evidence == (
        "Page 1 combines Peak beat(s) ['beat_peak'] with Release/aftermath "
        "beat(s) ['beat_release', 'beat_aftermath'].",
    )


def test_spread_sides_cannot_repeat_without_an_intervening_single_or_spread() -> None:
    adaptation = _adaptation()
    pages = [
        ComicPage(
            page_number=index,
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            page_turn_role="setup" if index == 1 else "release",
            spread_role="left",
            emphasis=beat.narrative_function,
            density_intent="standard",
            layout_intent=beat.summary,
            content=[
                PageContent(
                    id=f"page_{index:03d}_content_001",
                    order=1,
                    beat_ids=[beat.id],
                    visual_intent=beat.summary,
                    lettering=beat.lettering,
                )
            ],
            reading_order=[
                f"page_{index:03d}_content_001",
                beat.lettering[0].id,
            ],
        )
        for index, beat in enumerate(adaptation.beats, start=1)
    ]

    validation = validate_book_plan(
        adaptation,
        ApprovedVisualReferenceInventory(),
        ApprovedPageRange(minimum=2, maximum=2),
        pages,
    )

    failure = next(
        failure
        for failure in validation.invariant_failures
        if failure.code == "page_spread_order"
    )
    assert failure.artifact_ids == ("page_001", "page_002")
    assert failure.evidence == (
        "Pages 1 and 2 both declare spread side 'left'.",
    )


def test_pages_must_cite_the_canonical_book_adaptation_revision() -> None:
    adaptation = _adaptation()
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision + 1,
        adaptation_sha256="f" * 64,
        page_turn_role="release",
        spread_role="single",
        emphasis="release",
        density_intent="standard",
        layout_intent="Approach gives way to escape.",
        content=[
            PageContent(
                id="page_001_content_001",
                order=1,
                beat_ids=["beat_0001", "beat_0002"],
                visual_intent="The Alert approaches and turns away.",
                lettering=[
                    item
                    for beat in adaptation.beats
                    for item in beat.lettering
                ],
            )
        ],
        reading_order=[
            "page_001_content_001",
            "lettering_0001",
            "lettering_0002",
        ],
    )

    validation = validate_book_plan(
        adaptation,
        ApprovedVisualReferenceInventory(),
        ApprovedPageRange(minimum=1, maximum=1),
        [page],
    )

    failure = next(
        failure
        for failure in validation.invariant_failures
        if failure.code == "adaptation_authority_mismatch"
    )
    assert failure.artifact_ids == ("page_001",)
    assert failure.evidence == (
        f"Expected Adapt revision/hash {adaptation.revision}/"
        f"{adaptation.content_sha256}; found {adaptation.revision + 1}/"
        f"{'f' * 64}.",
    )
