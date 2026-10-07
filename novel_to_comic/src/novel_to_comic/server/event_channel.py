"""Bounded per-subscriber pipeline events; persisted status is recovery authority."""
import asyncio
from collections import deque


class EventChannel:
    def __init__(self):
        self.history = deque(maxlen=128)
        self.previews: dict[str, dict] = {}
        self.subscribers: set[asyncio.Queue] = set()

    def put_nowait(self, event: dict) -> None:
        kind, target = event.get("type"), event.get("target")
        if kind == "image_preview" and isinstance(target, str):
            self.previews[target] = event
            if len(self.previews) > 32:
                self.previews.pop(next(iter(self.previews)))
        elif kind == "image_preview_clear":
            current = self.previews.get(target)
            if current and (event.get("reset") or current.get("request_id") == event.get("request_id")):
                self.previews.pop(target, None)
        else:
            self.history.append(event)
        if kind == "pipeline_done":
            self.previews.clear()
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        """Replay only the run still in flight.

        A channel outlives its run and is reused by later jobs. Replaying a
        finished run's begin/progress/fail events makes a fresh subscriber
        (opened because an unrelated job is running) re-live that run.
        """
        queue = asyncio.Queue(maxsize=256)
        history = list(self.history)
        finished = [index for index, event in enumerate(history) if event.get("type") == "pipeline_done"]
        for event in history[finished[-1] + 1 if finished else 0:]:
            queue.put_nowait(event)
        for event in self.previews.values():
            queue.put_nowait(event)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)
