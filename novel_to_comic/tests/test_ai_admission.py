"""Admission uses existing provider budgets; tests never submit paid calls."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import threading
import time

import httpx
import pytest

from novel_to_comic.ai import admission, client
from novel_to_comic.ai.context import execution_observer


GEN = "http://gateway/v1/images/generations"
EDIT = "http://gateway/v1/images/edits"
CHAT = "http://gateway/v1/chat/completions"


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def controller(*, concurrency=12, requests=18, tokens=225000, burst=None, clock=None):
    return admission.AdmissionController({
        "pools": {"images": concurrency, "vertex_text": 16},
        "budgets": {"openai_images": {
            "aliases": ["image-sunburst-openai", "image-flare"], "pool": "images",
            "requests_per_minute": requests, "burst_requests": burst,
            "tokens_per_minute": tokens, "image_input_tokens": 100,
            "image_output_tokens": {"auto": 100}, "output_weight": 1,
        }},
    }, clock=clock or time.monotonic)


def image(model="image-sunburst-openai"):
    return {"model": model, "prompt": "proof", "n": 1}


def test_generations_edits_and_flare_share_one_minute_budget():
    clock = Clock()
    gate = controller(requests=2, clock=clock)

    async def run():
        first = await gate.acquire(GEN, image())
        second = await gate.acquire(EDIT, image("image-flare"), [("image", b"ref")])
        waiting = asyncio.create_task(gate.acquire(GEN, image()))
        await asyncio.sleep(0)
        assert not waiting.done()
        clock.now = 60
        first.close()
        third = await asyncio.wait_for(waiting, 1)
        second.close()
        third.close()
    asyncio.run(run())


def test_six_proofs_start_together_then_starts_are_smoothed():
    clock = Clock()
    gate = controller(burst=6, clock=clock)

    async def run():
        leases = [await gate.acquire(GEN, image()) for _ in range(6)]
        waiting = asyncio.create_task(gate.acquire(EDIT, image()))
        await asyncio.sleep(0)
        assert not waiting.done()
        clock.now = 4
        leases[0].close()
        extra = await asyncio.wait_for(waiting, 1)
        for lease in leases[1:]:
            lease.close()
        extra.close()
    asyncio.run(run())


def test_actual_usage_refunds_estimate_and_unblocks_waiting_request():
    gate = controller(tokens=150)

    async def run():
        lease = await gate.acquire(GEN, image())
        waiting = asyncio.create_task(gate.acquire(EDIT, image()))
        await asyncio.sleep(0)
        assert not waiting.done()
        lease.observe({"usage": {"input_tokens": 1, "output_tokens": 1}})
        second = await asyncio.wait_for(waiting, 1)
        lease.close()
        second.close()
    asyncio.run(run())


def test_token_overrun_delays_new_requests_after_long_stream():
    clock = Clock()
    gate = controller(tokens=200, clock=clock)

    async def run():
        first = await gate.acquire(GEN, image())
        clock.now = 61
        first.observe({"usage": {"input_tokens": 200, "output_tokens": 50}})
        waiting = asyncio.create_task(gate.acquire(GEN, image()))
        await asyncio.sleep(0)
        assert not waiting.done()
        clock.now = 121
        first.close()
        second = await asyncio.wait_for(waiting, 1)
        second.close()
    asyncio.run(run())


def test_cancellation_while_waiting_never_posts_or_leaks_capacity(monkeypatch):
    gate = controller(concurrency=1)
    monkeypatch.setattr(admission, "_controller", gate)
    posts = []

    class Http:
        async def post(self, url, **kwargs):
            posts.append(url)
            return httpx.Response(200, json={"usage": {"input_tokens": 1, "output_tokens": 1}})

    async def run():
        first = await gate.acquire(GEN, image())
        waiting = asyncio.create_task(client._post_with_retry(GEN, headers={}, json=image(), retry_ambiguous=False))
        monkeypatch.setattr(client, "_http", Http())
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await waiting
        assert admission.cancelled_before_submission(cancelled.value)
        assert posts == []
        first.close()
        await client._post_with_retry(EDIT, headers={}, json=image(), retry_ambiguous=False)
        assert posts == [EDIT]
    asyncio.run(run())
    assert gate._active["images"] == 0
    assert not gate._waiters


def test_deadline_while_waiting_is_a_timeout_not_a_cancellation():
    gate = controller(concurrency=1)

    async def run():
        first = await gate.acquire(GEN, image())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(gate.acquire(GEN, image()), timeout=0.01)
        first.close()
    asyncio.run(run())
    assert gate._active["images"] == 0
    assert not gate._waiters


@pytest.mark.parametrize("streaming", [False, True])
def test_execution_observer_fires_only_after_transport_admission(monkeypatch, streaming):
    gate = controller(concurrency=1)
    monkeypatch.setattr(admission, "_controller", gate)
    executions = []
    response = httpx.Response(200, json={})

    class Http:
        async def post(self, *args, **kwargs):
            return response

        @asynccontextmanager
        async def stream(self, *args, **kwargs):
            yield response

    async def call():
        with execution_observer(lambda: executions.append("submitted")):
            if streaming:
                async with admission.stream(Http(), "POST", GEN, json=image()):
                    pass
            else:
                await admission.post(Http(), GEN, json=image())

    async def run():
        held = await gate.acquire(GEN, image())
        waiting = asyncio.create_task(call())
        await asyncio.sleep(0)
        assert not executions
        held.close()
        await asyncio.wait_for(waiting, 1)
        assert executions == ["submitted"]

    asyncio.run(run())


def test_http_retries_count_as_new_admissions(monkeypatch):
    clock = Clock()
    gate = controller(requests=2, clock=clock)
    monkeypatch.setattr(admission, "_controller", gate)
    calls = []

    class Http:
        async def post(self, url, **kwargs):
            calls.append(url)
            return httpx.Response(429 if len(calls) < 3 else 200,
                                  request=httpx.Request("POST", url), json={"error": {}})

    async def pause(self, **kwargs):
        clock.now += 30

    monkeypatch.setattr(client, "_http", Http())
    monkeypatch.setattr(client._RetryPacer, "pause_or_raise", pause)
    asyncio.run(client._post_with_retry(GEN, headers={}, json=image(), retry_ambiguous=False))
    assert len(calls) == 3
    assert [r.started for r in gate._windows["openai_images"]] == [30, 60]


@pytest.mark.parametrize("model", ["image-sunburst-openai", "image-nano-banana-2.1"])
def test_429_cooldown_is_shared_with_other_requests(model):
    clock = Clock()
    gate = controller(clock=clock)

    async def run():
        first = await gate.acquire(GEN, image(model))
        first.observe_response(httpx.Response(429, headers={"retry-after": "10"}, json={"error": {}}))
        waiting = asyncio.create_task(gate.acquire(EDIT, image(model)))
        await asyncio.sleep(0)
        assert not waiting.done()
        clock.now = 10
        first.close()
        second = await asyncio.wait_for(waiting, 1)
        second.close()
    asyncio.run(run())


def test_one_request_larger_than_smoothing_burst_can_progress():
    gate = controller()
    gate.settings["budgets"]["openai_images"]["burst_tokens"] = 10

    async def run():
        lease = await asyncio.wait_for(gate.acquire(GEN, image()), 1)
        lease.close()
    asyncio.run(run())


def test_request_larger_than_minute_budget_rejected_before_post(monkeypatch):
    monkeypatch.setattr(admission, "_controller", controller(tokens=50))

    class Http:
        async def post(self, *args, **kwargs):
            pytest.fail("local rejection must happen before any paid submission")
    with pytest.raises(admission.AdmissionRejected):
        asyncio.run(admission.post(Http(), GEN, json=image()))


def test_global_image_capacity_spans_independent_event_loops():
    gate = controller(concurrency=2)
    barrier = threading.Barrier(2)
    active = peak = 0
    lock = threading.Lock()

    async def run():
        nonlocal active, peak
        async def call():
            nonlocal active, peak
            lease = await gate.acquire(GEN, image("image-nano-banana-2.1"))
            try:
                with lock:
                    active += 1
                    peak = max(peak, active)
                await asyncio.sleep(.01)
                with lock:
                    active -= 1
            finally:
                lease.close()
        await asyncio.gather(*(call() for _ in range(5)))

    def worker():
        barrier.wait(timeout=2)
        asyncio.run(run())
    with ThreadPoolExecutor(max_workers=2) as threads:
        futures = [threads.submit(worker) for _ in range(2)]
        for future in futures:
            future.result(timeout=3)
    assert peak == 2 and active == 0


def test_vertex_budget_counts_weighted_tokens_and_not_base64_bytes():
    gate = admission.new_controller()
    params = {"model": "gemini-3.8-flash", "messages": [{"role": "user", "content": [
        {"type": "text", "text": "review"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "a" * 1000000}},
    ]}], "metadata": {"metadata": {"feature": "plan.narrative_review"}}}
    pool, bucket, policy, (_, cost) = gate._spec(CHAT, params, None)
    assert pool == "vertex_text" and bucket == "vertex_text:gemini-3.8-flash"
    assert 2500 < cost < 5000
    lease = asyncio.run(gate.acquire(CHAT, params))
    lease.observe({"usage": {"prompt_tokens": 10, "completion_tokens": 20}})
    assert lease.reservation.tokens == 110
    lease.close()


def test_buffered_and_streamed_calls_share_capacity_and_usage(monkeypatch):
    gate = controller(concurrency=1)
    monkeypatch.setattr(admission, "_controller", gate)

    class Http:
        @asynccontextmanager
        async def stream(self, *args, **kwargs):
            yield httpx.Response(200, json={"usage": {"input_tokens": 2, "output_tokens": 3}})

    async def run():
        async with admission.stream(Http(), "POST", GEN, json=image()) as (response, lease):
            waiting = asyncio.create_task(gate.acquire(EDIT, image()))
            await asyncio.sleep(0)
            assert not waiting.done()
            lease.observe_response(response)
            assert lease.reservation.tokens == 5
        second = await asyncio.wait_for(waiting, 1)
        second.close()
    asyncio.run(run())


@pytest.mark.parametrize("url,params,pool,limit", [
    (GEN, image("image-nano-banana-2.1"), "images", 12),
    (CHAT, {"model": "gemini-3.8-flash", "messages": [{"role": "user", "content": "review"}],
            "metadata": {"metadata": {"feature": "plan.narrative_review"}}}, "vertex_text", 16),
])
def test_production_limits_admit_twelve_images_and_sixteen_vertex_calls(monkeypatch, url, params, pool, limit):
    gate = admission.new_controller()
    monkeypatch.setattr(admission, "_controller", gate)

    async def run():
        started = asyncio.Event()
        release = asyncio.Event()
        active = peak = calls = 0

        class Http:
            async def post(self, *args, **kwargs):
                nonlocal active, peak, calls
                active += 1
                calls += 1
                peak = max(peak, active)
                if calls == limit:
                    started.set()
                try:
                    await release.wait()
                    return httpx.Response(200, json={"usage": {"input_tokens": 1, "output_tokens": 1}})
                finally:
                    active -= 1

        tasks = [asyncio.create_task(admission.post(Http(), url, json=params)) for _ in range(limit + 1)]
        await asyncio.wait_for(started.wait(), 1)
        assert calls == limit and peak == limit
        assert gate._active[pool] == limit
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert calls == limit + 1 and active == 0 and gate._active[pool] == 0

    asyncio.run(run())


def test_invalid_usage_metadata_keeps_paid_response(monkeypatch):
    gate = controller()
    monkeypatch.setattr(admission, "_controller", gate)
    response = httpx.Response(200, json={"usage": {"input_tokens": "invalid", "output_tokens": 1}})

    class Http:
        async def post(self, *args, **kwargs):
            return response

    assert asyncio.run(admission.post(Http(), GEN, json=image())) is response
    assert gate._active["images"] == 0
