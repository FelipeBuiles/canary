from __future__ import annotations

from .plan_detail_support import detail_response, plan_response, reservation

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import pytest
from pydantic import ValidationError

from novel_to_comic.models.adaptation import (
    AdaptationLedgerEntry,
    AdaptedBeat,
    AppearanceChange,
    BookAdaptation,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.adaptation import ContinuityTransition
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
    _BookPlanDraft,
    _BookPageMap,
    _detail_batch_prompt,
    _PAGE_MAP_MAX_OUTPUT_TOKENS,
    _PageMapEntry,
    _detail_matches_map,
    _merged_editorial_issues,
    _planning_view,
    PlanInvariantError,
    build_book_plan_prompt,
    produce_book_plan,
    validate_book_plan,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


@pytest.fixture(autouse=True)
def isolate_editorial_judgment(monkeypatch):
    from .narrative_review_support import accept_narrative
    monkeypatch.setattr("novel_to_comic.page_planning.review_narrative", accept_narrative)


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
def test_detail_batch_retains_completed_transitions_before_its_first_page():
    adaptation = _adaptation()
    transition = ContinuityTransition(
        dimension="place", scope_id="main_thread", from_state="outside",
        to_state="inside", description="Johansen enters carrying the chart.",
    )
    first = adaptation.beats[0].model_copy(update={"transitions": (transition,)})
    adaptation = adaptation.model_copy(update={"beats": (first, adaptation.beats[1])})
    page_map = _BookPageMap(
        rhythm_summary="Arrival followed by response.",
        pages=[
            _PageMapEntry(
                page_number=index, beat_ids=(beat.id,), lettering_ids=tuple(item.id for item in beat.lettering), emphasis="initial",
                density_intent="standard", rhythm_intent="Advance the scene.",
            )
            for index, beat in enumerate(adaptation.beats, 1)
        ],
    )
    prompt = _detail_batch_prompt(adaptation, _inventory(), page_map, start=1, stop=2)
    context = json.loads(prompt[prompt.index("\n") + 1:])
    assert context["planning_view"]["established_continuity"][0]["transitions"] == [
        transition.model_dump(mode="json"),
    ]
    assert [beat["id"] for beat in context["planning_view"]["beats"]] == ["beat_0002"]






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
                        "continuity_intent": (
                            "Johansen starts aboard the approaching yacht and ends aboard it "
                            "after the turn, moving away from the city."
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
        ],
    }

    async def generate(**_kwargs):
        return ApiResult(
            value=plan_response(response),
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
    assert response["pages"][0]["layout_intent"] in page.layout_intent
    assert response["pages"][0]["content"][0]["continuity_intent"] in page.layout_intent
    assert page.content[0].lettering == tuple(
        item for beat in adaptation.beats for item in beat.lettering
    )
    assert artifacts.plan_path == tmp_path / "plan" / "book.json"
    assert artifacts.page_path(1) == tmp_path / "plan" / "pages" / "page_001.json"


def _long_adaptation(beat_count: int = 24) -> BookAdaptation:
    beats = [
        AdaptedBeat(
            id=f"beat_{index:04d}",
            order=index,
            summary=f"Story event {index}.",
            narrative_function="initial",
            story_functions=["causal_event"],
            source_unit_ids=[f"source_{index:06d}"],
            lettering=[
                LetteringItem(
                    id=f"lettering_{index:04d}",
                    kind="caption",
                    text=f"Event {index}.",
                    delivery="narration",
                    source_unit_ids=[f"source_{index:06d}"],
                )
            ],
        )
        for index in range(1, beat_count + 1)
    ]
    return BookAdaptation(
        revision=1,
        source_sha256="a" * 64,
        brief_revision=1,
        brief_sha256="b" * 64,
        treatment=NarrativeTreatment(causal_spine=["The events advance in order."]),
        beats=beats,
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id=f"source_{index:06d}",
                disposition="caption",
                adapted_beat_ids=[f"beat_{index:04d}"],
                preserved_function=f"Event {index} remains explicit.",
            )
            for index in range(1, beat_count + 1)
        ],
    )


def _long_adaptation_with_multiple_lettering_items() -> BookAdaptation:
    payload = _long_adaptation().model_dump()
    payload["content_sha256"] = ""
    for beat in payload["beats"]:
        first = beat["lettering"][0]
        beat["lettering"] = [
            first,
            {
                **first,
                "id": f"{first['id']}_second",
                "text": f"Follow-up {beat['order']}.",
            },
        ]
    return BookAdaptation.model_validate(payload)


def test_detail_validation_rejects_a_rewound_beat_sequence() -> None:
    draft = _BookPlanDraft.model_validate(
        plan_response({
            "rhythm_summary": "A two-beat page.",
            "pages": [
                {
                    "emphasis": "initial",
                    "density_intent": "standard",
                    "rhythm_intent": "The action advances.",
                    "layout_intent": "Two ordered beats with a returning error.",
                    "content": [
                        {
                            "beat_ids": ["beat_0035"],
                            "visual_intent": "The first beat begins.",
                        },
                        {
                            "beat_ids": ["beat_0036"],
                            "visual_intent": "The second beat advances the action.",
                        },
                        {
                            "beat_ids": ["beat_0035"],
                            "visual_intent": "The page incorrectly returns backward.",
                        },
                        {
                            "beat_ids": ["beat_0036"],
                            "visual_intent": "The page incorrectly advances again.",
                        },
                    ],
                }
            ],
        })
    )
    page_map = _PageMapEntry(
        page_number=1,
        beat_ids=("beat_0035", "beat_0036"),
        lettering_ids=(),
        emphasis="initial",
        density_intent="standard",
        rhythm_intent="The action advances.",
    )

    errors = _detail_matches_map(draft, (page_map,))

    assert errors
    assert "monotonic" in " ".join(errors)


@pytest.mark.parametrize("defect", ["rewound_beats", "base_state", "cross_entity_state", "unknown_entity"])
def test_two_pass_detail_retry_repairs_invalid_detail_at_the_batch_boundary(
    tmp_path: Path, defect: str,
) -> None:
    adaptation = _long_adaptation()
    calls: list[dict] = []
    detail_attempts: dict[tuple[int, ...], int] = {}
    inventory = ApprovedVisualReferenceInventory(references=[
        *_inventory().references,
        ApprovedVisualReference(id="wet_reference", entity_id="character_johansen",
                                appearance_state_id="wet", visual_anchor="soaked coat"),
    ])
    invalid_batch_start = 1 if defect == "rewound_beats" else 9

    async def generate(**request):
        calls.append(request)
        if request["feature"] == "plan.map":
            return ApiResult(
                value=plan_response({
                    "rhythm_summary": "Twelve measured story pages.",
                    "pages": [
                        {
                            "beat_ids": [
                                f"beat_{index:04d}",
                                f"beat_{index + 1:04d}",
                            ],
                            "lettering_ids": [f"lettering_{index:04d}", f"lettering_{index + 1:04d}"],
                            "emphasis": "initial",
                            "density_intent": "standard",
                            "rhythm_intent": f"Advance events {index} and {index + 1}.",
                        }
                        for index in range(1, 25, 2)
                    ],
                }),
                usage=None,
            )

        match = re.search(
            r'"target_page_numbers":\[(.*?)\]',
            request["user_content"],
        )
        assert match is not None
        page_numbers = tuple(
            int(value) for value in match.group(1).split(",") if value
        )
        attempt = detail_attempts.get(page_numbers, 0)
        detail_attempts[page_numbers] = attempt + 1
        if attempt and defect != "rewound_beats":
            assert "reference_authority" in request["user_content"]
            assert "page_009_content_001" in request["user_content"]
            assert "PREVIOUS DETAIL" in request["user_content"]
        pages = []
        for page_number in page_numbers:
            first_beat = (page_number - 1) * 2 + 1
            beat_ids = (
                f"beat_{first_beat:04d}",
                f"beat_{first_beat + 1:04d}",
            )
            if defect == "rewound_beats" and attempt == 0 and page_number == 1:
                content_beats = [
                    (beat_ids[0], "The first beat begins."),
                    (beat_ids[1], "The second beat advances the action."),
                    (beat_ids[0], "The invalid detail returns backward."),
                    (beat_ids[1], "The invalid detail advances again."),
                ]
            else:
                content_beats = [
                    (beat_ids[0], "The first mapped beat advances in order."),
                    (beat_ids[1], "The second mapped beat advances in order."),
                ]
            content = [
                {
                    "beat_ids": beats.split("|"),
                    "lettering_ids": [beats.replace("beat_", "lettering_")],
                    "panel_role": "standard",
                    "visual_intent": visual_intent,
                    "entity_ids": [],
                }
                for beats, visual_intent in content_beats
            ]
            if defect == "rewound_beats":
                for panel in content[2:]:
                    panel["lettering_ids"] = []
            if defect != "rewound_beats":
                content[0]["entity_ids"] = ["character_johansen", "location_alert"]
                content[0]["appearance_states"] = [{"entity_id": "character_johansen", "state_id": "wet"}]
                if attempt == 0 and page_number == 9:
                    if defect == "unknown_entity":
                        content[0]["entity_ids"].append("invented_character")
                    else:
                        content[0]["appearance_states"] = [{
                            "entity_id": "location_alert" if defect == "cross_entity_state" else "character_johansen",
                            "state_id": "wet" if defect == "cross_entity_state" else "base",
                        }]
            pages.append(
                {
                    "emphasis": "initial",
                    "density_intent": "standard",
                    "rhythm_intent": f"Advance page {page_number}.",
                    "layout_intent": "Ordered story moments.",
                    "content": content,
                }
            )
        return ApiResult(
            value=detail_response({"rhythm_summary": "Local detail.", "pages": pages}),
            usage=None,
        )

    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            inventory,
            ApprovedPageRange(minimum=12, maximum=12),
            artifacts=TargetArtifacts(tmp_path),
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="rewound-detail",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(plan.pages) == 12
    assert detail_attempts[tuple(range(1, 9))] == (2 if invalid_batch_start == 1 else 1)
    assert detail_attempts[tuple(range(9, 13))] == (2 if invalid_batch_start == 9 else 1)
    assert [call["feature"] for call in calls].count("plan.map") == 1
    map_call = next(call for call in calls if call["feature"] == "plan.map")
    assert map_call["max_output_tokens"] == _PAGE_MAP_MAX_OUTPUT_TOKENS
    assert [call["feature"] for call in calls].count("plan.detail") == 3
    if defect != "rewound_beats":
        page = TargetArtifacts(tmp_path).read_page(9)
        assert page.content[0].appearance_states == {"character_johansen": "wet"}
        assert page.content[0].lettering == (adaptation.beats[16].lettering[0],)


@pytest.mark.parametrize("beat_count,upper_target,expected", [(2, 2, 64), (42, 34, 64), (120, 34, 144), (24, 120, 144)])
def test_default_plan_budget_covers_review_and_repairs_and_scales_with_book(beat_count, upper_target, expected):
    from novel_to_comic.page_planning import _default_plan_call_limit

    assert _default_plan_call_limit(_long_adaptation(beat_count),
                                   ApprovedPageRange(minimum=1, maximum=upper_target)) == expected


@pytest.mark.parametrize("unresolved", [False, True])
def test_map_schema_corrections_do_not_consume_narrative_revision(tmp_path, monkeypatch, unresolved):
    from novel_to_comic.models.validation import InvariantFailure
    from novel_to_comic.page_planning import _generate_page_map

    adaptation = _long_adaptation(24)
    target = TargetArtifacts(tmp_path)
    ctx = StageRuntime("plan", PipelineState(project_name="map-revision", novel_path="novel.txt",
                       created_at=datetime.now(timezone.utc)), tmp_path)
    calls, reviews = [], []
    async def generate(**request):
        calls.append(request)
        assert request["feature"] == "plan.map"
        if len(calls) >= 3:
            assert "Move the revealing words" in request["user_content"]
        raw = {"rhythm_summary": "A reveal.", "pages": [
            {"beat_ids": [b.id], "lettering_ids": [i.id for i in b.lettering],
             "emphasis": "initial", "density_intent": "standard", "rhythm_intent": b.summary}
            for b in adaptation.beats
        ]}
        if len(calls) in (1, 3):
            raw["pages"][0]["placeholder_removed"] = False
        return ApiResult(value=plan_response(raw))
    async def review(context, **kwargs):
        reviews.append(context)
        if len(reviews) == 1 or unresolved:
            return (InvariantFailure(id="reveal", owner_stage="plan", code="narrative_review_rushed_sequence",
                                     message="Reveal precedes its page turn.", artifact_ids=["page_001", "page_002"],
                                     evidence=["Move the revealing words to the reveal page."]),)
        return ()
    monkeypatch.setattr("novel_to_comic.page_planning.review_narrative", review)
    if unresolved:
        with pytest.raises(PlanInvariantError):
            asyncio.run(produce_book_plan(adaptation, _inventory(), ApprovedPageRange(minimum=24, maximum=24),
                artifacts=target, ctx=ctx, model="test", generate=generate))
        saved = target.read_validation("plan")
        assert saved.attempts == 2 and len(saved.attempt_history) == 2
        assert not target.plan_path.exists()
    else:
        _, history = asyncio.run(_generate_page_map(adaptation, ApprovedPageRange(minimum=24, maximum=24),
            generate=generate, ctx=ctx, artifacts=target, model="test"))
        assert history[0].invariant_codes == ("narrative_review_rushed_sequence",)
        assert history[1].invariant_codes == ()
    assert len(calls) == 4 and len(reviews) == 2


def test_invalid_reference_detail_stops_after_bounded_correction_with_page_location(tmp_path):
    from novel_to_comic.page_planning import _generate_detail_batch, _concern_batch_indexes

    adaptation = _long_adaptation(10)
    page_map = _BookPageMap.model_validate({"rhythm_summary": "One event per page.", "pages": [
        {"page_number": n, "beat_ids": [b.id], "lettering_ids": [i.id for i in b.lettering],
         "emphasis": "initial", "density_intent": "standard", "rhythm_intent": "Advance."}
        for n, b in enumerate(adaptation.beats, 1)
    ]})
    calls = []
    async def generate(**request):
        calls.append(request)
        assert "The approved page map has already resolved global allocation" in request["user_content"]
        assert "Reallocate pages, panels, rhythm" not in request["user_content"]
        variants = request["json_schema"]["$defs"]["_PageDetailDraft"]["anyOf"]
        assert variants[0]["properties"]["page_number"]["enum"] == [9]
        return ApiResult(value=detail_response({"rhythm_summary": "Page nine.", "pages": [{
            "page_number": 1, "emphasis": "initial", "density_intent": "standard",
            "rhythm_intent": "Advance.", "layout_intent": "One event.",
            "content": [{"beat_ids": ["beat_0009"], "lettering_ids": ["lettering_0009"],
                         "visual_intent": "Johansen watches.", "entity_ids": ["character_johansen"],
                         "appearance_states": [{"entity_id": "character_johansen", "state_id": "base"}]}],
        }]}))
    with pytest.raises(PlanInvariantError) as exc:
        asyncio.run(_generate_detail_batch(
            adaptation, _inventory(), page_map, start=8, stop=9, generate=generate,
            ctx=StageRuntime("plan", PipelineState(project_name="invalid-reference", novel_path="novel.txt",
                             created_at=datetime.now(timezone.utc)), tmp_path),
            story_instruction="Keep the sailor's earlier appearance in this recollection.",
        ))
    assert len(calls) == 2
    failures = exc.value.validation.invariant_failures
    assert [f.code for f in failures] == ["reference_authority"]
    assert "page_009_content_001" in failures[0].artifact_ids
    assert "character_johansen:base" in failures[0].artifact_ids
    assert _concern_batch_indexes(failures, page_count=10) == {1: [failures[0]]}
    assert not TargetArtifacts(tmp_path).plan_path.exists()


def test_draft_reference_validation_precedes_derived_state_activation():
    from novel_to_comic.page_planning import _validate_plan_draft

    adaptation = _adaptation()
    beat = adaptation.beats[0].model_copy(update={"appearance_changes": (
        AppearanceChange(entity_id="character_johansen", to_state_id="wet", description="Spray soaks his coat."),
    )})
    adaptation = adaptation.model_copy(update={"beats": (beat, adaptation.beats[1])})
    inventory = ApprovedVisualReferenceInventory(references=[
        *_inventory().references,
        ApprovedVisualReference(id="wet_reference", entity_id="character_johansen",
                                appearance_state_id="wet", visual_anchor="soaked coat"),
    ])
    raw = {"rhythm_summary": "Approach and escape.", "pages": [{
        "emphasis": "release", "density_intent": "sparse", "rhythm_intent": "Escape.",
        "layout_intent": "The escape.", "content": [{
            "beat_ids": [b.id for b in adaptation.beats],
            "lettering_ids": [i.id for b in adaptation.beats for i in b.lettering],
            "visual_intent": "Johansen escapes through spray.", "entity_ids": ["character_johansen"],
            "appearance_states": [{"entity_id": "character_johansen", "state_id": "base"}],
        }],
    }]}
    target = ApprovedPageRange(minimum=1, maximum=1)
    pages, validation = _validate_plan_draft(adaptation, inventory, target, _BookPlanDraft.model_validate(plan_response(raw)), {})
    assert pages == ()
    assert [f.code for f in validation.invariant_failures] == ["reference_authority"]
    raw["pages"][0]["content"][0]["appearance_states"] = []
    pages, validation = _validate_plan_draft(adaptation, inventory, target, _BookPlanDraft.model_validate(plan_response(raw)), {})
    assert not any(f.code == "reference_authority" for f in validation.invariant_failures)
    assert pages[0].content[0].appearance_states == {"character_johansen": "wet"}


def test_long_plan_retains_composition_warnings_without_automatic_polishing(
    tmp_path: Path,
) -> None:
    adaptation = _long_adaptation()
    calls: list[dict] = []
    detail_targets: list[tuple[int, ...]] = []
    progress_at_repair: list[tuple[int, int]] = []
    state = PipelineState(
        project_name="long-plan",
        novel_path="novel.txt",
        created_at=datetime.now(timezone.utc),
    )

    async def generate(**request):
        calls.append(request)
        if request["feature"] == "plan.map":
            return ApiResult(
                value=plan_response({
                    "rhythm_summary": "Twenty-four measured story pages.",
                    "pages": [
                        {
                            "beat_ids": [f"beat_{index:04d}"],
                            "lettering_ids": [item.id for item in adaptation.beats[index - 1].lettering],
                            "emphasis": "initial",
                            "density_intent": "standard",
                            "rhythm_intent": f"Advance event {index}.",
                        }
                        for index in range(1, 25)
                    ],
                }),
                usage=None,
            )

        match = re.search(
            r'"target_page_numbers":\[(.*?)\]',
            request["user_content"],
        )
        assert match is not None
        page_numbers = tuple(int(value) for value in match.group(1).split(",") if value)
        detail_targets.append(page_numbers)
        repairing = "repetitive_page_composition" in request["user_content"]
        if repairing:
            progress_at_repair.append(
                (state.stages["plan"].items_done, state.stages["plan"].items_total)
            )
        pages = []
        for page_number in page_numbers:
            panel_count = 1 if page_number <= 4 and not repairing else 2
            pages.append(
                {
                    "emphasis": "initial",
                    "density_intent": "standard",
                    "rhythm_intent": f"Advance event {page_number}.",
                    "layout_intent": f"{panel_count} supported visual moments.",
                    "content": [
                        {
                            "beat_ids": [f"beat_{page_number:04d}"],
                            "panel_role": ("standard" if panel == 1 else "reaction"),
                            "visual_intent": (f"Visual moment {page_number}.{panel}."),
                            "lettering_ids": [f"lettering_{page_number:04d}"] if panel == 1 else [],
                            "entity_ids": [],
                        }
                        for panel in range(1, panel_count + 1)
                    ],
                }
            )
        return ApiResult(
            value=detail_response({"rhythm_summary": "Local detail.", "pages": pages}),
            usage=None,
        )

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            ApprovedVisualReferenceInventory(),
            ApprovedPageRange(minimum=24, maximum=24),
            artifacts=artifacts,
            ctx=StageRuntime("plan", state, tmp_path),
            model="test-planner",
            generate=generate,
        )
    )

    assert [call["feature"] for call in calls].count("plan.map") == 1
    assert [call["feature"] for call in calls].count("plan.detail") == 3
    assert detail_targets.count(tuple(range(1, 9))) == 1
    assert detail_targets.count(tuple(range(9, 17))) == 1
    assert detail_targets.count(tuple(range(17, 25))) == 1
    assert all("json_schema" in call for call in calls)
    assert len(plan.pages) == 24
    assert len(artifacts.read_page(1).content) == 1
    assert artifacts.read_page(1).content[0].lettering[0].id == "lettering_0001"
    assert progress_at_repair == []
    assert state.stages["plan"].items_done == state.stages["plan"].items_total == 5


def test_two_pass_plan_corrects_explicit_lettering_order_at_detail_boundary(
    tmp_path: Path,
) -> None:
    adaptation = _long_adaptation_with_multiple_lettering_items()
    calls: list[dict] = []
    detail_attempts: dict[tuple[int, ...], int] = {}

    async def generate(**request):
        calls.append(request)
        if request["feature"] == "plan.map":
            return ApiResult(
                value=plan_response({
                    "rhythm_summary": "Twenty-four measured story pages.",
                    "pages": [
                        {
                            "beat_ids": [f"beat_{index:04d}"],
                            "lettering_ids": [item.id for item in adaptation.beats[index - 1].lettering],
                            "emphasis": "initial",
                            "density_intent": "standard",
                            "rhythm_intent": f"Advance event {index}.",
                        }
                        for index in range(1, 25)
                    ],
                }),
                usage=None,
            )

        match = re.search(
            r'"target_page_numbers":\[(.*?)\]',
            request["user_content"],
        )
        assert match is not None
        page_numbers = tuple(
            int(value) for value in match.group(1).split(",") if value
        )
        attempt = detail_attempts.get(page_numbers, 0)
        detail_attempts[page_numbers] = attempt + 1
        pages = []
        for page_number in page_numbers:
            panel_count = (page_number % 3) + 1
            lettering_ids_by_panel = [[] for _ in range(panel_count)]
            lettering_ids_by_panel[0] = [item.id for item in adaptation.beats[page_number - 1].lettering]
            if page_number == 1:
                ids = ["lettering_0001", "lettering_0001_second"]
                if attempt == 0:
                    ids.reverse()
                lettering_ids_by_panel[0] = [ids[0]]
                lettering_ids_by_panel[1] = [ids[1]]
            pages.append(
                {
                    "emphasis": "initial",
                    "density_intent": "standard",
                    "rhythm_intent": f"Advance event {page_number}.",
                    "layout_intent": "One supported visual moment.",
                    "content": [
                        {
                            "beat_ids": [f"beat_{page_number:04d}"],
                            "panel_role": (
                                "standard" if panel == 1 else "detail"
                            ),
                            "visual_intent": (
                                f"Visual moment {page_number}.{panel}."
                            ),
                            "lettering_ids": lettering_ids_by_panel[panel - 1],
                            "entity_ids": ["character_johansen"],
                            "appearance_states": [
                                {
                                    "entity_id": "character_johansen",
                                    "state_id": "johansen_soaked",
                                },
                            ],
                        }
                        for panel in range(1, panel_count + 1)
                    ],
                }
            )
        return ApiResult(
            value=detail_response({"rhythm_summary": "Local detail.", "pages": pages}),
            usage=None,
        )

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            _soaked_inventory(),
            ApprovedPageRange(minimum=24, maximum=24),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="long-plan-lettering",
                    novel_path="novel.txt",
                    created_at=datetime.now(timezone.utc),
                ),
                tmp_path,
            ),
            model="test-planner",
            generate=generate,
        )
    )

    assert len(plan.pages) == 24
    assert [call["feature"] for call in calls].count("plan.map") == 1
    assert [call["feature"] for call in calls].count("plan.detail") == 4
    assert detail_attempts[tuple(range(1, 9))] == 2
    assert [
        item.id
        for content in artifacts.read_page(1).content
        for item in content.lettering
    ] == ["lettering_0001", "lettering_0001_second"]
    for page_number in range(1, 25):
        assert all(
            content.appearance_states == {"character_johansen": "johansen_soaked"}
            for content in artifacts.read_page(page_number).content
        )
    assert tuple(
        item
        for page_number in range(1, 25)
        for content in artifacts.read_page(page_number).content
        for item in content.lettering
    ) == tuple(item for beat in adaptation.beats for item in beat.lettering)


def test_plan_corrects_lettering_with_visual_intent_across_repeated_beat_panels(
    tmp_path: Path,
) -> None:
    payload = _adaptation().model_dump(mode="json")
    payload["content_sha256"] = ""
    first_lettering = payload["beats"][0]["lettering"][0]
    payload["beats"][0]["lettering"] = [
        first_lettering,
        {
            **first_lettering,
            "id": "lettering_0001_second",
            "text": "The reef rises again.",
        },
    ]
    adaptation = BookAdaptation.model_validate(payload)
    response = {
        "rhythm_summary": "The approach repeats before the turn.",
        "pages": [
            {
                "page_number": 1,
                "page_turn_role": "setup",
                "spread_role": "single",
                "emphasis": "prolongation",
                "density_intent": "standard",
                "rhythm_intent": "Hold on the approach.",
                "layout_intent": "Two adjacent approach panels.",
                "content": [
                    {
                        "beat_ids": ["beat_0001"],
                        "visual_intent": "The first approach panel.",
                        "lettering_ids": ["lettering_0001_second"],
                    },
                    {
                        "beat_ids": ["beat_0001"],
                        "visual_intent": "The second approach panel.",
                        "lettering_ids": ["lettering_0001"],
                    },
                ],
            },
            {
                "page_number": 2,
                "page_turn_role": "release",
                "spread_role": "single",
                "emphasis": "release",
                "density_intent": "standard",
                "rhythm_intent": "The turn follows the approach.",
                "layout_intent": "The yacht turns away.",
                "content": [
                    {
                        "beat_ids": ["beat_0002"],
                        "visual_intent": "Johansen turns the yacht away.",
                        "lettering_ids": ["lettering_0002"],
                    }
                ],
            },
        ],
    }
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        value = json.loads(json.dumps(response))
        if len(calls) == 2:
            panels = value["pages"][0]["content"]
            panels[0]["lettering_ids"] = ["lettering_0001"]
            panels[0]["visual_intent"] = "Johansen first sights the reef."
            panels[1]["lettering_ids"] = ["lettering_0001_second"]
            panels[1]["visual_intent"] = "The reef rises again beyond the yacht."
        return ApiResult(value=plan_response(value))

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(
        produce_book_plan(
            adaptation,
            ApprovedVisualReferenceInventory(),
            ApprovedPageRange(minimum=2, maximum=2),
            artifacts=artifacts,
            ctx=StageRuntime(
                "plan",
                PipelineState(
                    project_name="repeated-lettering",
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
    assert response["pages"][0]["content"][0]["lettering_ids"] == ["lettering_0001_second"]
    assert [
        item.id
        for page in plan.pages
        for content in artifacts.read_page(page.page_number).content
        for item in content.lettering
    ] == ["lettering_0001", "lettering_0001_second", "lettering_0002"]


def test_producer_keeps_repetitive_composition_advisory(
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
        return ApiResult(value=plan_response(responses[len(calls) - 1]))

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

    assert len(calls) == 1
    assert plan.rhythm_summary == repetitive["rhythm_summary"]
    assert len(artifacts.read_page(1).content) == 1
    assert "repetitive_page_composition" in {issue.code for issue in plan.editorial_issues}


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
        "score" not in failure.model_dump() for failure in validation.invariant_failures
    )


def test_plan_can_expand_one_adapted_beat_across_adjacent_planned_panels(
    tmp_path: Path,
) -> None:
    calls: list[dict] = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(
            value=plan_response({
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
            })
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
            value=plan_response(response),
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
    ] == [item.model_dump() for beat in adaptation.beats for item in beat.lettering]
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
            value=plan_response(unknown),
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

    assert [failure.code for failure in raised.value.validation.invariant_failures] == [
        "unknown_lettering"
    ]


def test_plan_persists_reviewed_allocation_above_target(
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
            value=plan_response(response),
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
    validation = artifacts.read_validation("plan")
    assert not validation.invariant_failures
    assert len(artifacts.read_plan().pages) == 2
    assert artifacts.read_plan().target_page_max == 1


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
        ],
    }

    async def generate(**_kwargs):
        return ApiResult(
            value=plan_response(response),
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


def test_safe_allocation_can_exceed_advisory_range() -> None:
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

    assert not validation.invariant_failures


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
        ApprovedPageRange(minimum=1, maximum=1),
        pages,
    )

    assert "target_page_range_conflict" not in {
        failure.code for failure in validation.invariant_failures
    }


def test_complete_allocation_can_be_shorter_than_target() -> None:
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
        ApprovedPageRange(minimum=4, maximum=8),
        pages,
    )

    assert not validation.invariant_failures


def test_onscreen_lettering_speaker_must_be_visible_in_its_panel() -> None:
    payload = _adaptation().model_dump(mode="json")
    payload["content_sha256"] = ""
    payload["beats"][1]["lettering"][0]["speaker_entity_id"] = "character_johansen"
    payload["beats"][1]["lettering"][0]["delivery"] = "onscreen"
    adaptation = BookAdaptation.model_validate(payload)
    page = ComicPage(
        page_number=1,
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        page_turn_role="release",
        spread_role="single",
        emphasis="release",
        density_intent="standard",
        layout_intent="The order is given from off frame.",
        content=[
            PageContent(
                id="page_001_content_001",
                order=1,
                beat_ids=["beat_0001", "beat_0002"],
                visual_intent="The Alert turns while Johansen remains unseen.",
                lettering=[
                    item for beat in adaptation.beats for item in beat.lettering
                ],
                entity_ids=["location_alert"],
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
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=2),
        [page],
    )

    failure = next(
        item
        for item in validation.invariant_failures
        if item.code == "lettering_speaker_visibility"
    )
    assert failure.artifact_ids == (
        "page_001_content_001",
        "lettering_0002",
        "character_johansen",
    )


def test_book_plan_preserves_an_approved_floor_after_valid_allocation() -> None:
    adaptation = _adaptation()
    plan = BookPlan(
        revision=1,
        adaptation_revision=adaptation.revision,
        adaptation_sha256=adaptation.content_sha256,
        target_page_min=32,
        target_page_max=40,
        rhythm_summary="Complete at the approved narrative floor.",
        pages=[
            PlannedPageRevision(
                page_number=index,
                revision=1,
                content_sha256="0" * 64,
            )
            for index in range(1, 33)
        ],
    )
    assert len(plan.pages) == 32
    assert plan.target_page_min == 32


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
        issue for issue in validation.editorial_issues if issue.code == "weak_page_turn"
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

    assert "weak_page_turn" not in {issue.code for issue in validation.editorial_issues}


def test_cthulhu_plan_preserves_approach_peak_escape_release_and_aftermath_rhythm(
    tmp_path: Path,
) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "cthulhu_plan_rhythm.json").read_text()
    )
    adaptation = BookAdaptation.model_validate(fixture["adaptation"])
    inventory = ApprovedVisualReferenceInventory.model_validate(fixture["references"])
    target_range = ApprovedPageRange.model_validate(fixture["target_range"])

    async def generate(**_kwargs):
        return ApiResult(
            value=plan_response(fixture["plan_response"]),
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
    assert plan.rhythm_summary == ("approach → Peak → escape → Release → aftermath")
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
                    item for beat in adaptation.beats for item in beat.lettering
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
                    item for beat in adaptation.beats for item in beat.lettering
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
        (Path(__file__).parent / "fixtures" / "cthulhu_plan_rhythm.json").read_text()
    )
    adaptation = BookAdaptation.model_validate(fixture["adaptation"])
    inventory = ApprovedVisualReferenceInventory.model_validate(fixture["references"])
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
    # Silence alone is not evidence of a causal gap and must not trigger a
    # paid editorial repair of an otherwise canonical visual sequence.
    assert "sustained_silent_pages" not in {
        issue.code for issue in validation.editorial_issues
    }


def test_peak_and_release_on_one_page_report_proportion_evidence() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "cthulhu_plan_rhythm.json").read_text()
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
    assert failure.evidence == ("Pages 1 and 2 both declare spread side 'left'.",)


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
                    item for beat in adaptation.beats for item in beat.lettering
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
            value=plan_response(responses[len(calls) - 1]),
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
        return ApiResult(value=plan_response(response))

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
    issue = next(
        issue for issue in plan.editorial_issues if issue.id == "plan_issue_test"
    )
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
                        "appearance_states": [
                            {"entity_id": "character_johansen", "state_id": "johansen_soaked"},
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
                        "beat_ids": ["beat_0002"],
                        "visual_intent": "The approach resolves into escape.",
                        "lettering_ids": ["lettering_0002"],
                        "entity_ids": ["character_johansen", "location_alert"],
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
        return ApiResult(value=plan_response(response))

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
    assert artifacts.read_page(1).content[0].appearance_states == {"character_johansen": "johansen_soaked"}
    assert artifacts.read_page(2).content[0].beat_ids == ("beat_0002",)
    assert artifacts.read_page(2).content[0].appearance_states == {"character_johansen": "johansen_soaked"}


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
        return ApiResult(value=plan_response(responses[len(calls) - 1]))

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
        return ApiResult(value=plan_response(response))

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




def test_planning_view_excludes_the_source_ledger_and_provenance() -> None:
    adaptation = _adaptation()
    view = _planning_view(adaptation)
    serialized = json.dumps(view)

    assert "ledger" not in view
    assert "source_unit_ids" not in serialized
    assert "content_sha256" not in serialized
    assert "The reef rose before us." in serialized
    assert "speaker_entity_id" in serialized


def test_plan_prompt_makes_both_page_targets_advisory() -> None:

    prompt = build_book_plan_prompt(
        _adaptation(),
        _inventory(),
        ApprovedPageRange(minimum=1, maximum=2),
    )

    assert "not a floor or ceiling" in prompt
    assert "Never pad the ending" in prompt


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
                        "appearance_states": [],
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
        return ApiResult(value=plan_response(response))

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


def test_plan_preserves_explicit_state_bindings_and_exact_lettering(tmp_path: Path) -> None:
    adaptation = _adaptation()
    artifacts, calls, plan = _run_plan(
        adaptation,
        _soaked_inventory(),
        _two_page_response({
            "entity_ids": ["character_johansen", "location_alert"],
            "appearance_states": [
                {"entity_id": "character_johansen", "state_id": "johansen_soaked"},
            ],
        }),
        tmp_path,
    )

    assert isinstance(plan, BookPlan)
    assert len(calls) == 1
    assert artifacts.read_page(1).content[0].appearance_states == {
        "character_johansen": "johansen_soaked",
    }
    assert artifacts.read_page(2).content[0].appearance_states == {}
    assert tuple(
        item
        for page_number in (1, 2)
        for content in artifacts.read_page(page_number).content
        for item in content.lettering
    ) == tuple(item for beat in adaptation.beats for item in beat.lettering)


def test_plan_derives_visibility_from_an_explicit_state_binding(tmp_path: Path) -> None:
    # A planner can omit an entity from entity_ids while still naming one of
    # its approved appearance states. The state binding is an unambiguous
    # declaration that the entity is depicted, so canonicalization should
    # repair the redundant omission without buying a retry.
    artifacts, calls, plan = _run_plan(
        _adaptation(),
        _soaked_inventory(),
        _two_page_response({
            "entity_ids": ["location_alert"],
            "appearance_states": [
                {"entity_id": "character_johansen", "state_id": "johansen_soaked"},
            ],
        }),
        tmp_path,
    )

    assert isinstance(plan, BookPlan)
    assert len(calls) == 1
    content = artifacts.read_page(1).content[0]
    assert content.entity_ids == ("location_alert", "character_johansen")
    assert content.appearance_states == {"character_johansen": "johansen_soaked"}


@pytest.mark.parametrize("second_state", ["johansen_soaked", "johansen_dry"])
def test_plan_draft_rejects_duplicate_entity_state_bindings(second_state: str) -> None:
    response = _two_page_response({
        "appearance_states": [
            {"entity_id": "character_johansen", "state_id": "johansen_soaked"},
            {"entity_id": "character_johansen", "state_id": second_state},
        ],
    })

    with pytest.raises(ValidationError) as caught:
        _BookPlanDraft.model_validate(plan_response(response))

    assert any(
        error["loc"][:4] == ("pages", 0, "content", 0)
        for error in caught.value.errors()
    )


def test_plan_preserves_shared_state_id_for_distinct_entities(tmp_path: Path) -> None:
    adaptation = _adaptation()
    entities = ("character_johansen", "location_alert")
    inventory = ApprovedVisualReferenceInventory(references=[
        *_inventory().references,
        *[
            ApprovedVisualReference(
                id=f"ref_{entity_id}_soaked",
                entity_id=entity_id,
                appearance_state_id="soaked",
                visual_anchor=f"{entity_id}; soaked by sea spray",
            )
            for entity_id in entities
        ],
    ])
    artifacts, calls, plan = _run_plan(
        adaptation,
        inventory,
        _two_page_response({
            "entity_ids": list(entities),
            "appearance_states": [
                {"entity_id": entity_id, "state_id": "soaked"}
                for entity_id in entities
            ],
        }),
        tmp_path,
    )

    assert isinstance(plan, BookPlan)
    assert len(calls) == 1
    assert artifacts.read_page(1).content[0].appearance_states == {
        "character_johansen": "soaked",
        "location_alert": "soaked",
    }


def _onscreen_adaptation() -> BookAdaptation:
    payload = _adaptation().model_dump(mode="json")
    payload["content_sha256"] = ""
    payload["beats"][1]["lettering"][0]["delivery"] = "onscreen"
    payload["beats"][1]["lettering"][0]["speaker_entity_id"] = (
        "character_johansen"
    )
    return BookAdaptation.model_validate(payload)


def test_plan_derives_onscreen_speaker_entity_citation_without_retry(
    tmp_path: Path,
) -> None:
    response = _two_page_response({"entity_ids": ["location_alert"]})
    response["pages"][1]["content"][0]["entity_ids"] = ["location_alert"]

    artifacts, calls, plan = _run_plan(
        _onscreen_adaptation(),
        _inventory(),
        response,
        tmp_path,
    )

    assert isinstance(plan, BookPlan)
    assert len(calls) == 1
    assert artifacts.read_page(2).content[0].entity_ids == (
        "location_alert",
        "character_johansen",
    )


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
    assert content.appearance_states == {"character_johansen": "johansen_soaked"}
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
                "appearance_states": [
                    {"entity_id": "character_johansen", "state_id": "johansen_soaked"},
                ],
            }
        ),
        tmp_path,
    )

    assert isinstance(plan, BookPlan)
    content = artifacts.read_page(1).content[0]
    assert content.entity_ids == ("character_johansen", "location_alert")
    assert content.appearance_states == {"character_johansen": "johansen_soaked"}


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


def test_detail_context_prunes_only_explicit_scopes_and_keeps_speakers():
    from novel_to_comic.page_planning import _BookPageMap, _detail_batch_prompt

    adaptation = _adaptation()
    beats = tuple(beat.model_copy(update={'entity_ids': ('location_alert',)}) for beat in adaptation.beats)
    second = beats[1].model_copy(update={'lettering': (beats[1].lettering[0].model_copy(update={'speaker_entity_id': 'character_johansen'}),)})
    adaptation = adaptation.model_copy(update={'beats': (beats[0], second)})
    inventory = _inventory().model_copy(update={'references': (*_inventory().references,
        ApprovedVisualReference(id='unrelated', entity_id='unrelated', visual_anchor='unrelated distant mansion'))})
    mapping = _BookPageMap(rhythm_summary='Two beats.', pages=(
        _PageMapEntry(page_number=1, beat_ids=tuple(beat.id for beat in beats), lettering_ids=tuple(item.id for beat in beats for item in beat.lettering), emphasis='release', density_intent='standard', rhythm_intent='Two beats.'),
    ))
    prompt = _detail_batch_prompt(adaptation, inventory, mapping, start=0, stop=1)
    assert 'unrelated distant mansion' not in prompt
    assert 'gaunt Norwegian sailor' in prompt
    assert 'small steam yacht' in prompt


def test_all_plan_prompts_preserve_restrained_depiction_and_exact_lettering():
    from novel_to_comic.narrative_instructions import PLAN_DEPICTION_GUIDANCE
    from novel_to_comic.page_planning import _build_page_map_prompt

    adaptation = _adaptation()
    target = ApprovedPageRange(minimum=1, maximum=2)
    page_map = _BookPageMap(rhythm_summary='One moment per page.', pages=[
        _PageMapEntry(page_number=index, beat_ids=(beat.id,), lettering_ids=tuple(item.id for item in beat.lettering), emphasis='initial',
                      density_intent='standard', rhythm_intent='Advance the scene.')
        for index, beat in enumerate(adaptation.beats, 1)
    ])
    for prompt in (
        build_book_plan_prompt(adaptation, _inventory(), target),
        _build_page_map_prompt(adaptation, target),
        _detail_batch_prompt(adaptation, _inventory(), page_map, start=0, stop=1),
    ):
        assert PLAN_DEPICTION_GUIDANCE in prompt
        context = json.loads(prompt.split('\n', 1)[1])
        for planned in context['planning_view']['beats']:
            original = next(beat for beat in adaptation.beats if beat.id == planned['id'])
            assert [item['text'] for item in planned['lettering']] == [item.text for item in original.lettering]


@pytest.mark.parametrize("placement", ["missing", "duplicate", "reversed", "wrong_page"])
def test_page_map_rejects_invalid_lettering_ownership_before_detail(placement):
    from novel_to_comic.page_planning import _validate_page_map

    adaptation = _adaptation()
    pages = [
        _PageMapEntry(
            beat_ids=(beat.id,), lettering_ids=tuple(item.id for item in beat.lettering),
            emphasis="initial", density_intent="standard", rhythm_intent="Advance.",
        )
        for beat in adaptation.beats
    ]
    if placement == "missing":
        pages[0] = pages[0].model_copy(update={"lettering_ids": ()})
    elif placement == "duplicate":
        pages[1] = pages[1].model_copy(update={"lettering_ids": (*pages[0].lettering_ids, *pages[1].lettering_ids)})
    elif placement == "reversed":
        pages[0], pages[1] = (
            pages[0].model_copy(update={"lettering_ids": pages[1].lettering_ids}),
            pages[1].model_copy(update={"lettering_ids": pages[0].lettering_ids}),
        )
    else:
        # The global order is correct, but one page does not carry the owning beat.
        pages[0] = pages[0].model_copy(update={"lettering_ids": (*pages[0].lettering_ids, *pages[1].lettering_ids)})
        pages[1] = pages[1].model_copy(update={"lettering_ids": ()})
    validation = _validate_page_map(
        adaptation, ApprovedPageRange(minimum=1, maximum=2),
        _BookPageMap(rhythm_summary="Two pages.", pages=pages),
    )
    assert [failure.code for failure in validation.invariant_failures] == ["lettering_allocation"]


def test_normalization_never_moves_fills_or_discards_authored_words():
    from copy import deepcopy
    from novel_to_comic.page_planning import _normalize_book_plan_draft

    raw = {"pages": [{"content": [
        {"beat_ids": ["beat_0001"], "visual_intent": "First action.", "lettering_ids": []},
        {"beat_ids": ["beat_0002"], "visual_intent": "Second action.", "lettering_ids": ["lettering_0002", "lettering_0002"]},
        {"beat_ids": ["beat_0001"], "visual_intent": "Wrong return.", "lettering_ids": ["lettering_0001"]},
    ]}]}
    original = deepcopy(raw)
    normalized = _normalize_book_plan_draft(raw, _adaptation())
    assert raw == original
    for actual, authored in zip(normalized["pages"][0]["content"], raw["pages"][0]["content"], strict=True):
        assert actual["lettering_ids"] == authored["lettering_ids"]
        assert actual["visual_intent"] == authored["visual_intent"]


def test_repeated_beat_across_parallel_detail_batches_has_one_lettering_owner(tmp_path):
    adaptation = _long_adaptation_with_multiple_lettering_items()
    map_pages = []
    for index, beat in enumerate(adaptation.beats, 1):
        ids = [item.id for item in beat.lettering]
        allocations = [[ids[0]], [ids[1]]] if index == 8 else [ids]
        for allocation in allocations:
            map_pages.append({
                "beat_ids": [beat.id], "lettering_ids": allocation,
                "emphasis": "initial", "density_intent": "standard",
                "rhythm_intent": "Continue the source event without replaying it.",
            })
    attempts = {}

    async def generate(**request):
        if request["feature"] == "plan.map":
            return ApiResult(value=plan_response({"rhythm_summary": "One event spans the batch boundary.", "pages": map_pages}))
        context, _ = json.JSONDecoder().raw_decode(request["user_content"].split("\n", 1)[1])
        numbers = tuple(context["target_page_numbers"])
        attempts[numbers] = attempts.get(numbers, 0) + 1
        pages = []
        for number in numbers:
            mapped = map_pages[number - 1]
            ids = mapped["lettering_ids"]
            # The second worker sees the same beat, but cannot reallocate its earlier words.
            if number == 9 and attempts[numbers] == 1:
                ids = ["lettering_0008", "lettering_0008_second"]
            pages.append({
                **{key: mapped[key] for key in ("emphasis", "density_intent", "rhythm_intent")},
                "layout_intent": "A source-supported action followed by a silent detail.",
                "content": [
                    {"beat_ids": mapped["beat_ids"], "visual_intent": "The assigned action.", "lettering_ids": ids},
                    {"beat_ids": mapped["beat_ids"], "visual_intent": "A distinct silent detail.", "lettering_ids": [], "panel_role": "detail"},
                ],
            })
        return ApiResult(value=detail_response({"rhythm_summary": "Local detail.", "pages": pages}))

    artifacts = TargetArtifacts(tmp_path)
    plan = asyncio.run(produce_book_plan(
        adaptation, ApprovedVisualReferenceInventory(), ApprovedPageRange(minimum=25, maximum=25),
        artifacts=artifacts, ctx=StageRuntime("plan", PipelineState(
            project_name="batch-boundary", novel_path="novel.txt", created_at=datetime.now(timezone.utc),
        ), tmp_path), model="test-planner", generate=generate,
    ))
    assert len(plan.pages) == 25
    assert attempts[tuple(range(1, 9))] == 1
    assert attempts[tuple(range(9, 17))] == 2
    assert tuple(item for page in plan.pages for content in artifacts.read_page(page.page_number).content for item in content.lettering) == tuple(
        item for beat in adaptation.beats for item in beat.lettering
    )


def _assigned_detail_fixture():
    adaptation = _long_adaptation_with_multiple_lettering_items()
    first, second = adaptation.beats[:2]
    ids = tuple(item.id for beat in (first, second) for item in beat.lettering)
    mapped = _PageMapEntry(
        page_number=30, beat_ids=(first.id, second.id), lettering_ids=ids,
        emphasis="initial", density_intent="standard", rhythm_intent="Two events.",
    )
    raw = {"rhythm_summary": "Ordered moments.", "pages": [{
        "page_number": 30, "emphasis": "initial", "density_intent": "standard",
        "rhythm_intent": "Two events.", "layout_intent": "Three voiced moments and a silent reaction.",
        "content": [
            {"beat_ids": [first.id], "visual_intent": "Establish the first event."},
            {"beat_ids": [second.id], "visual_intent": "The second event begins."},
            {"beat_ids": [second.id], "visual_intent": "The second event continues."},
            {"beat_ids": [second.id], "visual_intent": "A silent reaction."},
        ],
        # Object key order is immaterial; destinations and locked order are authoritative.
        "lettering_placements": {ids[3]: reservation(3), ids[1]: reservation(1), ids[0]: reservation(1), ids[2]: reservation(2)},
    }]}
    return adaptation, mapped, raw


def test_detail_assignments_compile_once_without_changing_authored_destinations():
    from copy import deepcopy
    from novel_to_comic.page_planning import _compile_detail_response, _detail_response_view

    adaptation, mapped, raw = _assigned_detail_fixture()
    original = deepcopy(raw)
    draft = _compile_detail_response(raw, (mapped,), adaptation)
    assert raw == original
    assert _detail_matches_map(draft, (mapped,)) == ()
    assert [panel.lettering_ids for panel in draft.pages[0].content] == [
        mapped.lettering_ids[:2], mapped.lettering_ids[2:3], mapped.lettering_ids[3:], (),
    ]
    assert [panel.visual_intent for panel in draft.pages[0].content] == [
        panel["visual_intent"] for panel in raw["pages"][0]["content"]
    ]
    repair_view = _detail_response_view(draft)
    assert repair_view["pages"][0]["lettering_placements"] == raw["pages"][0]["lettering_placements"]
    assert all("lettering_ids" not in panel for panel in repair_view["pages"][0]["content"])
    assert _compile_detail_response(repair_view, (mapped,), adaptation) == draft


@pytest.mark.parametrize("defect, expected", [
    ("missing", "missing"), ("foreign", "out-of-page"),
    ("nonexistent", "only 4 panels exist"), ("backward", "preserve locked lettering order"),
    ("wrong_beat", "visual beat citations must preserve mapped order"), ("zero", "greater than or equal to 1"),
    ("boolean", "valid integer"), ("list", "valid integer"),
    ("repeated_panel_copy", "Extra inputs are not permitted"),
])
def test_invalid_detail_assignments_require_authored_correction(defect, expected):
    from copy import deepcopy
    from novel_to_comic.page_planning import _compile_detail_response

    adaptation, mapped, raw = _assigned_detail_fixture()
    placements = raw["pages"][0]["lettering_placements"]
    last = mapped.lettering_ids[-1]
    if defect == "missing":
        del placements[last]
    elif defect == "foreign":
        placements["lettering_other_page"] = reservation(4)
    elif defect == "repeated_panel_copy":
        raw["pages"][0]["content"][-1]["lettering_ids"] = [mapped.lettering_ids[2]]
    else:
        placements[last]["panel_number"] = {"nonexistent": 5, "backward": 1, "zero": 0,
                            "boolean": True, "list": [3, 4], "wrong_beat": 3}[defect]
        if defect == "wrong_beat":
            raw["pages"][0]["content"][2]["beat_ids"] = [mapped.beat_ids[0]]
    original = deepcopy(raw)
    with pytest.raises(ValueError, match=expected):
        _compile_detail_response(raw, (mapped,), adaptation)
    assert raw == original


@pytest.mark.parametrize("visual_beat", [0, 1])
def test_panel_bridging_two_beats_derives_both_lettering_owners(visual_beat):
    """Reproduce the page-42 correction alternating beat 38 and beat 39."""
    from copy import deepcopy
    from novel_to_comic.page_planning import _compile_detail_response

    adaptation, mapped, raw = _assigned_detail_fixture()
    page = raw["pages"][0]
    page["content"][0]["beat_ids"] = [mapped.beat_ids[visual_beat]]
    page["lettering_placements"][mapped.lettering_ids[2]]["panel_number"] = 1
    original = deepcopy(raw)
    draft = _compile_detail_response(raw, (mapped,), adaptation)
    assert raw == original
    assert draft.pages[0].content[0].beat_ids == mapped.beat_ids
    assert _detail_matches_map(draft, (mapped,)) == ()
    for number, panel in enumerate(draft.pages[0].content, 1):
        assert panel.visual_intent == page["content"][number - 1]["visual_intent"]
        assert panel.lettering_ids == tuple(
            item_id for item_id in mapped.lettering_ids
            if page["lettering_placements"][item_id]["panel_number"] == number
        )


def test_provenance_compilation_does_not_accept_foreign_visual_citations():
    from novel_to_comic.page_planning import _compile_detail_response

    adaptation, mapped, raw = _assigned_detail_fixture()
    raw["pages"][0]["content"][0]["beat_ids"] = ["invented_beat"]
    with pytest.raises(ValueError, match="out-of-page visual beats"):
        _compile_detail_response(raw, (mapped,), adaptation)


def test_derived_provenance_still_rejects_a_backward_page_sequence():
    from novel_to_comic.page_planning import _compile_detail_response

    adaptation, mapped, raw = _assigned_detail_fixture()
    for panel in raw["pages"][0]["content"]:
        panel["beat_ids"] = [mapped.beat_ids[1]]
    raw["pages"][0]["lettering_placements"] = {item_id: reservation(2) for item_id in mapped.lettering_ids}
    draft = _compile_detail_response(raw, (mapped,), adaptation)
    # An unlettered later-beat visual precedes the earlier-beat captions.
    # Deriving owners cannot make that backward story sequence valid.
    assert _detail_matches_map(draft, (mapped,))


def test_silent_detail_page_requires_an_explicit_empty_assignment():
    from novel_to_comic.page_planning import _compile_detail_response

    adaptation, mapped, raw = _assigned_detail_fixture()
    mapped = mapped.model_copy(update={"lettering_ids": ()})
    raw["pages"][0]["lettering_placements"] = {}
    draft = _compile_detail_response(raw, (mapped,), adaptation)
    assert all(not panel.lettering_ids for panel in draft.pages[0].content)
    del raw["pages"][0]["lettering_placements"]
    with pytest.raises(ValidationError, match="lettering_placements"):
        _compile_detail_response(raw, (mapped,), adaptation)


def test_invalid_detail_destination_gets_one_bounded_correction(tmp_path):
    from copy import deepcopy
    from novel_to_comic.page_planning import _generate_detail_batch

    adaptation, mapped, raw = _assigned_detail_fixture()
    page_map = _BookPageMap(rhythm_summary="Two events.", pages=(mapped,))
    calls = []

    async def generate(**request):
        calls.append(request)
        value = deepcopy(raw)
        value["pages"][0]["lettering_placements"][mapped.lettering_ids[-1]]["panel_number"] = 5
        if len(calls) == 2:
            assert "targets panel 5" in request["user_content"]
            assert "PREVIOUS DETAIL:" in request["user_content"]
        return ApiResult(value=plan_response(value))

    with pytest.raises(PlanInvariantError) as error:
        asyncio.run(_generate_detail_batch(
            adaptation, _inventory(), page_map, start=0, stop=1, generate=generate,
            ctx=StageRuntime("plan", PipelineState(project_name="assignment", novel_path="novel.txt",
                             created_at=datetime.now(timezone.utc)), tmp_path),
        ))
    assert len(calls) == 2
    assert error.value.validation.invariant_failures[0].code == "beat_allocation"
    assert "targets panel 5" in error.value.validation.invariant_failures[0].evidence[0]
