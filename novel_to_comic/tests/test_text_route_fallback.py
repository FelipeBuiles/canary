"""Vertex Argon calls move to Runware only after a definite 429; never on unknown outcomes."""
import asyncio
import json

import httpx
import pytest

from novel_to_comic import text_route_fallback
from novel_to_comic.ai import client
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.config import Config
from novel_to_comic.text_models import TEXT_MODEL_BY_ID, TextModelJob

ARGON, RUNWARE = "gemini-4-carbon", "runware-gemini-4-argon"


def _answer(model):
    return httpx.Response(200, json={
        "model": model, "choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    })


@pytest.fixture
def gateway(monkeypatch):
    """Answers per model; records every POST the app makes."""
    monkeypatch.setenv("CANARY_RUNWARE_TEXT_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("CANARY_AI_STREAM_TEXT", "0")
    monkeypatch.setattr(text_route_fallback, "_CIRCUITS", {})
    events, sent, answers = [], [], {}
    monkeypatch.setattr(client, "_insert_event", lambda **kwargs: events.append(("insert", kwargs)))
    monkeypatch.setattr(client, "_finalize_event", lambda **kwargs: events.append(("finalize", kwargs)))
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)

    async def unpaced_post(http, url, **kwargs):
        # Routing, not pacing: skip admission's shared 429 cooldown.
        return await http.post(url, **kwargs)

    monkeypatch.setattr(client, "admitted_post", unpaced_post)

    def handler(request):
        model = json.loads(request.content)["model"]
        sent.append(model)
        answer = answers.get(model, _answer)
        if isinstance(answer, Exception):
            raise answer
        return answer(model) if callable(answer) else answer

    monkeypatch.setattr(client, "_http", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return {"events": events, "sent": sent, "answers": answers, "delays": delays}


def _call(feature="plan.detail"):
    return asyncio.run(client.generate_structured_object(
        config=Config(), model=ARGON, system_prompt="Return JSON.", user_content="Plan the page.",
        feature=feature,
    ))


def _finalized(events):
    return [(kwargs["model_alias"], kwargs["status"]) for kind, kwargs in events if kind == "finalize"]


def test_first_429_switches_once_and_both_attempts_stay_recorded(gateway):
    gateway["answers"][ARGON] = httpx.Response(429)
    result = _call()
    assert result.value == {"ok": True}
    assert gateway["sent"] == [ARGON, RUNWARE]
    assert gateway["delays"] == []  # no Vertex backoff before the switch
    assert _finalized(gateway["events"]) == [(ARGON, "failed"), (RUNWARE, "succeeded")]
    assert result.usage.provider == "runware"


def test_open_circuit_sends_later_calls_straight_to_runware(gateway):
    gateway["answers"][ARGON] = httpx.Response(429)
    _call()
    gateway["answers"].pop(ARGON)
    _call("extract.story_bible")
    assert gateway["sent"] == [ARGON, RUNWARE, RUNWARE]


def test_circuit_closes_after_its_cooldown(gateway, monkeypatch):
    gateway["answers"][ARGON] = httpx.Response(429)
    _call()
    gateway["answers"].pop(ARGON)
    text_route_fallback.circuit(ARGON).reset()
    _call()
    assert gateway["sent"] == [ARGON, RUNWARE, ARGON]


@pytest.mark.parametrize("answer", [httpx.Response(500), httpx.Response(400), httpx.ReadTimeout("lost")])
def test_errors_other_than_429_never_switch(gateway, answer):
    gateway["answers"][ARGON] = answer
    with pytest.raises(AITransportError):
        _call()
    assert RUNWARE not in gateway["sent"]
    assert not text_route_fallback.circuit(ARGON).is_open()


def test_runware_rate_limits_keep_their_retries_and_never_return_to_vertex(gateway):
    gateway["answers"][ARGON] = httpx.Response(429)
    gateway["answers"][RUNWARE] = httpx.Response(429)
    with pytest.raises(AITransportError):
        _call()
    assert gateway["sent"] == [ARGON] + [RUNWARE] * (client._MAX_RATE_LIMIT_RETRIES + 1)


@pytest.mark.parametrize("flag", ["", "false"])
def test_disabled_flag_keeps_todays_vertex_retries(gateway, monkeypatch, flag):
    monkeypatch.setenv("CANARY_RUNWARE_TEXT_FALLBACK_ENABLED", flag)
    gateway["answers"][ARGON] = httpx.Response(429)
    with pytest.raises(AITransportError):
        _call()
    assert gateway["sent"] == [ARGON] * (client._MAX_RATE_LIMIT_RETRIES + 1)


def test_labs_pins_the_named_model(gateway):
    gateway["answers"][ARGON] = httpx.Response(429)
    with text_route_fallback.pinned_text_routes(), pytest.raises(AITransportError):
        _call()
    assert RUNWARE not in gateway["sent"]


def test_a_bound_stage_job_accepts_its_models_fallback(gateway):
    gateway["answers"][ARGON] = httpx.Response(429)
    with TextModelJob("plan", ARGON).bind():
        assert _call().value == {"ok": True}
    with TextModelJob("plan", ARGON).bind(), pytest.raises(ValueError, match="bound to"):
        asyncio.run(client.generate_structured_object(
            config=Config(), model="runware-deepseek-v4.1-flash-1017", system_prompt="Return JSON.",
            user_content="u", feature="plan.detail",
        ))


def test_only_argon_names_a_rate_limit_route_and_it_shares_argons_tuning():
    assert {m.id: m.rate_limit_fallback for m in TEXT_MODEL_BY_ID.values() if m.rate_limit_fallback} == {
        ARGON: RUNWARE,
    }
    assert TEXT_MODEL_BY_ID[RUNWARE].tuning == ARGON
