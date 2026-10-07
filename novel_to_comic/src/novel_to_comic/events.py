"""Structured event system for pipeline stages.

Each stage ``run()`` function accepts an optional ``on_event`` callback.
The CLI passes ``None`` (no-op — Rich console output is unchanged).
The web dashboard injects a callback that streams events to the browser
over SSE or WebSocket.

Event schema (all fields are strings / ints — JSON-serialisable by default)
----------------------------------------------------------------------------
stage_begin      stage: str, total: int
stage_progress   stage: str, done: int, total: int
stage_activity   stage: str, fraction: float | None (0..1), detail: str | None,
                 at: str (ISO-8601 UTC)
                   Sub-item progress inside the item being worked on, driven by
                   streamed completions. Advisory and not persisted: it may move
                   backwards when a request retries, so consumers must keep it
                   out of the items_done counters that /status reconciles.
                   `at` doubles as a liveness heartbeat for long single calls.
stage_complete   stage: str, done: int, total: int
stage_fail       stage: str, message: str
log              stage: str, level: str, message: str
                   level one of: "info" | "warn" | "error" | "dim" | "bold"
page_start       stage: str, page_number: int, started_at: str (ISO-8601 UTC)
page_done        stage: str, page_number: int, revision: int,
                 status: "ok" | "failed", duration_ms: int,
                 error: str | None
image_preview    stage: str, target: str (project-relative asset path or page:N),
                 request_id: str, preview_index: int (0..3; 3 = completed pixels), preview_total: int,
                 image_url: str (bounded WebP data URL)
                   Advisory pixels only; never saved artwork, item completion,
                   provider success, or visual-review evidence.
image_preview_clear stage: str, target: str, request_id: str, reset: bool | absent,
                    settled: bool | absent
                   Discard on failure, fallback or job termination. A reset
                   starts a new request; other clears match the request ID.
                   settled marks completed pixels from a successful job: the
                   UI may hold them only until the saved file loads.

Example usage in a stage
-------------------------
    from novel_to_comic.events import EventCallback, _NOOP

    async def run(config, project_dir, state, on_event: EventCallback | None = None):
        emit = on_event or _NOOP

        begin_stage(state, "myscene", total=len(items))
        emit({"type": "stage_begin", "stage": "myscene", "total": len(items)})

        for item in items:
            ...
            record_item_done(state, "myscene")
            emit({
                "type": "stage_progress", "stage": "myscene",
                "done":  state.stages["myscene"].items_done,
                "total": state.stages["myscene"].items_total,
            })

        complete_stage(state, "myscene")
        emit({
            "type": "stage_complete", "stage": "myscene",
            "done":  state.stages["myscene"].items_done,
            "total": state.stages["myscene"].items_total,
        })

Web dashboard example
---------------------
    # FastAPI SSE endpoint:
    import json, asyncio
    from fastapi.responses import StreamingResponse

    async def run_stage_stream(config, project_dir, state):
        queue: asyncio.Queue = asyncio.Queue()

        async def generator():
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\\n\\n"
                if event["type"] in ("stage_complete", "stage_fail"):
                    break

        asyncio.create_task(
            stage.run(config, project_dir, state,
                      on_event=lambda e: queue.put_nowait(e))
        )
        return StreamingResponse(generator(), media_type="text/event-stream")
"""

from __future__ import annotations

from typing import Any, Callable

# Type alias — a callable that receives one dict event and returns nothing.
EventCallback = Callable[[dict[str, Any]], None]

# Sentinel no-op: stages call ``emit = on_event or _NOOP`` so callers that
# pass None pay zero overhead.
def _NOOP(_: dict[str, Any]) -> None:
    return None


class _SilentProgress:
    """Progress stand-in that discards all output.

    Used when ``on_event`` is provided (TUI / web server mode) — progress
    is reported via ``emit()`` instead of Rich's live display.
    """

    def add_task(self, *a, **kw):
        return None

    def advance(self, *a, **kw):
        pass

    def update(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def make_progress(on_event):
    """Return a Progress appropriate for the execution mode.

    When ``on_event`` is provided (TUI or web server), returns a silent
    stand-in so progress is reported via ``emit()`` only.  When ``on_event``
    is ``None`` (CLI mode), returns a real Rich ``Progress`` bar.
    """
    if on_event is not None:
        return _SilentProgress()
    from rich.progress import Progress
    return Progress()
