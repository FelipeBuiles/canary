"""Sunburst while the Runware grant lasts: Runware first, then OpenAI → FAL.

Runware moves on only when its attempt definitely did not run; an unknown
outcome stops and keeps the hold, never resubmitting elsewhere.
"""
from unittest.mock import patch

import pytest

from novel_to_comic import image_route_fallback
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.config import Config
from novel_to_comic.image_models import image_model_profile
from novel_to_comic.image_route_fallback import classify_runware_image_failure
from novel_to_comic.model_catalog import models
from novel_to_comic.models.draw import BookEdition
from novel_to_comic.page_drawing import (
    RunwareFirstPageAdapter,
    SunburstFallbackPageAdapter,
    complete_page_adapter,
    current_page_capability_profile,
    ensure_current_page_edition,
    page_image_quality,
    runware_first_page_capability_profile,
    spendable_page_profiles,
    sunburst_fallback_page_capability_profile,
)
from novel_to_comic.server import credits
from tests import test_asset_route_fallback as asset
from tests.test_page_fallback import JOB, _ambiguous, _compiled, _handler_failure, _marks_5xx, _ok, _run

RUNWARE = "image-sunburst-runware"
OPENAI = "image-sunburst-openai"
FAL = "image-sunburst"
RUNWARE_OK = "runware/gpt-image-2.5-sunburst"
OPENAI_OK = "openai/gpt-image-2.5-sunburst"


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(credits, "_unsettled_jobs", set())
    for circuit in (image_route_fallback.OPENAI_SUNBURST_CIRCUIT, image_route_fallback.RUNWARE_CIRCUIT):
        circuit.reset()
    yield
    for circuit in (image_route_fallback.OPENAI_SUNBURST_CIRCUIT, image_route_fallback.RUNWARE_CIRCUIT):
        circuit.reset()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("CANARY_RUNWARE_FIRST_ENABLED", "true")


def _runware_failure(detail: str):
    return _marks_5xx(_handler_failure(f"Runware image {detail}"))


def _adapter():
    return complete_page_adapter(Config(draw_model="image-sunburst"), runware_first_page_capability_profile())


def _models(calls):
    return [call["data"]["model"] for call in calls]


# Identity ------------------------------------------------------------------------

def test_the_switch_is_off_by_default():
    assert image_model_profile("image-sunburst").provider_key == "openai-fal"
    assert current_page_capability_profile(Config(draw_model="image-sunburst")) == sunburst_fallback_page_capability_profile()


def test_new_sunburst_work_starts_on_runware_when_enabled(enabled):
    config = Config(draw_model="image-sunburst")
    profile = runware_first_page_capability_profile()
    assert current_page_capability_profile(config) == profile
    assert isinstance(complete_page_adapter(config), RunwareFirstPageAdapter)
    assert page_image_quality(profile.id, profile.provider) == "medium"
    assert (profile.provider, profile.model, profile.max_attempts) == ("runware-openai-fal", "gpt-image-2.5-sunburst", 3)
    asset_profile = image_model_profile("image-sunburst")
    assert (asset_profile.provider_key, asset_profile.max_references) == ("runware-openai-fal", 16)
    picker = {m["id"]: m["provider"] for m in models(include_codex=False) if m["kind"] == "image"}
    assert picker["image-sunburst"] == "Runware, OpenAI and FAL backup"
    integrated = current_page_capability_profile(config.model_copy(update={"lettering_mode": "integrated"}))
    assert integrated.id == profile.id + "-integrated-v1" and integrated.exact_visible_lettering


def test_frozen_requests_keep_their_route_whatever_the_switch(tmp_path, monkeypatch):
    config = Config(draw_model="image-sunburst")
    runware_request = _compiled(tmp_path, runware_first_page_capability_profile()).request
    openai_request = _compiled(tmp_path).request
    assert isinstance(complete_page_adapter(config, request=runware_request), RunwareFirstPageAdapter)
    monkeypatch.setenv("CANARY_RUNWARE_FIRST_ENABLED", "true")
    adapter = complete_page_adapter(config, request=openai_request)
    assert isinstance(adapter, SunburstFallbackPageAdapter) and not isinstance(adapter, RunwareFirstPageAdapter)


def test_existing_editions_keep_their_route_whichever_way_the_switch_is_set(monkeypatch):
    config = Config(draw_model="image-sunburst")
    openai_first = BookEdition(revision=1, id="e", capability_profile=sunburst_fallback_page_capability_profile())
    runware_first = BookEdition(revision=1, id="e", capability_profile=runware_first_page_capability_profile())
    for enabled in ("true", ""):
        monkeypatch.setenv("CANARY_RUNWARE_FIRST_ENABLED", enabled)
        for edition in (openai_first, runware_first):
            assert ensure_current_page_edition(None, edition, config) is edition
    integrated = Config(draw_model="image-sunburst", lettering_mode="integrated")
    assert all(profile.exact_visible_lettering for profile in spendable_page_profiles(integrated))
    assert len({profile.id for profile in spendable_page_profiles(integrated)}) == 3


# Draw coordinator ------------------------------------------------------------

def test_runware_success_submits_once_with_the_frozen_manifest(tmp_path):
    result, calls = _run(_adapter(), _compiled(tmp_path, runware_first_page_capability_profile()), [_ok(RUNWARE_OK)])
    assert _models(calls) == [RUNWARE] and calls[0]["retry_ambiguous"] is False
    assert calls[0]["data"]["canary_wire_request"] == (
        '{"width": 1024, "height": 1536, "controls": [["quality", "medium"], ["output_format", "png"], ["n", 1]]}'
    )
    assert result.response_metadata == {"route": "runware"}
    assert (result.usage.provider, result.actual_provider_model) == ("runware", RUNWARE_OK)


@pytest.mark.parametrize("detail,reason", [
    ("submit failed for gpt-image-2.5-sunburst; upstream_status=402; code=insufficientCredits", "credits"),
    ("submit failed for gpt-image-2.5-sunburst; upstream_status=401; code=invalidApiKey", "credentials"),
    ("submit failed for gpt-image-2.5-sunburst; upstream_status=429; code=inferenceRateLimitExceeded", "capacity"),
    ("submit failed for gpt-image-2.5-sunburst; upstream_status=503; code=serviceOverloaded", "capacity"),
    ("submit failed for gpt-image-2.5-sunburst; upstream_status=500; code=timeoutProvider", "provider_error"),
    ("submit failed for gpt-image-2.5-sunburst; code=providerError; task_uuid=t", "provider_error"),
    ("upload failed for gpt-image-2.5-sunburst; upstream_status=500", "not_submitted"),
    ("submit_connect failed for gpt-image-2.5-sunburst; task_uuid=t; detail=ConnectError", "not_submitted"),
])
def test_a_definite_runware_failure_moves_on_to_openai_without_holding(tmp_path, detail, reason):
    result, calls = _run(_adapter(), _compiled(tmp_path, runware_first_page_capability_profile()), [
        _runware_failure(detail), _ok(OPENAI_OK),
    ])
    assert _models(calls) == [RUNWARE, OPENAI]
    assert result.response_metadata == {"route": "openai", "fallback": {"from_route": "runware", "reason": reason}}
    assert result.usage.provider == "openai"
    assert JOB not in credits._unsettled_jobs


def test_the_openai_chain_runs_unchanged_after_runware(tmp_path):
    result, calls = _run(_adapter(), _compiled(tmp_path, runware_first_page_capability_profile()), [
        _runware_failure("submit failed for gpt-image-2.5-sunburst; upstream_status=402; code=insufficientCredits"),
        _marks_5xx(_handler_failure(
            "OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=429; detail=code=rate_limit")),
        _ok("fal-queue/openai/gpt-image-2.5/sunburst"),
    ])
    assert _models(calls) == [RUNWARE, OPENAI, FAL]
    assert result.response_metadata == {"route": "fal-queue", "fallback": {
        "from_route": "runware", "reason": "credits",
        "then": {"from_route": "openai", "reason": "capacity"},
    }}
    assert JOB not in credits._unsettled_jobs


@pytest.mark.parametrize("failure,held", [
    (_runware_failure("unknown_outcome failed for gpt-image-2.5-sunburst; task_uuid=t; detail=task not found"), True),
    (_runware_failure("result failed for gpt-image-2.5-sunburst; task_uuid=t"), True),
    (_runware_failure("request_validation failed for gpt-image-2.5-sunburst; detail=invalid size 1000x1500"), True),
    (_handler_failure("Runware image submit failed for gpt-image-2.5-sunburst; upstream_status=400; code=invalidPrompt"),
     False),
    (_marks_5xx(_handler_failure("unrecognised gateway failure")), True),
    (_ambiguous(), True),
])
def test_an_unknown_outcome_or_request_fault_stops_on_runware(tmp_path, failure, held):
    with pytest.raises(AITransportError) as caught:
        _run(_adapter(), _compiled(tmp_path, runware_first_page_capability_profile()), [failure])
    assert _models(caught.value.calls) == [RUNWARE]
    assert (JOB in credits._unsettled_jobs) is held
    assert not image_route_fallback.RUNWARE_CIRCUIT.is_open()


def test_a_spent_grant_opens_the_circuit_straight_to_openai(tmp_path):
    spent = "submit failed for gpt-image-2.5-sunburst; upstream_status=402; code=insufficientCredits"
    compiled = _compiled(tmp_path, runware_first_page_capability_profile())
    for _ in range(3):
        _run(_adapter(), compiled, [_runware_failure(spent), _ok(OPENAI_OK)])
    assert image_route_fallback.RUNWARE_CIRCUIT.is_open()
    result, calls = _run(_adapter(), compiled, [_ok(OPENAI_OK)])
    assert _models(calls) == [OPENAI]
    assert result.response_metadata["fallback"] == {"from_route": "runware", "reason": "circuit_open"}


def test_a_different_upstream_model_is_rejected_not_retried(tmp_path):
    with pytest.raises(ValueError, match="Runware response model"):
        _run(_adapter(), _compiled(tmp_path, runware_first_page_capability_profile()),
             [_ok("runware/gpt-image-2.5-flare")])


def test_non_gateway_failures_stop():
    assert classify_runware_image_failure(ValueError("bad png")) is None
    assert classify_runware_image_failure(AITransportError("lost", phase="ambiguous_submission")) is None


# Style & Cast ------------------------------------------------------------------

def test_style_and_cast_images_start_on_runware(tmp_path):
    wire = asset._wire(provider_key="runware-openai-fal")
    result, calls, db, _ = asset._run(tmp_path, wire, [asset._ok(RUNWARE_OK)])
    assert asset._models(calls) == [RUNWARE]
    assert result.response_metadata == {"route": "runware"}
    assert asset._released(db) == []


def test_a_spent_grant_draws_style_and_cast_on_openai_and_frees_the_runware_guarantee(tmp_path):
    wire = asset._wire(provider_key="runware-openai-fal")
    spent = asset._handler_failure(
        "Runware image submit failed for gpt-image-2.5-sunburst; upstream_status=402; code=insufficientCredits")
    with patch.object(image_route_fallback, "increment_metric"):
        result, calls, db, _ = asset._run(tmp_path, wire, [spent, asset._ok(OPENAI_OK)])
    assert asset._models(calls) == [RUNWARE, OPENAI]
    assert result.response_metadata == {"route": "openai", "fallback": {"from_route": "runware", "reason": "credits"}}
    assert asset._released(db) == ["call-1"]
    assert JOB not in credits._unsettled_jobs
