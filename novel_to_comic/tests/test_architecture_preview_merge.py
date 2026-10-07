"""Preview delivery through the merged stage and durable execution paths."""

import asyncio
from types import SimpleNamespace

from novel_to_comic.ai.image_previews import _emit
from novel_to_comic.config import Config
from novel_to_comic.server.event_channel import EventChannel
from novel_to_comic.state import create_initial_state, save_state


def emit_completed_preview():
    _emit("image_preview", target="page:1", request_id="preview-1",
          preview_index=3, preview_total=3, image_url="data:image/webp;base64,x")


def assert_completed_preview(events):
    assert [event["type"] for event in events] == ["image_preview", "image_preview_clear"]
    assert events[0]["target"] == events[1]["target"] == "page:1"
    assert events[0]["request_id"] == events[1]["request_id"] == "preview-1"
    assert events[1]["settled"] is True


def test_worker_preview_delivery_preserves_reconnect_and_clear_semantics():
    async def exercise():
        channel = EventChannel()
        queue = channel.subscribe()
        first = {"type": "image_preview", "target": "page:1", "request_id": "one", "preview_index": 0}
        last = {**first, "preview_index": 3}
        waiting = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        await asyncio.to_thread(channel.put_nowait, first)
        assert await asyncio.wait_for(waiting, 1) == first
        await asyncio.to_thread(channel.put_nowait, last)
        assert await asyncio.wait_for(queue.get(), 1) == last
        assert not channel.history
        replay = channel.subscribe()
        assert replay.get_nowait() == last
        assert replay.empty()

        stale = {"type": "image_preview_clear", "target": "page:1", "request_id": "old"}
        await asyncio.to_thread(channel.put_nowait, stale)
        assert await asyncio.wait_for(queue.get(), 1) == stale
        assert channel.previews["page:1"] == last
        cleared = {**stale, "request_id": "one"}
        await asyncio.to_thread(channel.put_nowait, cleared)
        assert await asyncio.wait_for(queue.get(), 1) == cleared
        assert not channel.previews
        assert not channel.history

    # Debug mode rejects waking a pending subscriber from the worker thread.
    asyncio.run(exercise(), debug=True)


def test_stage_execution_publishes_and_settles_image_previews(monkeypatch, tmp_path):
    from novel_to_comic.server import pipeline_operations

    async def run(config, directory, ctx):
        emit_completed_preview()

    monkeypatch.setitem(pipeline_operations.REGISTRY, "style", SimpleNamespace(run=run))

    async def exercise():
        channel = EventChannel()
        queue = channel.subscribe()
        state = create_initial_state("book", "novel.txt")
        await pipeline_operations._run_stage("style", Config(), tmp_path, state, channel)
        assert_completed_preview([queue.get_nowait(), queue.get_nowait()])
        assert queue.empty()
        assert not channel.previews

    asyncio.run(exercise())


def test_durable_execution_publishes_and_settles_image_previews(monkeypatch, tmp_path):
    from novel_to_comic.server import cover_operations, credits, db, job_execution
    from novel_to_comic.server.deps import event_key
    from novel_to_comic.server.job_commands import command

    directory = tmp_path / "owner" / "book"
    directory.mkdir(parents=True)
    save_state(create_initial_state("book", "novel.txt"), directory)
    spec = command("cover", directory, Config()).model_copy(update={
        "user_id": "owner", "stage": "draw", "ledger_job_id": "ledger-job",
    })
    job = SimpleNamespace(command=spec, project_name="owner:book", payload={})
    app = SimpleNamespace(state=SimpleNamespace(projects_dir=tmp_path, event_queues={}))
    monkeypatch.setattr(db, "get_db", lambda: object())
    monkeypatch.setattr(credits, "reserve_credits", lambda *args, **kwargs: (None, "ledger-job"))
    monkeypatch.setattr(credits, "assert_reservation_active", lambda *args: None)

    async def generate(config, project_dir, user_id, project_id):
        emit_completed_preview()

    monkeypatch.setattr(cover_operations, "_generate_project_cover", generate)

    async def exercise():
        channel = EventChannel()
        app.state.event_queues[event_key(job.project_name, directory)] = channel
        queue = channel.subscribe()
        await job_execution.execute_command(app, job)
        assert_completed_preview([queue.get_nowait(), queue.get_nowait()])
        assert queue.empty()
        assert not channel.previews

    asyncio.run(exercise())
