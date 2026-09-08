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
        queue = asyncio.Queue(maxsize=256)
        for event in self.history:
            queue.put_nowait(event)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)
