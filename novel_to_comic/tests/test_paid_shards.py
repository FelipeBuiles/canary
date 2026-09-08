import asyncio

import pytest

from novel_to_comic.paid_shards import run_paid_shards


def test_failed_shard_stops_queue_and_drains_provider_accounting_and_checkpoint():
    async def scenario():
        started = asyncio.Event()
        failed = asyncio.Event()
        release = asyncio.Event()
        events = []

        async def failing():
            await started.wait()
            failed.set()
            raise ValueError("shard failed")

        async def paid():
            started.set()
            await release.wait()
            events.extend(["provider completed", "usage accounted", "checkpoint saved"])

        async def queued():
            events.append("queued provider submitted")

        owner = asyncio.create_task(run_paid_shards([failing, paid, queued], limit=2))
        await failed.wait()
        await asyncio.sleep(0)
        assert not owner.done()
        release.set()
        with pytest.raises(ValueError, match="shard failed"):
            await owner
        assert events == ["provider completed", "usage accounted", "checkpoint saved"]

    asyncio.run(scenario())


def test_cancelled_stage_drains_ambiguous_paid_call_without_starting_queue():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        events = []

        async def paid():
            started.set()
            await release.wait()
            events.append("checkpoint saved")

        async def queued():
            events.append("queued provider submitted")

        owner = asyncio.create_task(run_paid_shards([paid, queued], limit=1))
        await started.wait()
        owner.cancel()
        await asyncio.sleep(0)
        assert not owner.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert events == ["checkpoint saved"]

    asyncio.run(scenario())
