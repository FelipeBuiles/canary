"""Sunburst Draw: OpenAI first, one FAL attempt, and who pays for a lost attempt."""
import asyncio
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.ai.errors import AIRefusalError, AITransportError
from novel_to_comic.config import Config
from novel_to_comic.models.draw import BookEdition, RetryProvenance
from novel_to_comic import image_route_fallback
from novel_to_comic.image_route_fallback import classify_openai_image_failure
from novel_to_comic.page_drawing import (
    OpenAICompletePageAdapter,
    SunburstFallbackPageAdapter,
    compile_page_generation_request,
    complete_page_adapter,
    current_page_capability_profile,
    ensure_current_page_edition,
    fal_sunburst_page_capability_profile,
    muse_page_capability_profile,
    select_book_edition,
    spendable_page_profiles,
    sunburst_fallback_page_capability_profile,
)
from novel_to_comic.server import credits
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import UsageRecord
from tests.test_complete_page_draw import _inventory, _page, _reference_files
from .page_draw_support import execute_draw

JOB = "ledger-job"
OPENAI = "image-sunburst-openai"
FAL = "image-sunburst"


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(credits, "_unsettled_jobs", set())
    image_route_fallback.OPENAI_SUNBURST_CIRCUIT.reset()
    yield
    image_route_fallback.OPENAI_SUNBURST_CIRCUIT.reset()


def _compiled(tmp_path, profile=None):
    profile = profile or sunburst_fallback_page_capability_profile()
    return compile_page_generation_request(
        _page(), select_book_edition(edition_id="test", profile=profile),
        _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )


def _png() -> bytes:
    image = io.BytesIO()
    Image.new("RGB", (1024, 1536)).save(image, format="PNG")
    return image.getvalue()


def _ok(model: str) -> httpx.Response:
    return httpx.Response(200, json={"model": model, "data": [{"b64_json": "x"}]},
                          request=httpx.Request("POST", "http://gateway/v1/images/edits"))


def _handler_failure(detail: str) -> httpx.Response:
    """What the proxy returns when a custom handler raises: a generic 500."""
    return httpx.Response(500, json={"error": {"message": f"Openai-streamException - {detail}"}},
                          request=httpx.Request("POST", "http://gateway/v1/images/edits"))


def _ambiguous(job_id=JOB):
    """Like _post_with_retry after a dispatched request lost its response."""
    def act():
        credits.retain_ambiguous_job(job_id)
        raise AITransportError("Page submission outcome is unknown", phase="ambiguous_submission")
    return act


def _marks_5xx(response):
    """Like the transport after an unknown gateway 5xx: retain the outcome."""
    def act():
        credits.retain_ambiguous_job(JOB)
        return response
    return act


def _run(adapter, compiled, outcomes):
    calls: list[dict] = []

    async def post(url, **kwargs):
        calls.append(kwargs)
        outcome = outcomes[len(calls) - 1]
        return outcome() if callable(outcome) else outcome

    async def run():
        with ai_request_context(job_id=JOB):
            return await adapter.generate(adapter.prepare(compiled))

    usage = UsageRecord(provider="litellm", model="m", operation="image", image_count=1,
                        cost_usd=0.05, cost_source="provider")
    with (
        patch("novel_to_comic.ai.client._post_with_retry", post),
        patch("novel_to_comic.ai.client._decode_image_response", AsyncMock(return_value=_png())),
        patch("novel_to_comic.ai.client._extract_usage", return_value=usage),
        patch("novel_to_comic.ai.client._finalize_event_shielded", AsyncMock()),
        patch("novel_to_comic.ai.finalisation.finalise_image_failure", AsyncMock()),
        patch("novel_to_comic.ai.finalisation.finalise_image_cancelled", AsyncMock()),
    ):
        try:
            return asyncio.run(run()), calls
        except BaseException as exc:
            exc.calls = calls  # type: ignore[attr-defined]
            raise


# Profile and edition binding -------------------------------------------------

def test_new_editions_get_openai_first_and_existing_fal_editions_keep_drawing():
    config = Config(draw_model="image-sunburst")
    fallback = sunburst_fallback_page_capability_profile()
    fal = fal_sunburst_page_capability_profile()
    assert current_page_capability_profile(config) == fallback
    assert spendable_page_profiles(config) == (fallback, fal)
    for profile in (fallback, fal):
        edition = BookEdition(revision=1, id="e", capability_profile=profile)
        assert ensure_current_page_edition(None, edition, config) is edition
    stranded = BookEdition(revision=1, id="e", capability_profile=muse_page_capability_profile())
    updated = ensure_current_page_edition(None, stranded, config, persist=False)
    assert updated.capability_profile == fallback
    assert updated.revision == 2


def test_lettering_variant_of_the_retained_edition_must_match_the_project():
    integrated = Config(draw_model="image-sunburst", lettering_mode="integrated")
    fal = fal_sunburst_page_capability_profile()
    kept = spendable_page_profiles(integrated)
    assert kept[0].exact_visible_lettering and kept[1].exact_visible_lettering
    assert kept[1].id == fal.id + "-integrated-v1"
    with pytest.raises(ValueError, match="different page profile"):
        ensure_current_page_edition(None, BookEdition(revision=1, id="e", capability_profile=fal), integrated)


def test_adapter_follows_the_frozen_request_not_mutable_settings(tmp_path):
    config = Config(draw_model="image-sunburst")
    fal_request = _compiled(tmp_path, fal_sunburst_page_capability_profile()).request
    assert isinstance(complete_page_adapter(config, request=fal_request), OpenAICompletePageAdapter)
    new_request = _compiled(tmp_path).request
    assert isinstance(complete_page_adapter(config, request=new_request), SunburstFallbackPageAdapter)
    foreign = new_request.model_copy(update={"profile_sha256": "0" * 64})
    with pytest.raises(ValueError, match="can no longer draw"):
        complete_page_adapter(config, request=foreign)


def test_fallback_pages_share_parallel_page_lanes():
    from types import SimpleNamespace
    from novel_to_comic.server.generation_jobs import is_parallel_page_draw

    job = SimpleNamespace(kind="complete_page_draw", status="queued", started_at=None, command=SimpleNamespace(
        operation="page_draw", arguments={"request": {"provider": "openai-fal"}}))
    assert is_parallel_page_draw(job)


# Coordinator -------------------------------------------------------------------

def test_openai_success_submits_once_to_the_openai_route(tmp_path):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    result, calls = _run(adapter, _compiled(tmp_path), [_ok("openai/gpt-image-2.5-sunburst")])
    assert len(calls) == 1
    data = calls[0]["data"]
    assert data["model"] == OPENAI
    assert json.loads(data["canary_wire_request"]) == {
        "width": 1024, "height": 1536,
        "controls": [["quality", "medium"], ["output_format", "png"], ["n", 1]],
    }
    assert calls[0]["retry_ambiguous"] is False
    assert result.response_metadata == {"route": "openai"}
    assert result.usage.provider == "openai"
    assert result.actual_provider_model == "openai/gpt-image-2.5-sunburst"


@pytest.mark.parametrize("detail,reason", [
    ("OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=429; detail=code=rate_limit", "capacity"),
    ("OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=401", "credentials"),
    ("OpenAI image submit_connect failed for gpt-image-2.5-sunburst; detail=ConnectError", "not_submitted"),
])
def test_rejection_before_acceptance_falls_back_without_absorbing(tmp_path, detail, reason):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    result, calls = _run(adapter, _compiled(tmp_path), [
        _marks_5xx(_handler_failure(detail)), _ok("fal-queue/openai/gpt-image-2.5/sunburst"),
    ])
    assert [call["data"]["model"] for call in calls] == [OPENAI, FAL]
    assert result.response_metadata == {"route": "fal-queue", "fallback": {"from_route": "openai", "reason": reason}}
    assert result.usage.provider == "fal-queue"
    assert JOB not in credits._unsettled_jobs


@pytest.mark.parametrize("failure", [
    _ambiguous(),
    _marks_5xx(_handler_failure("OpenAI image stream failed for gpt-image-2.5-sunburst; request_id=req_1")),
    _marks_5xx(_handler_failure("OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=502")),
    _marks_5xx(_handler_failure("unrecognised gateway failure")),
])
def test_unknown_openai_outcome_is_absorbed_and_drawn_on_fal(tmp_path, failure):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    with patch("novel_to_comic.image_route_fallback.increment_metric") as metric:
        result, calls = _run(adapter, _compiled(tmp_path), [failure, _ok("fal-queue/openai/gpt-image-2.5/sunburst")])
    assert [call["data"]["model"] for call in calls] == [OPENAI, FAL]
    fallback = result.response_metadata["fallback"]
    assert fallback["reason"] == "unknown_outcome"
    assert len(fallback["absorbed_call_ids"]) == 1
    assert 0 < fallback["absorbed_estimated_cost_usd"] < 0.25
    # Canary absorbs it: the user's hold is not retained for the lost attempt.
    assert JOB not in credits._unsettled_jobs
    metric.assert_any_call("canary_absorbed_image_attempts_total", route="openai", surface="draw")


@pytest.mark.parametrize("failure,held", [
    (_handler_failure(
        "OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=400; detail=code=moderation_blocked"), False),
    (_handler_failure(
        "OpenAI image stream failed for gpt-image-2.5-sunburst; request_id=req_1; detail=code=moderation_blocked"), False),
    (_marks_5xx(_handler_failure("OpenAI image request_validation failed for gpt-image-2.5-sunburst")), True),
])
def test_request_faults_stop_without_trying_fal(tmp_path, failure, held):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    with pytest.raises(AITransportError) as caught:
        _run(adapter, _compiled(tmp_path), [failure])
    assert len(caught.value.calls) == 1
    # Safety refusals are terminal; an unclassified 5xx still needs reconciliation.
    assert (JOB in credits._unsettled_jobs) is held


def test_refusal_and_invalid_output_stop_without_trying_fal(tmp_path):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    wrong = httpx.Response(200, json={"model": "openai/gpt-image-2.5-flare", "data": [{"b64_json": "x"}]},
                           request=httpx.Request("POST", "http://gateway"))
    with pytest.raises(ValueError, match="does not match"):
        _run(adapter, _compiled(tmp_path), [wrong])
    assert classify_openai_image_failure(AIRefusalError("refused")) is None


def test_cancellation_stops_and_keeps_the_hold(tmp_path):
    def cancelled():
        credits.retain_ambiguous_job(JOB)
        raise asyncio.CancelledError()

    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    with pytest.raises(asyncio.CancelledError):
        _run(adapter, _compiled(tmp_path), [cancelled])
    assert JOB in credits._unsettled_jobs


def test_an_unknown_fal_backup_attempt_is_retained_as_today(tmp_path):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    with pytest.raises(AITransportError):
        _run(adapter, _compiled(tmp_path), [_ambiguous(), _ambiguous()])
    assert JOB in credits._unsettled_jobs


def test_repeated_openai_failures_open_the_circuit_to_fal(tmp_path):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    for _ in range(3):
        _run(adapter, _compiled(tmp_path), [_ambiguous(), _ok("fal-queue/openai/gpt-image-2.5/sunburst")])
    result, calls = _run(adapter, _compiled(tmp_path), [_ok("fal-queue/openai/gpt-image-2.5/sunburst")])
    assert [call["data"]["model"] for call in calls] == [FAL]
    assert result.response_metadata["fallback"] == {"from_route": "openai", "reason": "circuit_open"}


def test_a_success_resets_the_failure_count(tmp_path):
    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    fal = _ok("fal-queue/openai/gpt-image-2.5/sunburst")
    for outcomes in ([_ambiguous(), fal], [_ambiguous(), fal], [_ok("openai/gpt-image-2.5-sunburst")],
                     [_ambiguous(), fal]):
        _run(adapter, _compiled(tmp_path), outcomes)
    assert not image_route_fallback.OPENAI_SUNBURST_CIRCUIT.is_open()


def test_fallback_provenance_persists_the_absorbed_attempt(tmp_path):

    adapter = complete_page_adapter(Config(draw_model="image-sunburst"))
    compiled = _compiled(tmp_path)
    artifacts = TargetArtifacts(tmp_path / "project")

    async def post(url, **kwargs):
        post.calls += 1
        if post.calls == 1:
            _ambiguous()()
        return _ok("fal-queue/openai/gpt-image-2.5/sunburst")
    post.calls = 0

    async def run():
        with ai_request_context(job_id=JOB):
            return await execute_draw(compiled, adapter=adapter, artifacts=artifacts, page=_page())

    usage = UsageRecord(provider="litellm", model="m", operation="image", image_count=1,
                        cost_usd=0.05, cost_source="provider")
    with (
        patch("novel_to_comic.ai.client._post_with_retry", post),
        patch("novel_to_comic.ai.client._decode_image_response", AsyncMock(return_value=_png())),
        patch("novel_to_comic.ai.client._extract_usage", return_value=usage),
        patch("novel_to_comic.ai.client._finalize_event_shielded", AsyncMock()),
        patch("novel_to_comic.ai.finalisation.finalise_image_failure", AsyncMock()),
    ):
        provenance = asyncio.run(run())
    saved = artifacts.read_provenance(7, provenance.render.revision)
    assert saved.response_metadata["route"] == "fal-queue"
    assert saved.response_metadata["fallback"]["reason"] == "unknown_outcome"
    assert saved.render.provider == "openai-fal"
    assert saved.usage.provider == "fal-queue"


# Classification ----------------------------------------------------------------

@pytest.mark.parametrize("exc,reason", [
    (httpx.ConnectError("down"), "gateway_unreachable"),
    (AITransportError("x", phase="ambiguous_submission"), "unknown_outcome"),
    (AITransportError("x", phase="response_json"), None),
    (ValueError("dimensions"), None),
    (RuntimeError("anything else"), None),
])
def test_classification_of_non_gateway_failures(exc, reason):
    assert classify_openai_image_failure(exc) == reason


# Credits scope -----------------------------------------------------------------

def test_deferred_ambiguity_holds_markers_until_the_coordinator_decides():
    with credits.deferred_ambiguity() as scope:
        credits.retain_ambiguous_job("job-a")
        assert credits.is_ambiguous_job("job-a")
        assert "job-a" not in credits._unsettled_jobs
        scope.commit()
    assert "job-a" in credits._unsettled_jobs


def test_an_unresolved_scope_commits_so_no_hold_is_lost():
    with credits.deferred_ambiguity():
        credits.retain_ambiguous_job("job-b")
    assert "job-b" in credits._unsettled_jobs


def test_releasing_a_scope_frees_its_call_guarantees_and_markers():
    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = True
    with credits.deferred_ambiguity() as scope:
        credits.authorize_model_call(db, user_id="user", job_id="job-c", call_id="call-1", estimated_cost_usd=0.05)
        credits.retain_ambiguous_job("job-c")
        scope.release(db, user_id="user")
    assert "job-c" not in credits._unsettled_jobs
    db.rpc.assert_any_call("release_model_call_authorization", {"p_user_id": "user", "p_usage_call_id": "call-1"})
