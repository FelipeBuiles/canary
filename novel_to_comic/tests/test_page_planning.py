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
    BookPlan,
    ComicPage,
    PageContent,
    PinnedGeometry,
    PlannedPageRevision,
)
from novel_to_comic.models.validation import EditorialIssue
from novel_to_comic.page_planning import (
    _merged_editorial_issues,
    PlanInvariantError,
    build_book_plan_prompt,
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


def test_plan_prompt_uses_structured_panels_and_reserves_splashes() -> None:
    prompt = build_book_plan_prompt(
        _adaptation(),
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=4),
    )

    assert "Each content item is one planned semantic panel" in prompt
    assert "may cite an adapted beat again only on an immediately adjacent panel" in prompt
    assert "Reserve one-panel pages and splash panels" in prompt
    assert "group adjacent story beats into varied multi-panel pages" in prompt.casefold()


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
                        "lettering_ids": [
                            item.id
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


def test_producer_retries_repetitive_single_panel_grammar_once(
    tmp_path: Path,
) -> None:
    adaptation = _adaptation()

    def page_payload(
        page_number: int,
        panels: list[tuple[str, str, str | None]],
    ) -> dict:
        content = [
            {
                "id": f"page_{page_number:03d}_content_{index:03d}",
                "order": index,
                "beat_ids": [beat_id],
                "panel_role": role,
                "visual_intent": f"Visual submoment {page_number}.{index}.",
                "lettering_ids": [lettering_id] if lettering_id else [],
                "entity_ids": [],
            }
            for index, (beat_id, role, lettering_id) in enumerate(panels, 1)
        ]
        return {
            "page_number": page_number,
            "page_turn_role": "release" if page_number == 4 else "none",
            "spread_role": "single",
            "emphasis": "release" if page_number == 4 else "prolongation",
            "density_intent": "standard",
            "rhythm_intent": f"page {page_number} rhythm",
            "layout_intent": f"{len(content)} planned panel(s).",
            "content": content,
            "reading_order": [
                ordered_id
                for item in content
                for ordered_id in (item["id"], *item["lettering_ids"])
            ],
        }

    repetitive = {
        "rhythm_summary": "four identical page weights",
        "pages": [
            page_payload(1, [("beat_0001", "standard", "lettering_0001")]),
            page_payload(2, [("beat_0001", "standard", None)]),
            page_payload(3, [("beat_0001", "standard", None)]),
            page_payload(4, [("beat_0002", "standard", "lettering_0002")]),
        ],
    }
    varied = {
        "rhythm_summary": "varied panel rhythm before release",
        "pages": [
            page_payload(
                1,
                [
                    ("beat_0001", "establishing", "lettering_0001"),
                    ("beat_0001", "detail", None),
                ],
            ),
            page_payload(2, [("beat_0001", "reaction", None)]),
            page_payload(
                3,
                [
                    ("beat_0001", "detail", None),
                    ("beat_0001", "action", None),
                ],
            ),
            page_payload(4, [("beat_0002", "action", "lettering_0002")]),
        ],
    }
    responses = [repetitive, varied]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=responses[len(calls) - 1])

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            ApprovedVisualReferenceInventory(),
            ApprovedPageRange(minimum=4, maximum=4),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(calls) == 2
    assert "repetitive_page_composition" in calls[1]["user_content"]
    assert plan.rhythm_summary == "varied panel rhythm before release"
    assert len(artifacts.read_page(1).content) == 2
    assert "repetitive_page_composition" not in {
        issue.code for issue in plan.editorial_issues
    }


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


def test_plan_can_expand_one_adapted_beat_across_adjacent_planned_panels(
    tmp_path: Path,
) -> None:
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value={
                "rhythm_summary": "approach expands before escape",
                "pages": [
                    {
                        "page_number": 1,
                        "page_turn_role": "setup",
                        "spread_role": "single",
                        "emphasis": "prolongation",
                        "density_intent": "sparse",
                        "rhythm_intent": "establish the approach",
                        "layout_intent": "One establishing panel.",
                        "content": [
                            {
                                "id": "page_001_content_001",
                                "order": 1,
                                "beat_ids": ["beat_0001"],
                                "panel_role": "establishing",
                                "visual_intent": "The Alert nears the risen city.",
                                "lettering_ids": ["lettering_0001"],
                                "entity_ids": ["location_alert"],
                            }
                        ],
                        "reading_order": [
                            "page_001_content_001",
                            "lettering_0001",
                        ],
                    },
                    {
                        "page_number": 2,
                        "page_turn_role": "cliffhanger",
                        "spread_role": "single",
                        "emphasis": "prolongation",
                        "density_intent": "sparse",
                        "rhythm_intent": "hold on the threatening city",
                        "layout_intent": "One detail panel.",
                        "content": [
                            {
                                "id": "page_002_content_001",
                                "order": 1,
                                "beat_ids": ["beat_0001"],
                                "panel_role": "detail",
                                "visual_intent": "Impossible masonry fills the horizon.",
                                "lettering_ids": [],
                                "entity_ids": ["location_alert"],
                            }
                        ],
                        "reading_order": ["page_002_content_001"],
                    },
                    {
                        "page_number": 3,
                        "page_turn_role": "release",
                        "spread_role": "single",
                        "emphasis": "release",
                        "density_intent": "standard",
                        "rhythm_intent": "Johansen turns away",
                        "layout_intent": "One action panel.",
                        "content": [
                            {
                                "id": "page_003_content_001",
                                "order": 1,
                                "beat_ids": ["beat_0002"],
                                "panel_role": "action",
                                "visual_intent": "Johansen hauls the wheel over.",
                                "lettering_ids": ["lettering_0002"],
                                "entity_ids": [
                                    "character_johansen",
                                    "location_alert",
                                ],
                            }
                        ],
                        "reading_order": [
                            "page_003_content_001",
                            "lettering_0002",
                        ],
                    },
                ],
            }
        )

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            _adaptation(),
            _inventory(),
            ApprovedPageRange(minimum=3, maximum=4),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(calls) == 1
    assert len(plan.pages) == 3
    assert artifacts.read_page(1).content[0].beat_ids == ("beat_0001",)
    assert artifacts.read_page(2).content[0].beat_ids == ("beat_0001",)
    assert artifacts.read_page(2).content[0].panel_role == "detail"


def test_lettering_allocated_to_the_wrong_beat_is_a_blocking_failure() -> None:
    # Ordered equality across the whole book is blind to this: moving beat 2's
    # balloon onto beat 1's content item preserves the flat lettering order
    # while lettering the wrong panel.
    adaptation = _adaptation()
    lettering = [item for beat in adaptation.beats for item in beat.lettering]
    content = [
        PageContent(
            id="page_001_content_001",
            order=1,
            beat_ids=["beat_0001"],
            visual_intent="The Alert approaches.",
            lettering=lettering,
            entity_ids=["location_alert"],
        ),
        PageContent(
            id="page_001_content_002",
            order=2,
            beat_ids=["beat_0002"],
            visual_intent="Johansen hauls the wheel.",
            entity_ids=["character_johansen"],
        ),
    ]
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        emphasis="release",
        density_intent="standard",
        layout_intent="Approach, then escape.",
        content=content,
        reading_order=[
            "page_001_content_001",
            *(item.id for item in lettering),
            "page_001_content_002",
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
        if failure.code == "lettering_beat_mismatch"
    )
    assert "lettering_0002" in failure.artifact_ids
    assert "beat_0002" in failure.artifact_ids


def test_plan_cannot_return_to_an_earlier_beat_after_story_order_advances() -> None:
    adaptation = _adaptation()
    contents = [
        PageContent(
            id="page_001_content_001",
            order=1,
            beat_ids=["beat_0001"],
            panel_role="establishing",
            visual_intent="The Alert approaches.",
            lettering=adaptation.beats[0].lettering,
        ),
        PageContent(
            id="page_001_content_002",
            order=2,
            beat_ids=["beat_0002"],
            panel_role="action",
            visual_intent="Johansen turns away.",
            lettering=adaptation.beats[1].lettering,
        ),
        PageContent(
            id="page_001_content_003",
            order=3,
            beat_ids=["beat_0001"],
            panel_role="detail",
            visual_intent="The story incorrectly returns to the approach.",
        ),
    ]
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="release",
        spread_role="single",
        emphasis="release",
        density_intent="dense",
        rhythm_intent="The order rewinds.",
        layout_intent="Three ordered panels.",
        content=contents,
        reading_order=[
            ordered_id
            for content in contents
            for ordered_id in (
                content.id,
                *(lettering.id for lettering in content.lettering),
            )
        ],
    )

    validation = validate_book_plan(
        adaptation,
        ApprovedVisualReferenceInventory(),
        ApprovedPageRange(minimum=1, maximum=1),
        [page],
    )

    assert "beat_allocation" in {
        failure.code for failure in validation.invariant_failures
    }


def test_plan_copies_adapt_lettering_from_the_cited_ids(tmp_path: Path) -> None:
    """Plan cannot restate wording, so it cannot corrupt it."""

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
                        "visual_intent": "The Alert approaches.",
                        "lettering_ids": ["lettering_0001"],
                        "entity_ids": ["location_alert"],
                    },
                    {
                        "id": "page_001_content_002",
                        "order": 2,
                        "beat_ids": ["beat_0002"],
                        "visual_intent": "The Alert turns away.",
                        "lettering_ids": ["lettering_0002"],
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
        ],
    }

    async def generate(**_kwargs):
        return ApiResult(
            value=response,
            usage=UsageRecord(
                provider="test",
                model="test-planner",
                operation="plan.book",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0,
            ),
        )

    artifacts = TargetArtifacts(tmp_path)
    asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=1),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    page = artifacts.read_page(1)
    assert [
        item.model_dump() for content in page.content for item in content.lettering
    ] == [
        item.model_dump() for beat in adaptation.beats for item in beat.lettering
    ]
    assert artifacts.read_page_revision(1, 1) == page


def test_lettering_cited_by_the_wrong_content_item_cannot_be_planned(
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
                        "beat_ids": ["beat_0001", "beat_0002"],
                        "visual_intent": "The approach and the escape.",
                        "lettering_ids": ["lettering_0001", "lettering_0002"],
                        "entity_ids": ["location_alert"],
                    }
                ],
                "reading_order": [
                    "page_001_content_001",
                    "lettering_0001",
                    "lettering_0002",
                ],
            }
        ],
    }
    unknown = {
        **response,
        "pages": [
            {
                **response["pages"][0],
                "content": [
                    {
                        **response["pages"][0]["content"][0],
                        "lettering_ids": ["lettering_0001", "lettering_9999"],
                    }
                ],
            }
        ],
    }

    async def generate(**_kwargs):
        return ApiResult(
            value=unknown,
            usage=UsageRecord(
                provider="test",
                model="test-planner",
                operation="plan.book",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0,
            ),
        )

    with pytest.raises(PlanInvariantError) as raised:
        asyncio.run(
            produce_book_plan(
                adaptation,
                _inventory(),
                ApprovedPageRange(minimum=1, maximum=1),
                artifacts=TargetArtifacts(tmp_path),
                ctx=StageRuntime(
                    "plan",
                    PipelineState(
                        project_name="cthulhu",
                        novel_path="novel.txt",
                        created_at=datetime.now(timezone.utc),
                    ),
                    tmp_path,
                ),
                model="test-planner",
                generate=generate,
            )
        )

    assert [
        failure.code for failure in raised.value.validation.invariant_failures
    ] == ["unknown_lettering"]


def test_plan_persists_its_verdict_and_page_range_recommendation(
    tmp_path: Path,
) -> None:
    adaptation = _adaptation()
    response = {
        "rhythm_summary": "approach → escape",
        "pages": [
            {
                "page_number": page_number,
                "page_turn_role": "release",
                "spread_role": "single",
                "emphasis": "release" if page_number == 2 else "prolongation",
                "density_intent": "standard",
                "rhythm_intent": "one beat per page",
                "layout_intent": "One beat per page.",
                "content": [
                    {
                        "id": f"page_{page_number:03d}_content_001",
                        "order": 1,
                        "beat_ids": [f"beat_000{page_number}"],
                        "visual_intent": "A beat.",
                        "lettering_ids": [f"lettering_000{page_number}"],
                        "entity_ids": ["location_alert"],
                    }
                ],
                "reading_order": [
                    f"page_{page_number:03d}_content_001",
                    f"lettering_000{page_number}",
                ],
            }
            for page_number in (1, 2)
        ],
    }

    async def generate(**_kwargs):
        return ApiResult(
            value=response,
            usage=UsageRecord(
                provider="test",
                model="test-planner",
                operation="plan.book",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0,
            ),
        )

    artifacts = TargetArtifacts(tmp_path)
    with pytest.raises(PlanInvariantError):
        asyncio.run(
            produce_book_plan(
                adaptation,
                _inventory(),
                ApprovedPageRange(minimum=1, maximum=1),
                artifacts=artifacts,
                ctx=StageRuntime(
                    "plan",
                    PipelineState(
                        project_name="cthulhu",
                        novel_path="novel.txt",
                        created_at=datetime.now(timezone.utc),
                    ),
                    tmp_path,
                ),
                model="test-planner",
                generate=generate,
            )
        )

    # The recommendation is the one thing the user can act on, so it has to
    # outlive the raised exception.
    validation = artifacts.read_validation("plan")
    assert validation.owner_stage == "plan"
    assert validation.attempts == 2
    assert [failure.code for failure in validation.invariant_failures] == [
        "target_page_range_conflict"
    ]
    assert "Recommend a minimum of 2 pages." in validation.recommendations[0]


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
                        "lettering_ids": [adaptation.beats[0].lettering[0].id],
                        "entity_ids": ["location_alert"],
                    },
                    {
                        "id": "page_001_content_002",
                        "order": 2,
                        "beat_ids": ["beat_0002"],
                        "visual_intent": "The yacht escapes.",
                        "lettering_ids": [adaptation.beats[1].lettering[0].id],
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


def test_fidelity_page_floor_allows_safe_allocation_beyond_maximum() -> None:
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
        ApprovedPageRange(minimum=1, maximum=1, allow_expansion=True),
        pages,
    )

    assert "target_page_range_conflict" not in {
        failure.code for failure in validation.invariant_failures
    }


def test_allocation_below_the_floor_is_reviewable_not_repaired() -> None:
    """The floor was approved before any beats existed.

    Plan allocated the adaptation that actually got written, so a shortfall is
    recorded for review rather than padded to reach a stale estimate — and it is
    recorded by the validator, not left to whether the model volunteers it.
    """
    adaptation = _adaptation()
    pages = [
        ComicPage(
            page_number=1,
            revision=1,
            adaptation_revision=adaptation.revision,
            adaptation_sha256=adaptation.content_sha256,
            page_turn_role="setup",
            spread_role="single",
            emphasis=adaptation.beats[0].narrative_function,
            density_intent="dense",
            layout_intent="Every beat on one page.",
            content=[
                PageContent(
                    id=f"page_001_content_{index:03d}",
                    order=index,
                    beat_ids=[beat.id],
                    visual_intent=beat.summary,
                    lettering=beat.lettering,
                    entity_ids=["location_alert"],
                )
                for index, beat in enumerate(adaptation.beats, start=1)
            ],
            reading_order=[
                item
                for index, beat in enumerate(adaptation.beats, start=1)
                for item in (f"page_001_content_{index:03d}", beat.lettering[0].id)
            ],
        )
    ]

    validation = validate_book_plan(
        adaptation,
        _inventory(),
        ApprovedPageRange(minimum=4, maximum=8, allow_expansion=True),
        pages,
    )

    assert validation.invariant_failures == ()
    shortfall = next(
        issue
        for issue in validation.editorial_issues
        if issue.code == "page_count_below_floor"
    )
    assert shortfall.blocking is False
    assert "allocation is 1 pages" in shortfall.evidence[0]
    assert "Recommend lowering the approved minimum to 1 pages" in shortfall.evidence[0]


def test_expansion_lets_the_recorded_range_follow_a_short_allocation() -> None:
    # BookPlan's own validator enforces target_page_min <= len(pages), so the
    # recorded floor has to follow the allocation or construction would fail the
    # stage on a plan the validator already accepted.
    adaptation = _adaptation()
    plan = BookPlan(
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        target_page_min=min(32, 23),
        target_page_max=max(40, 23),
        rhythm_summary="Short but complete.",
        pages=[
            PlannedPageRevision(
                page_number=index,
                revision=1,
                content_sha256="0" * 64,
            )
            for index in range(1, 24)
        ],
    )
    assert len(plan.pages) == 23
    assert plan.target_page_min == 23


def test_reveal_without_page_turn_setup_is_an_evidence_backed_editorial_issue() -> None:
    payload = _adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][1]["narrative_function"] = "peak"
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


def test_non_peak_reveal_does_not_require_its_own_page_turn() -> None:
    payload = _adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][1]["narrative_function"] = "prolongation"
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

    assert "weak_page_turn" not in {
        issue.code for issue in validation.editorial_issues
    }


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


def test_repetitive_single_panel_run_is_an_evidence_backed_editorial_issue() -> None:
    adaptation = _adaptation()
    pages: list[ComicPage] = []
    allocations = [
        ("beat_0001", "lettering_0001", "prolongation"),
        ("beat_0001", None, "prolongation"),
        ("beat_0001", None, "prolongation"),
        ("beat_0002", "lettering_0002", "release"),
    ]
    for page_number, (beat_id, lettering_id, emphasis) in enumerate(
        allocations,
        start=1,
    ):
        beat = next(beat for beat in adaptation.beats if beat.id == beat_id)
        lettering = (
            tuple(item for item in beat.lettering if item.id == lettering_id)
            if lettering_id is not None
            else ()
        )
        content_id = f"page_{page_number:03d}_content_001"
        pages.append(
            ComicPage(
                page_number=page_number,
                revision=1,
                adaptation_revision=adaptation.revision,
                adaptation_sha256=adaptation.content_sha256,
                page_turn_role="none",
                spread_role="single",
                emphasis=emphasis,
                density_intent="standard",
                rhythm_intent="The same beat receives another whole page.",
                layout_intent="One full-page panel.",
                content=[
                    PageContent(
                        id=content_id,
                        order=1,
                        beat_ids=[beat_id],
                        panel_role="standard",
                        visual_intent=beat.summary,
                        lettering=lettering,
                    )
                ],
                reading_order=[
                    content_id,
                    *(item.id for item in lettering),
                ],
            )
        )

    validation = validate_book_plan(
        adaptation,
        ApprovedVisualReferenceInventory(),
        ApprovedPageRange(minimum=4, maximum=4),
        pages,
    )

    assert validation.invariant_failures == ()
    issue = next(
        issue
        for issue in validation.editorial_issues
        if issue.code == "repetitive_page_composition"
    )
    assert issue.artifact_ids == (
        "page_001",
        "page_002",
        "page_003",
        "page_004",
    )


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


def test_a_schema_slip_in_the_plan_draft_is_repaired_not_fatal(tmp_path: Path) -> None:
    adaptation = _adaptation()
    page = {
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
                "beat_ids": ["beat_0001", "beat_0002"],
                "visual_intent": "The approach, then the escape.",
                "lettering_ids": ["lettering_0001", "lettering_0002"],
                "entity_ids": ["character_johansen", "location_alert"],
            }
        ],
        "reading_order": [
            "page_001_content_001",
            "lettering_0001",
            "lettering_0002",
        ],
    }
    responses = [
        # beat_ids as a bare string: a shape slip, not a planning decision.
        {
            "rhythm_summary": "approach → escape",
            "pages": [
                {
                    **page,
                    "content": [{**page["content"][0], "beat_ids": "beat_0001"}],
                }
            ],
        },
        {"rhythm_summary": "approach → escape", "pages": [page]},
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value=responses[len(calls) - 1],
            usage=UsageRecord(
                provider="test",
                model="test-planner",
                operation="plan.book",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0,
            ),
        )

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=1),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(plan.pages) == 1
    assert len(calls) == 2
    assert "VALIDATION ERRORS" in calls[1]["user_content"]


def test_plan_authored_issue_ownership_is_canonicalized_without_a_retry(
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
                        "beat_ids": ["beat_0001", "beat_0002"],
                        "visual_intent": "The approach, then the escape.",
                        "lettering_ids": ["lettering_0001", "lettering_0002"],
                        "entity_ids": [
                            "character_johansen",
                            "location_alert",
                        ],
                    }
                ],
                "reading_order": [
                    "page_001_content_001",
                    "lettering_0001",
                    "lettering_0002",
                ],
            }
        ],
        "editorial_issues": [
            {
                "id": "plan_issue_test",
                # Exact production slip: the Plan model mislabels its own issue.
                "owner_stage": "adapt",
                "code": "test_issue",
                "message": "The transition may feel abrupt.",
                "source_unit_ids": ["source_000001"],
                "artifact_ids": ["page_001_content_001"],
                "evidence": ["The approach and escape share one content unit."],
                "kind": "editorial_issue",
                "blocking": False,
            }
        ],
    }
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=response)

    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=1),
            artifacts=TargetArtifacts(tmp_path),
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(calls) == 1
    issue = next(issue for issue in plan.editorial_issues if issue.id == "plan_issue_test")
    assert issue.owner_stage == "plan"


def test_plan_does_not_republish_an_upstream_adapt_issue() -> None:
    payload = _adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["editorial_issues"] = [
        {
            "id": "adapt_issue_transition_continuity_beat_0001_place",
            "owner_stage": "adapt",
            "code": "continuity_state_mismatch",
            "message": "A place transition may skip an intermediate state.",
            "artifact_ids": ["beat_0001"],
            "source_unit_ids": ["source_000001"],
            "evidence": ["Expected the studio; found Providence."],
        }
    ]
    adaptation = BookAdaptation.model_validate(payload)
    copied_by_plan = EditorialIssue(
        id="adapt_issue_transition_continuity_beat_0001_place",
        owner_stage="plan",
        code="continuity_state_mismatch",
        message="A place transition may skip an intermediate state.",
        artifact_ids=["beat_0001"],
        source_unit_ids=["source_000001"],
        evidence=["Expected the studio; found Providence."],
    )

    merged = _merged_editorial_issues(
        (),
        (copied_by_plan,),
        adaptation=adaptation,
        pages=(),
    )

    assert merged == ()


def test_mechanical_allocation_and_reference_ids_are_canonicalized(
    tmp_path: Path,
) -> None:
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
            ApprovedVisualReference(
                id="character_johansen:base",
                entity_id="character_johansen",
                visual_anchor="gaunt Norwegian sailor; rain-dark pea coat",
            ),
            ApprovedVisualReference(
                id="character_johansen:johansen_soaked",
                entity_id="character_johansen",
                appearance_state_id="johansen_soaked",
                visual_anchor="gaunt Norwegian sailor; soaked rain-dark pea coat",
            ),
            ApprovedVisualReference(
                id="location_alert:base",
                entity_id="location_alert",
                visual_anchor="small steam yacht; black hull; single funnel",
            ),
        ]
    )
    response = {
        "rhythm_summary": "approach → escape",
        "pages": [
            {
                "page_number": 1,
                "page_turn_role": "setup",
                "spread_role": "single",
                "emphasis": "initial",
                "density_intent": "standard",
                "rhythm_intent": "The soaked approach begins.",
                "layout_intent": "Spray fills the approach.",
                "content": [
                    {
                        "id": "page_001_content_001",
                        "order": 1,
                        "beat_ids": ["beat_0001"],
                        "visual_intent": "Johansen approaches through heavy spray.",
                        "lettering_ids": ["lettering_0001"],
                        "entity_ids": ["character_johansen", "location_alert"],
                        # Exact production slip: reference IDs are copied into
                        # the appearance-state field, including base references.
                        "appearance_state_ids": [
                            "character_johansen:base",
                            "character_johansen:johansen_soaked",
                            "location_alert:base",
                        ],
                    }
                ],
                "reading_order": [
                    "page_001_content_001",
                    "lettering_0001",
                ],
            },
            {
                "page_number": 2,
                "page_turn_role": "release",
                "spread_role": "single",
                "emphasis": "release",
                "density_intent": "standard",
                "rhythm_intent": "The approach gives way to escape.",
                "layout_intent": "The yacht wheels away.",
                "content": [
                    {
                        "id": "page_002_content_001",
                        "order": 1,
                        # The approach remains visible as the escape begins.
                        "beat_ids": ["beat_0001", "beat_0002"],
                        "visual_intent": "The approach resolves into escape.",
                        "lettering_ids": ["lettering_0002"],
                        "entity_ids": ["character_johansen", "location_alert"],
                        "appearance_state_ids": [
                            "character_johansen:johansen_soaked",
                            "location_alert:base",
                        ],
                    }
                ],
                "reading_order": [
                    "page_002_content_001",
                    "lettering_0002",
                ],
            },
        ],
    }
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=response)

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            inventory,
            ApprovedPageRange(minimum=2, maximum=2),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(calls) == 1
    assert len(plan.pages) == 2
    assert artifacts.read_page(1).content[0].appearance_state_ids == (
        "johansen_soaked",
    )
    assert artifacts.read_page(2).content[0].beat_ids == (
        "beat_0001",
        "beat_0002",
    )
    assert artifacts.read_page(2).content[0].appearance_state_ids == (
        "johansen_soaked",
    )


def test_an_adapted_beat_may_expand_across_adjacent_planned_panels(
    tmp_path: Path,
) -> None:
    adaptation = _adaptation()
    valid_page = {
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
                "beat_ids": ["beat_0001", "beat_0002"],
                "visual_intent": "The approach, then the escape.",
                "lettering_ids": ["lettering_0001", "lettering_0002"],
                "entity_ids": ["character_johansen", "location_alert"],
            }
        ],
        "reading_order": [
            "page_001_content_001",
            "lettering_0001",
            "lettering_0002",
        ],
    }
    duplicate_beat_page = {
        **valid_page,
        "content": [
            {
                **valid_page["content"][0],
                "beat_ids": ["beat_0001"],
                "lettering_ids": ["lettering_0001"],
            },
            {
                "id": "page_001_content_002",
                "order": 2,
                "beat_ids": ["beat_0001"],
                "visual_intent": "The approach is repeated as a separate unit.",
                "lettering_ids": [],
                "entity_ids": ["character_johansen", "location_alert"],
            },
            {
                "id": "page_001_content_003",
                "order": 3,
                "beat_ids": ["beat_0002"],
                "visual_intent": "The yacht escapes.",
                "lettering_ids": ["lettering_0002"],
                "entity_ids": ["character_johansen", "location_alert"],
            },
        ],
        "reading_order": [
            "page_001_content_001",
            "lettering_0001",
            "page_001_content_002",
            "page_001_content_003",
            "lettering_0002",
        ],
    }
    responses = [
        {
            "rhythm_summary": "approach → escape",
            "pages": [duplicate_beat_page],
        }
    ]
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=responses[len(calls) - 1])

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=1),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(plan.pages) == 1
    assert len(calls) == 1
    assert len(artifacts.read_page(1).content) == 3
    assert artifacts.read_page(1).content[1].beat_ids == ("beat_0001",)


def test_missing_lettering_ids_are_derived_into_reading_order(
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
                        "beat_ids": ["beat_0001", "beat_0002"],
                        "visual_intent": "The approach, then the escape.",
                        "lettering_ids": ["lettering_0001", "lettering_0002"],
                        "entity_ids": [
                            "character_johansen",
                            "location_alert",
                        ],
                    }
                ],
                # This is the exact real failure: the content is allocated, but
                # the model omits its lettering IDs from explicit reading order.
                "reading_order": ["page_001_content_001"],
            }
        ],
    }
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=response)

    artifacts = TargetArtifacts(tmp_path)
    asyncio.run(
        produce_book_plan(
            adaptation,
            _inventory(),
            ApprovedPageRange(minimum=1, maximum=1),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="cthulhu",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(calls) == 1
    assert artifacts.read_page(1).reading_order == (
        "page_001_content_001",
        "lettering_0001",
        "lettering_0002",
    )


def test_the_plan_prompt_states_the_page_shape_it_wants() -> None:
    # Plan describes its allocation rules at length but, like Adapt did, never
    # named the JSON keys — leaving the writer to guess the container.
    from novel_to_comic.page_planning import build_book_plan_prompt

    prompt = build_book_plan_prompt(
        _adaptation(),
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=2),
    )

    assert '"rhythm_summary"' in prompt
    assert '"pages"' in prompt
    assert "<_PageDraft> = {" in prompt
    assert "<_PageContentDraft> = {" in prompt
    # Lettering is allocated by ID; the contract has to say so in the shape too.
    assert '"lettering_ids": [string, ...]' in prompt
    assert '"density_intent": "sparse" | "standard" | "dense"' in prompt


def test_fidelity_plan_prompt_treats_page_maximum_as_expandable_floor() -> None:
    from novel_to_comic.page_planning import build_book_plan_prompt

    prompt = build_book_plan_prompt(
        _adaptation(),
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=2, allow_expansion=True),
    )

    assert "approved minimum is a narrative floor" in prompt
    assert "exceeds the approved maximum" in prompt


def _soaked_adaptation() -> BookAdaptation:
    """The production shape: beat_0001 changes Johansen into a soaked state."""

    payload = _adaptation().model_dump()
    payload["content_sha256"] = ""
    payload["beats"][0]["appearance_changes"] = [
        AppearanceChange(
            entity_id="character_johansen",
            to_state_id="johansen_soaked",
            description="Spray soaks Johansen's coat.",
        ).model_dump(mode="json")
    ]
    return BookAdaptation.model_validate(payload)


def _soaked_inventory() -> ApprovedVisualReferenceInventory:
    return ApprovedVisualReferenceInventory(
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


def _two_page_response(content_overrides: dict[str, object]) -> dict:
    return {
        "rhythm_summary": "approach → escape",
        "pages": [
            {
                "page_number": 1,
                "page_turn_role": "setup",
                "spread_role": "single",
                "emphasis": "initial",
                "density_intent": "standard",
                "rhythm_intent": "The soaked approach begins.",
                "layout_intent": "Spray fills the approach.",
                "content": [
                    {
                        "id": "page_001_content_001",
                        "order": 1,
                        "beat_ids": ["beat_0001"],
                        "visual_intent": "Johansen approaches through heavy spray.",
                        "lettering_ids": ["lettering_0001"],
                        **content_overrides,
                    }
                ],
                "reading_order": ["page_001_content_001", "lettering_0001"],
            },
            {
                "page_number": 2,
                "page_turn_role": "release",
                "spread_role": "single",
                "emphasis": "release",
                "density_intent": "standard",
                "rhythm_intent": "The approach gives way to escape.",
                "layout_intent": "The yacht wheels away.",
                "content": [
                    {
                        "id": "page_002_content_001",
                        "order": 1,
                        "beat_ids": ["beat_0002"],
                        "visual_intent": "The yacht wheels away.",
                        "lettering_ids": ["lettering_0002"],
                        "entity_ids": ["character_johansen", "location_alert"],
                    }
                ],
                "reading_order": ["page_002_content_001", "lettering_0002"],
            },
        ],
    }


def _run_plan(
    adaptation: BookAdaptation,
    inventory: ApprovedVisualReferenceInventory,
    response: dict,
    tmp_path: Path,
) -> tuple[TargetArtifacts, list[dict], BookPlan | PlanInvariantError]:
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value=response)

    artifacts = TargetArtifacts(tmp_path)
    ctx = StageRuntime(
        "plan",
        PipelineState(
            project_name="cthulhu",
            novel_path="novel.txt",
            created_at=datetime.now(timezone.utc),
        ),
        tmp_path,
    )
    try:
        outcome: BookPlan | PlanInvariantError = asyncio.run(
            produce_book_plan(
                adaptation,
                inventory,
                ApprovedPageRange(minimum=2, maximum=2),
                artifacts=artifacts,
                ctx=ctx,
                model="test-planner",
                generate=generate,
            )
        )
    except PlanInvariantError as error:
        outcome = error
    return artifacts, calls, outcome


def test_an_adapted_appearance_change_is_derived_into_the_page_citations(
    tmp_path: Path,
) -> None:
    # The exact production failure: the writer allocated the beat that carries
    # the appearance change but cited neither the entity nor the target state,
    # which used to raise a blocking appearance_state_allocation failure and
    # buy a full repair round. Both IDs are Adapt's decision, so code derives
    # them and no second call is made.
    artifacts, calls, plan = _run_plan(
        _soaked_adaptation(),
        _soaked_inventory(),
        _two_page_response({"entity_ids": ["location_alert"]}),
        tmp_path,
    )

    assert isinstance(plan, BookPlan)
    assert len(calls) == 1
    content = artifacts.read_page(1).content[0]
    assert content.entity_ids == ("location_alert", "character_johansen")
    assert content.appearance_state_ids == ("johansen_soaked",)
    validation = artifacts.read_validation("plan")
    assert validation.invariant_failures == ()


def test_deriving_an_appearance_change_never_duplicates_a_cited_id(
    tmp_path: Path,
) -> None:
    artifacts, _calls, plan = _run_plan(
        _soaked_adaptation(),
        _soaked_inventory(),
        _two_page_response(
            {
                "entity_ids": ["character_johansen", "location_alert"],
                "appearance_state_ids": ["johansen_soaked"],
            }
        ),
        tmp_path,
    )

    assert isinstance(plan, BookPlan)
    content = artifacts.read_page(1).content[0]
    assert content.entity_ids == ("character_johansen", "location_alert")
    assert content.appearance_state_ids == ("johansen_soaked",)


def test_an_unapproved_appearance_state_is_attributed_to_adapt_not_repaired(
    tmp_path: Path,
) -> None:
    # Adapt named a state Cast never approved. No page allocation can make that
    # valid, so Plan must not derive it, must not blame itself, and must not pay
    # for a repair attempt it cannot win.
    artifacts, calls, outcome = _run_plan(
        _soaked_adaptation(),
        _inventory(),
        _two_page_response({"entity_ids": ["character_johansen", "location_alert"]}),
        tmp_path,
    )

    assert isinstance(outcome, PlanInvariantError)
    assert len(calls) == 1
    validation = artifacts.read_validation("plan")
    failure = next(
        failure
        for failure in validation.invariant_failures
        if failure.code == "unapproved_appearance_state"
    )
    assert failure.owner_stage == "adapt"
    assert failure.artifact_ids == (
        "beat_0001",
        "character_johansen",
        "johansen_soaked",
    )
    assert validation.attempt_history[0].invariant_codes == (
        "unapproved_appearance_state",
    )
