"""Bounded paid work: stop admission on failure, drain owned calls before exit."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


async def run_paid_shards(work: Sequence[Callable[[], Awaitable[T]]], *, limit: int) -> list[T]:
    """Keep provider calls, accounting and checkpoints inside the caller's lifetime.

    Cancellation closes admission but never cancels an ambiguous paid call. Each
    admitted callable must include its accounting and persistence, not just HTTP.
    """
    if limit < 1:
        raise ValueError("paid shard concurrency must be positive")
    results: dict[int, T] = {}
    next_index = 0
    failure: BaseException | None = None
    stopped = False

    async def worker() -> None:
        nonlocal next_index, failure, stopped
        while not stopped and next_index < len(work):
            index = next_index
            next_index += 1
            try:
                results[index] = await work[index]()
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
    return [results[index] for index in range(len(work))]
