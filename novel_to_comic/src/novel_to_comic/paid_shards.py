"""Bounded paid work: stop admission on failure, drain owned calls before exit."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
U = TypeVar("U")


async def _drain_paid_work(work: deque[Callable[[], Awaitable[None]]], *, limit: int) -> None:
    """Run ready operations, including dependencies unlocked by completed work."""
    if limit < 1:
        raise ValueError("paid shard concurrency must be positive")
    failure: BaseException | None = None
    stopped = False

    async def worker() -> None:
        nonlocal failure, stopped
        while not stopped and work:
            operation = work.popleft()
            try:
                await operation()
            except BaseException as error:
                if failure is None:
                    failure = error
                stopped = True

    drain = asyncio.gather(*(worker() for _ in range(min(limit, len(work)))))
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            await asyncio.shield(drain)
            break
        except asyncio.CancelledError as error:
            stopped = True
            cancellation = error
    if cancellation is not None:
        raise cancellation
    if failure is not None:
        raise failure


async def run_paid_shards(work: Sequence[Callable[[], Awaitable[T]]], *, limit: int) -> list[T]:
    """Keep provider calls, accounting and checkpoints inside the caller's lifetime.

    Cancellation closes admission but never cancels an ambiguous paid call. Each
    admitted callable must include its accounting and persistence, not just HTTP.
    """
    results: dict[int, T] = {}

    async def run(index: int, operation: Callable[[], Awaitable[T]]) -> None:
        results[index] = await operation()

    await _drain_paid_work(deque(
        lambda index=index, operation=operation: run(index, operation)
        for index, operation in enumerate(work)
    ), limit=limit)
    return [results[index] for index in range(len(work))]


async def run_paid_pipeline(
    first: Sequence[Callable[[], Awaitable[T]]],
    then: Callable[[int, T], Awaitable[U]],
    *,
    limit: int,
) -> list[U]:
    """Unlock each shard's second operation as soon as its first is saved.

    Both phases share one admission limit. A failed sibling or cancellation
    prevents any further second-phase submissions, while admitted operations
    finish accounting/checkpointing. Results retain original shard order.
    """
    results: dict[int, U] = {}
    ready: deque[Callable[[], Awaitable[None]]] = deque()

    async def finish(index: int, value: T) -> None:
        results[index] = await then(index, value)

    async def start(index: int, operation: Callable[[], Awaitable[T]]) -> None:
        value = await operation()
        ready.appendleft(lambda: finish(index, value))

    ready.extend(lambda index=index, operation=operation: start(index, operation)
                 for index, operation in enumerate(first))
    await _drain_paid_work(ready, limit=limit)
    return [results[index] for index in range(len(first))]
