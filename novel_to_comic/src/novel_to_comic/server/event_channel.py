"""Bounded per-subscriber pipeline events; persisted status is recovery authority."""
import asyncio
from collections import deque


class EventChannel:
    def __init__(self):
        self.history = deque(maxlen=128)
        self.subscribers: set[asyncio.Queue] = set()

    def put_nowait(self, event: dict) -> None:
        self.history.append(event)
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
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)
