"""Stage requests and schema names match fingerprints captured from pre-refactor HEAD."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from novel_to_comic import book_adaptation, page_planning
from novel_to_comic.models.page import ApprovedPageRange
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.stages import s2_style
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult
from tests.narrative_review_support import accept_narrative
from tests.test_book_adaptation import (
    _approved_brief, _blueprint_response, _book_adaptation, _lettering_response,
    _source_document, _story_bible,
)
from tests.test_page_planning import _adaptation, _inventory


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_stage_requests_and_schemas_keep_pre_refactor_fingerprints(tmp_path, monkeypatch):
    monkeypatch.setattr("novel_to_comic.validation_round.review_narrative", accept_narrative)
    expected = _book_adaptation()
    responses = [expected.treatment.model_dump(mode="json"),
                 _blueprint_response(expected.beats, include_legacy_ledger=True),
                 _lettering_response(expected.beats)]
    requests = []

    async def generate(**request):
        requests.append(request)
        return ApiResult(responses[len(requests) - 1])

    asyncio.run(book_adaptation.produce_book_adaptation(
        _source_document(), _story_bible(), _approved_brief(), artifacts=TargetArtifacts(tmp_path),
        ctx=StageRuntime("adapt", PipelineState(project_name="fingerprint", novel_path="novel.txt",
                                               created_at=datetime.now(timezone.utc)), tmp_path),
        model="test", generate=generate,
    ))
    actual = {request["feature"]: digest(request) for request in requests}
    actual.update({
        "plan.schema": digest(page_planning._plan_response_schema(_inventory())),
        "plan.prompt": digest(page_planning.build_book_plan_prompt(
            _adaptation(), _inventory(), ApprovedPageRange(minimum=1, maximum=4),
        )),
    })
    for name in ("StyleProduction", "StyleSketchBatch", "ProofCopy", "CustomDirectionDescription"):
        actual[f"style.{name}"] = digest(getattr(s2_style, name).model_json_schema())
    baseline = json.loads((Path(__file__).parent / "fixtures/stage_call_fingerprints.json").read_text())
    assert actual == baseline


def test_stale_lettering_checkpoint_is_priced_and_repaired_with_current_source_scope(tmp_path, monkeypatch):
    from novel_to_comic.models.adaptation import LetteringItem

    source, bible, brief = _source_document(), _story_bible(), _approved_brief()
    adaptation = _book_adaptation()
    target = TargetArtifacts(tmp_path)
    ids = tuple(unit.id for unit in source.units)
    requirements = book_adaptation.partition_requirements_by_shard(source, brief, (ids,))[0]
    treatment_prompt = book_adaptation.build_narrative_treatment_prompt(source, bible, brief)
    blueprint = book_adaptation._BlueprintDraft.model_validate(_blueprint_response(adaptation.beats))
    blueprint_prompt = book_adaptation.build_adaptation_blueprint_prompt(
        source, bible, brief, adaptation.treatment, primary_source_unit_ids=ids,
        owned_requirement_ids=requirements, shard_index=1, shard_count=1,
    )
    lettering_prompt = book_adaptation.build_locked_lettering_prompt(
        source, bible, brief, adaptation.treatment, blueprint,
        primary_source_unit_ids=ids, shard_index=1, shard_count=1,
    )
    invalid = book_adaptation._LetteringDraft(beats=[{
        "beat_id": adaptation.beats[0].id,
        "lettering": [LetteringItem.model_validate({
            **item.model_dump(), "source_unit_ids": ("source_999999",),
        }) for item in adaptation.beats[0].lettering],
    }])
    for name, feature, prompt, value in (
        ("treatment", "adapt.narrative_treatment", treatment_prompt, adaptation.treatment),
        ("blueprint/shard_001", "adapt.blueprint", blueprint_prompt, blueprint),
        ("lettering/shard_001", "adapt.lettering", lettering_prompt, invalid),
    ):
        book_adaptation._write_checkpoint(target, name=name, payload=value,
            input_sha256=book_adaptation._checkpoint_key(model="test", feature=feature, prompt=prompt))
    priced = []
    monkeypatch.setattr(book_adaptation, "estimate_text_cost",
                        lambda model, prompt, **kwargs: priced.append(prompt) or 1.0)
    book_adaptation.estimate_book_adaptation_cost(source, bible, brief, model="test", artifacts=target)
    assert lettering_prompt in priced
    assert blueprint_prompt not in priced
    calls = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(_lettering_response(adaptation.beats))

    result = asyncio.run(book_adaptation._generate_locked_lettering(
        prompt=lettering_prompt, blueprint=blueprint, known_speaker_ids={c.id for c in bible.characters},
        checkpoint_name="lettering/shard_001", model="test", artifacts=target, generate=generate,
        ctx=StageRuntime("adapt", PipelineState(project_name="cached-scope", novel_path="novel.txt",
                                               created_at=datetime.now(timezone.utc)), tmp_path),
    ))
    assert len(calls) == 1
    assert "source_999999" in calls[0]["user_content"]
    assert {u for beat in result.beats for item in beat.lettering for u in item.source_unit_ids} <= set(ids)
