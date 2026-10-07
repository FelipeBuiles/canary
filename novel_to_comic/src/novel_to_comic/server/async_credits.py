"""Bounded synchronous ledger I/O with cancellation-safe completion.

A cancelled RPC can still have committed. Wait for its result without blocking
the event loop; reservation callers release a hold obtained before execution.
Never retry a provider submission here.
"""

from __future__ import annotations

import asyncio
import logging
from weakref import WeakKeyDictionary

_limits = WeakKeyDictionary()
logger = logging.getLogger("canary.credits")


async def _finish(task):
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def ledger_call(operation, *args, cancel_cleanup=None, **kwargs):
    loop = asyncio.get_running_loop()
    limit = _limits.setdefault(loop, asyncio.Semaphore(8))
    async with limit:
        task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                result = await _finish(task)
                if cancel_cleanup is not None:
                    await _finish(
                        asyncio.create_task(asyncio.to_thread(cancel_cleanup, result))
                    )
            except Exception:
                # Preserve cancellation even if the completed RPC or cleanup
                # failed. The ledger retains its outcome for reconciliation.
                logger.warning("Ledger completion after cancellation failed", exc_info=True)
            raise


def release_unstarted_hold(db, result):
    from .credits import release_reservation

    if result[0]:
        release_reservation(db, result[0])
