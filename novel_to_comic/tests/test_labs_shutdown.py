"""Server shutdown drains Labs cancellation before closing provider clients."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from novel_to_comic.server import app as server, credits, db
from novel_to_comic.ai import client


def test_lifespan_drains_labs(monkeypatch):
    monkeypatch.setattr(server, "configure_telemetry", lambda: False)
    monkeypatch.setattr(server, "_audit_pricing_at_startup", lambda: None)
    monkeypatch.setattr(server, "_refresh_pricing_if_stale", lambda: None)
    monkeypatch.setattr(server, "shutdown_telemetry", lambda: None)
    monkeypatch.setattr(server, "initialize_queue", AsyncMock())
    monkeypatch.setattr(credits, "start_reservation_leases", lambda db: None)
    monkeypatch.setattr(credits, "stop_reservation_leases", lambda: None)
    monkeypatch.setattr(db, "get_db", lambda: None)
    events = []

    async def close():
        events.append("client closed")

    monkeypatch.setattr(client, "_http", SimpleNamespace(aclose=close))

    async def scenario():
        ready = asyncio.Event()
        async def labs():
            try:
                ready.set()
                await asyncio.Future()
            finally:
                await asyncio.sleep(0)
                events.append("labs drained")

        app = SimpleNamespace(state=SimpleNamespace(
            running_tasks={}, style_tasks={}, admission=SimpleNamespace(draining=False),
        ))
        async with server._lifespan(app):
            task = asyncio.create_task(labs())
            app.state.labs_tasks = {"run": task}
            await ready.wait()
        assert task.cancelled()

    asyncio.run(scenario())
    assert events == ["labs drained", "client closed"]
