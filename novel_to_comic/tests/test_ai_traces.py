"""AI Observability tree, timing, outcomes and the dev-only content gate."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_to_comic.ai.context import (
    ai_request_context,
    generation_probe,
    mark_generation_executing,
    mark_generation_first_content,
)
from novel_to_comic.clients.structured_call import StructuredCallError, generate_validated_json
from novel_to_comic.server import telemetry as t
from novel_to_comic.server.page_outcomes import record_page_outcome
from novel_to_comic.server.product_events import SERVER_EVENT_PROPERTIES, _clean_properties
from novel_to_comic.usage import ApiResult, UsageRecord

USER = "b039877c-3d9b-46ec-988f-183972a14945"
PROJECT = "7c1e5f0a-2a51-4c55-9a43-5cbb3f4f3c11"
OPERATION = "0d4f3c1e-8a6b-4f0e-9c2d-1b7a5e3f9d20"


@pytest.fixture
def sdk(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(t, "_client", client)
    monkeypatch.setattr(t, "_provider", None)
    monkeypatch.delenv("CANARY_AI_CONTENT_CAPTURE", raising=False)
    monkeypatch.setenv("CANARY_ENV", "development")
    return client


def events(sdk, name=None):
    found = [(call.args[0], call.kwargs["properties"]) for call in sdk.capture.call_args_list]
    return [props for event, props in found if event == name] if name else found


def generation(event_id, **kwargs):
    usage = UsageRecord(provider="litellm", model="text-pro", operation="text",
                        input_tokens=100, output_tokens=40)
    t.observe_generation(event_id=event_id, feature="plan.page", operation="text",
                         model_alias="text-pro", provider_model="provider-text", status="succeeded",
                         usage=usage, cost_usd=0.01, cost_source="provider_reported",
                         latency_ms=2000, **kwargs)


def test_job_stage_and_generation_form_one_navigable_tree(sdk):
    with ai_request_context(user_id=USER, project_id=PROJECT), t.observation_context(operation_id=OPERATION):
        with t.ai_span("job.pipeline") as job:
            with t.ai_span("stage.plan", stage="plan") as stage:
                generation("call-1", reasoning_tokens=12)
            job.set(status="complete")
    [trace] = events(sdk, "$ai_trace")
    [span] = events(sdk, "$ai_span")
    [call] = events(sdk, "$ai_generation")
    assert trace["$ai_trace_id"] == OPERATION and trace["$ai_trace_name"] == "job.pipeline"
    assert trace["$ai_is_error"] is False
    assert span["$ai_parent_id"] == OPERATION and span["$ai_span_name"] == "stage.plan"
    assert call["$ai_trace_id"] == OPERATION and call["$ai_parent_id"] == stage.span_id
    assert call["$ai_reasoning_tokens"] == 12 and call["$ai_output_tokens"] == 40
    assert {trace["$ai_session_id"], span["$ai_session_id"], call["$ai_session_id"]} == {PROJECT}
    assert job.span_id == OPERATION


def test_spans_without_ai_work_are_never_exported(sdk):
    with t.ai_span("job.export"):
        with t.ai_span("stage.finish"):
            pass
    assert events(sdk) == []


def test_failed_span_is_an_error_without_exception_text(sdk):
    with pytest.raises(ValueError):
        with t.ai_span("job.draw"):
            generation("call-1")
            raise ValueError("private prose")
    [trace] = events(sdk, "$ai_trace")
    assert trace["$ai_is_error"] is True and trace["error_type"] == "ValueError"
    assert "private prose" not in repr(sdk.capture.call_args_list)


def test_concurrent_pages_keep_their_own_parents(sdk):
    async def page(number):
        with t.ai_span("page", page_number=number) as span:
            await asyncio.sleep(0)
            await asyncio.to_thread(generation, f"call-{number}")
            return span.span_id

    async def run():
        with t.ai_span("stage.draw"):
            return await asyncio.gather(page(1), page(2))

    parents = asyncio.run(run())
    calls = {props["$ai_span_id"]: props["$ai_parent_id"] for props in events(sdk, "$ai_generation")}
    assert calls == {"call-1": parents[0], "call-2": parents[1]}


def test_probe_splits_admission_execution_and_first_content(sdk, monkeypatch):
    clock = iter([10.0, 12.5, 13.0])
    monkeypatch.setattr("novel_to_comic.ai.context.time.perf_counter", lambda: next(clock))
    with generation_probe() as probe:
        probe.describe(system_prompt="Plan the page.", user_content="private", json_schema={"type": "object"},
                       stream=True, keep_content=False)
        mark_generation_executing()
        mark_generation_first_content()
        generation("call-1")
    [call] = events(sdk, "$ai_generation")
    assert call["admission_ms"] == 2500 and call["execution_ms"] == 0
    assert call["$ai_time_to_first_token"] == 0.5 and call["$ai_stream"] is True
    assert len(call["prompt_sha"]) == 16 and len(call["schema_sha"]) == 16
    assert "$ai_input" not in call and "private" not in repr(call)


def test_unobserved_phases_stay_missing(sdk):
    with generation_probe():
        generation("call-1")
    [call] = events(sdk, "$ai_generation")
    assert not {"admission_ms", "execution_ms", "$ai_time_to_first_token"} & set(call)


def _probe_with_content():
    probe = generation_probe()
    entered = probe.__enter__()
    entered.describe(system_prompt="System.", user_content="Fixture text.", json_schema=None,
                     stream=False, keep_content=True)
    entered.output_text = "Model answer."
    return probe


@pytest.mark.parametrize("env,flag,expected", [
    ("development", None, True),
    ("development", "true", True),
    ("development", "false", False),
    ("production", None, False),
    ("production", "true", False),
])
def test_content_reaches_posthog_only_from_local_development(sdk, monkeypatch, env, flag, expected):
    monkeypatch.setenv("CANARY_ENV", env)
    if flag is not None:
        monkeypatch.setenv("CANARY_AI_CONTENT_CAPTURE", flag)
    probe = _probe_with_content()
    try:
        with ai_request_context(project_id=PROJECT), t.ai_span("stage.plan"):
            generation("call-1")
    finally:
        probe.__exit__(None, None, None)
    [call] = events(sdk, "$ai_generation")
    assert ("$ai_input" in call) is expected
    if expected:
        assert call["$ai_input"][1] == {"role": "user", "content": "Fixture text."}
        assert call["$ai_output_choices"] == [{"role": "assistant", "content": "Model answer."}]
        assert t._before_send({"event": "$ai_generation", "properties": call})["properties"]["$ai_input"]
    else:
        assert "Fixture text." not in repr(sdk.capture.call_args_list)


def test_scrubber_strips_content_outside_development(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    clean = t._before_send({"event": "$ai_generation", "properties": {
        "$ai_input": [{"role": "user", "content": "secret"}]}})
    assert "secret" not in repr(clean)


def test_scrubber_never_admits_content_on_other_events(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.setenv("CANARY_AI_CONTENT_CAPTURE", "true")
    clean = t._before_send({"event": "$ai_span", "properties": {
        "experiment_id": "exp-1", "$ai_input": [{"role": "user", "content": "secret"}]}})
    assert "secret" not in repr(clean)


def _structured(responses, **kwargs):
    replies = iter(responses)

    async def fake_generate(**_):
        value = next(replies)
        generation(f"call-{value['n']}")
        return ApiResult(value=value, usage=UsageRecord(provider="litellm", model="text-pro", operation="text"))

    def parse(value):
        if not value["ok"]:
            raise ValueError("bad shape")
        return value

    return asyncio.run(generate_validated_json(
        None, model="text-pro", system_prompt="s", user_content="u", parse=parse,
        correction=lambda _value, _error: "fix", label="Plan", feature="plan.page",
        generate=fake_generate, **kwargs))


def test_validation_rejection_is_distinct_from_provider_success(sdk):
    outcome = _structured([{"n": 1, "ok": False}, {"n": 2, "ok": True}])
    assert outcome.attempts == 2
    spans = {(props["$ai_span_name"], props.get("attempt_number")): props for props in events(sdk, "$ai_span")}
    assert spans[("attempt", 1)]["outcome"] == "rejected"
    assert spans[("attempt", 1)]["error_type"] == "ValueError"
    assert spans[("attempt", 2)]["outcome"] == "accepted"
    [call_span] = events(sdk, "$ai_trace")
    assert call_span["outcome"] == "accepted_after_retry" and call_span["attempts"] == 2
    calls = {props["$ai_span_id"]: props for props in events(sdk, "$ai_generation")}
    assert calls["call-1"]["attempt_number"] == 1 and calls["call-1"]["$ai_is_error"] is False
    assert calls["call-1"]["$ai_parent_id"] == spans[("attempt", 1)]["$ai_span_id"]


def test_local_repair_and_exhaustion_outcomes(sdk):
    with pytest.raises(StructuredCallError):
        _structured([{"n": 1, "ok": False}], retries=0)
    [trace] = events(sdk, "$ai_trace")
    assert trace["outcome"] == "failed" and trace["$ai_is_error"] is True
    sdk.reset_mock()
    _structured([{"n": 1, "ok": True}], validate=lambda value: None if value.get("repaired") else 1 / 0,
                repair=lambda value, _error: value | {"repaired": True})
    assert events(sdk, "$ai_trace")[0]["outcome"] == "repaired"


def test_author_verdict_links_to_the_render_trace(monkeypatch, sdk):
    captured = []
    monkeypatch.setattr("novel_to_comic.server.lifecycle_events.capture",
                        lambda app, name, identity, **kwargs: captured.append((name, identity, kwargs)))
    provenance = SimpleNamespace(usage=SimpleNamespace(call_id="call-7"), ai_trace_id=OPERATION)
    target = SimpleNamespace(active_render_revision=lambda _page: 3,
                             read_provenance=lambda page, revision: provenance)
    record_page_outcome(None, "redraw_requested", user_id=USER, project_id=PROJECT, target=target,
                        page_number=2, identity="job-1", mode="canonical")
    [(name, identity, kwargs)] = captured
    assert name == "page_outcome" and identity == f"redraw_requested:{PROJECT}:job-1"
    assert kwargs["properties"] == {"outcome": "redraw_requested", "page_number": 2, "render_revision": 3,
                                    "generation_id": "call-7", "mode": "canonical"}
    _clean_properties("page_outcome", kwargs["properties"], source="server")
    [metric] = events(sdk, "$ai_metric")
    assert metric["$ai_trace_id"] == OPERATION and metric["$ai_parent_id"] == "call-7"
    assert metric["$ai_metric_name"] == "author_redraw_requested" and metric["$ai_metric_value"] == 1


def test_lettering_verdicts_never_score_the_art_and_failures_are_silent(monkeypatch, sdk):
    monkeypatch.setattr("novel_to_comic.server.lifecycle_events.capture", lambda *a, **k: None)
    provenance = SimpleNamespace(usage=SimpleNamespace(call_id="call-7"), ai_trace_id=OPERATION)
    target = SimpleNamespace(active_render_revision=lambda _page: 1,
                             read_provenance=lambda page, revision: provenance)
    record_page_outcome(None, "lettering_saved", user_id=USER, project_id=PROJECT, target=target,
                        page_number=1, mode="reviewed")
    assert events(sdk, "$ai_metric") == []
    broken = SimpleNamespace(active_render_revision=MagicMock(side_effect=OSError("disk")))
    record_page_outcome(None, "render_selected", user_id=USER, project_id=PROJECT, target=broken, page_number=1)
    with pytest.raises(ValueError):
        record_page_outcome(None, "panel_flagged", user_id=USER, project_id=PROJECT, target=target, page_number=1)


def test_retired_panel_events_are_rejected():
    assert "panel_flagged" not in SERVER_EVENT_PROPERTIES
    assert "panel_regenerated" not in SERVER_EVENT_PROPERTIES


def test_labs_fixture_ids_are_opaque_and_stable():
    from novel_to_comic.labs.storage import fixture_id

    assert fixture_id("projects/my-novel") == fixture_id("projects/my-novel")
    assert "novel" not in fixture_id("projects/my-novel")
