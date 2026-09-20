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


def test_pipeline_starts_ready_lettering_before_slowest_blueprint_and_keeps_order():
    from novel_to_comic.paid_shards import run_paid_pipeline

    async def scenario():
        ready_lettering = asyncio.Event()
        events = []
        active = 0
        peak = 0

        async def blueprint(index):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                if index == 0:
                    await ready_lettering.wait()
                events.append(f"blueprint {index} saved")
                return index
            finally:
                active -= 1

        async def lettering(index, locked):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                assert locked == index
                assert f"blueprint {index} saved" in events
                events.append(f"lettering {index} saved")
                if index == 1:
                    ready_lettering.set()
                return f"draft {index}"
            finally:
                active -= 1

        result = await asyncio.wait_for(run_paid_pipeline(
            [lambda index=index: blueprint(index) for index in range(5)],
            lettering, limit=2,
        ), timeout=2)
        assert result == [f"draft {index}" for index in range(5)]
        assert peak == 2
        assert events.index("lettering 1 saved") < events.index("blueprint 0 saved")

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_pipeline_failure_or_cancellation_does_not_admit_ready_lettering(cancel):
    from novel_to_comic.paid_shards import run_paid_pipeline

    async def scenario():
        started, release, failed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events = []

        async def slow():
            started.set()
            await release.wait()
            events.append("blueprint saved")
            return "locked"

        async def failing():
            await started.wait()
            failed.set()
            raise ValueError("failed")

        async def lettering(index, locked):
            events.append("lettering submitted")
            return locked

        owner = asyncio.create_task(run_paid_pipeline(
            [slow] if cancel else [slow, failing], lettering, limit=2,
        ))
        await started.wait()
        if cancel:
            owner.cancel()
        else:
            await failed.wait()
        await asyncio.sleep(0)
        assert not owner.done()
        release.set()
        with pytest.raises(asyncio.CancelledError if cancel else ValueError):
            await owner
        assert events == ["blueprint saved"]

    asyncio.run(scenario())
