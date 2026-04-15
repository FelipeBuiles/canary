"""Structured event system for pipeline stages.

Each stage ``run()`` function accepts an optional ``on_event`` callback.
The CLI passes ``None`` (no-op — Rich console output is unchanged).
The web dashboard injects a callback that streams events to the browser
over SSE or WebSocket.

Event schema (all fields are strings / ints — JSON-serialisable by default)
----------------------------------------------------------------------------
stage_begin      stage: str, total: int
stage_progress   stage: str, done: int, total: int
stage_complete   stage: str, done: int, total: int
stage_fail       stage: str, message: str
log              stage: str, level: str, message: str
                   level one of: "info" | "warn" | "error" | "dim" | "bold"

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
_NOOP: EventCallback = lambda _: None
