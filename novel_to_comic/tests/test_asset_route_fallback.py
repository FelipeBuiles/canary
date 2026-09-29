"""Sunburst Style & Cast images: OpenAI first, one FAL attempt, through the real wire transport."""
import asyncio
import itertools
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from novel_to_comic import image_route_fallback
from novel_to_comic.ai import client
from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.ai.providers import litellm_http
from novel_to_comic.config import Config
from novel_to_comic.image_models import image_model_profile
from novel_to_comic.image_route_fallback import classify_openai_image_failure
from novel_to_comic.model_catalog import models
from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_DISCRIMINATOR,
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireRequest,
)
from novel_to_comic.server import credits
from novel_to_comic.usage import ApiResult, UsageRecord

JOB = "asset-job"
USER = "user-1"
OPENAI = "image-sunburst-openai"
FAL = "image-sunburst"


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(credits, "_unsettled_jobs", set())
    image_route_fallback.OPENAI_SUNBURST_CIRCUIT.reset()
    yield
    image_route_fallback.OPENAI_SUNBURST_CIRCUIT.reset()


def _wire(provider_key: str = "openai-fal", alias: str = "image-sunburst") -> ProviderWireRequest:
    wire = ProviderWireRequest(
        discriminator=PROVIDER_WIRE_DISCRIMINATOR, schema_version=PROVIDER_WIRE_SCHEMA_VERSION,
        requested_alias=alias, expected_route="gpt_image_2", provider_key=provider_key,
        configured_provider_model="gpt-image-2.5-sunburst", prompt_parts=("A lighthouse at dusk",),
        references=(), width=1024, height=1280, structured_aspect=None,
        controls=(("quality", "medium"),), compiled_request_sha256="c" * 64, execution_fingerprint="",
    )
    return replace(wire, execution_fingerprint=wire.recompute_execution_fingerprint())


def _ok(model: str) -> httpx.Response:
    return httpx.Response(200, json={"model": model, "data": [{"b64_json": "x"}]},
                          request=httpx.Request("POST", "http://gateway/v1/images/generations"))


def _handler_failure(detail: str) -> httpx.Response:
    """What the proxy returns when a custom handler raises: a generic 500."""
    return httpx.Response(500, json={"error": {"message": f"Openai-streamException - {detail}"}},
                          request=httpx.Request("POST", "http://gateway/v1/images/generations"))


def _run(tmp_path, wire, outcomes):
    """Drive generate_wire_image through the real _post_with_retry and LiteLLM transport."""
    calls: list[dict] = []
    ids = itertools.count(1)

    class FakeHttp:
        async def post(self, url, **kwargs):
            calls.append(kwargs)
            outcome = outcomes[len(calls) - 1]
            return outcome() if callable(outcome) else outcome

    async def begin(**kwargs):
        return SimpleNamespace(event_id=f"call-{next(ids)}", estimated_cost_usd=0.05,
                               metadata={"funding": "api"}, started=0.0)

    async def success(*, ctx, model, raw, output_path, **_):
        return ApiResult(value=output_path, actual_provider_model=raw.actual_provider_model,
                         usage=UsageRecord(provider="litellm", model=model, operation="image", image_count=1))

    db = MagicMock()
    db.rpc.return_value.execute.return_value.data = True

    async def run():
        with ai_request_context(user_id=USER, job_id=JOB):
            return await client.generate_wire_image(config=Config(), wire=wire, output_path=tmp_path / "out.png")

    with (
        patch.object(client, "_http", FakeHttp()),
        patch.object(client, "begin_image_call", begin),
        patch.object(client, "finalise_image_success", success),
        patch.object(client, "finalise_image_failure", AsyncMock()),
        patch.object(client, "_decode_image_response", AsyncMock(return_value=b"png")),
        patch("novel_to_comic.server.db.get_db", return_value=db),
        patch.object(image_route_fallback, "increment_metric") as metric,
    ):
        try:
            result = asyncio.run(run())
        except BaseException as exc:
            exc.calls, exc.db = calls, db  # type: ignore[attr-defined]
            raise
    return result, calls, db, metric


def _models(calls):
    return [call["json"]["model"] for call in calls]


def _released(db):
    return [c.args[1]["p_usage_call_id"] for c in db.rpc.call_args_list
            if c.args[0] == "release_model_call_authorization"]


# Identity ------------------------------------------------------------------------

def test_image_sunburst_is_openai_first_with_the_documented_reference_cap():
    profile = image_model_profile("image-sunburst")
    assert (profile.provider_key, profile.max_references) == ("openai-fal", 16)
    # Retained FAL literals and frozen FAL wires keep their route.
    assert image_model_profile("fal-queue/openai/gpt-image-2.5/sunburst").provider_key == "fal-queue"
    picker = {m["id"]: m["provider"] for m in models(include_codex=False) if m["kind"] == "image"}
    assert picker["image-sunburst"] == "OpenAI, FAL backup"


# Coordinator ---------------------------------------------------------------------

def test_openai_success_submits_once_with_the_frozen_manifest(tmp_path):
    wire = _wire()
    result, calls, db, _ = _run(tmp_path, wire, [_ok("openai/gpt-image-2.5-sunburst")])
    assert _models(calls) == [OPENAI]
    manifest = json.loads(calls[0]["json"]["canary_wire_request"])
    # Only the gateway deployment differs from the frozen request.
    assert manifest["requested_alias"] == OPENAI
    assert {k: v for k, v in manifest.items() if k not in {"requested_alias", "execution_fingerprint"}} == {
        k: v for k, v in json.loads(wire.to_json()).items() if k not in {"requested_alias", "execution_fingerprint"}
    }
    assert result.response_metadata == {"route": "openai"}
    assert _released(db) == []


@pytest.mark.parametrize("detail,reason", [
    ("OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=429; detail=code=rate_limit", "capacity"),
    ("OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=401", "credentials"),
    ("OpenAI image submit_connect failed for gpt-image-2.5-sunburst; detail=ConnectError", "not_submitted"),
])
def test_rejection_before_acceptance_falls_back_without_absorbing(tmp_path, detail, reason):
    result, calls, db, _ = _run(tmp_path, _wire(), [_handler_failure(detail), _ok("fal-queue/openai/gpt-image-2.5/sunburst")])
    assert _models(calls) == [OPENAI, FAL]
    assert result.response_metadata == {"route": "fal-queue", "fallback": {"from_route": "openai", "reason": reason}}
    assert _released(db) == ["call-1"]
    assert JOB not in credits._unsettled_jobs


@pytest.mark.parametrize("detail", [
    "OpenAI image stream failed for gpt-image-2.5-sunburst; request_id=req_1",
    "OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=502",
    "unrecognised gateway failure",
])
def test_unknown_openai_outcome_is_absorbed_and_generated_on_fal(tmp_path, detail):
    result, calls, db, metric = _run(tmp_path, _wire(), [_handler_failure(detail), _ok("fal-queue/openai/gpt-image-2.5/sunburst")])
    assert _models(calls) == [OPENAI, FAL]
    fallback = result.response_metadata["fallback"]
    assert fallback["reason"] == "unknown_outcome"
    assert fallback["absorbed_call_ids"] == ["call-1"]
    assert 0 < fallback["absorbed_estimated_cost_usd"] < 0.25
    # Canary absorbs it: the guarantee is released and the hold is not retained.
    assert _released(db) == ["call-1"]
    assert JOB not in credits._unsettled_jobs
    metric.assert_any_call("canary_absorbed_image_attempts_total", route="openai", surface="asset")


def test_a_request_fault_stops_without_trying_fal_and_keeps_the_hold(tmp_path):
    moderation = _handler_failure(
        "OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=400; detail=code=moderation_blocked")
    with pytest.raises(AITransportError) as caught:
        _run(tmp_path, _wire(), [moderation])
    assert _models(caught.value.calls) == [OPENAI]
    assert _released(caught.value.db) == []
    assert JOB in credits._unsettled_jobs


def test_an_unknown_fal_backup_attempt_is_retained_as_today(tmp_path):
    lost = "OpenAI image stream failed for gpt-image-2.5-sunburst"
    with pytest.raises(AITransportError):
        _run(tmp_path, _wire(), [_handler_failure(lost), _handler_failure("FAL result failed for x")])
    assert JOB in credits._unsettled_jobs


def test_frozen_fal_wires_keep_their_single_route(tmp_path):
    result, calls, _, _ = _run(tmp_path, _wire(provider_key="fal-queue"), [_ok("fal-queue/openai/gpt-image-2.5/sunburst")])
    assert _models(calls) == [FAL]
    assert result.response_metadata is None


def test_draw_and_assets_share_one_circuit(tmp_path):
    for _ in range(3):
        image_route_fallback.OPENAI_SUNBURST_CIRCUIT.record_failure()
    result, calls, _, _ = _run(tmp_path, _wire(), [_ok("fal-queue/openai/gpt-image-2.5/sunburst")])
    assert _models(calls) == [FAL]
    assert result.response_metadata["fallback"] == {"from_route": "openai", "reason": "circuit_open"}


# Classification through the redacting transport ---------------------------------

def test_the_redacted_transport_error_keeps_only_the_phase_marker():
    response = _handler_failure(
        "OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=429; detail=prompt text here")
    error = httpx.HTTPStatusError("500", request=response.request, response=response)
    with pytest.raises(AITransportError) as caught:
        litellm_http._raise_safe_wire_phase_error("gateway_request", error)
    assert "prompt text" not in str(caught.value)
    assert classify_openai_image_failure(caught.value) == "capacity"


def test_an_unreachable_gateway_is_not_submitted():
    with pytest.raises(AITransportError) as caught:
        litellm_http._raise_safe_wire_phase_error("gateway_request", httpx.ConnectError("refused"))
    assert classify_openai_image_failure(caught.value) == "gateway_unreachable"
