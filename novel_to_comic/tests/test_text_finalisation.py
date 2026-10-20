"""The lifecycle books exactly one terminal outcome across a fake route."""
import asyncio

import httpx
import pytest

from novel_to_comic.ai import client, text_finalisation
from novel_to_comic.config import Config


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
def test_fake_route_terminal_accounting(monkeypatch, outcome):
    events = []
    monkeypatch.setattr(client, "_insert_event", lambda **kw: events.append(("insert", kw)))
    monkeypatch.setattr(client, "_finalize_event", lambda **kw: events.append(("terminal", kw)))

    async def route(request, *, state, **kwargs):
        state.submission_started = True
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        if outcome == "failed":
            raise ValueError("rejected locally")
        state.text = "A story"
        state.finish_reason = "stop"
        state.data = {"usage": {"prompt_tokens": 10, "completion_tokens": 3}}
        state.response = httpx.Response(200)
        return state

    monkeypatch.setattr(text_finalisation, "execute_text_route", route)
    call = text_finalisation.complete_text(
        config=Config(), model="gpt-6-sol", system_prompt="Write", user_content="Story",
        temperature=.2, max_output_tokens=32, json_mode=False, feature="adapt.book",
    )
    if outcome == "succeeded":
        result = asyncio.run(call)
        assert result["text"] == "A story"
        assert result["usage"].input_tokens == 10
    else:
        with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else ValueError):
            asyncio.run(call)
    assert [kind for kind, _ in events] == ["insert", "terminal"]
    assert events[-1][1]["status"] == outcome
