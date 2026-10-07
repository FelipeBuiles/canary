"""Process-wide admission for the single-owner API and its worker event loops.

Count every HTTP attempt, including retries. Waiting happens before submission;
an ambiguous image outcome never authorizes another attempt. Token reservations
are pacing estimates, reconciled from usage without changing credit accounting.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import math
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import yaml

from novel_to_comic.ai.context import notify_execution_started
from novel_to_comic.text_models import text_wire
from novel_to_comic.usage import estimate_token_count


_UNSUBMITTED = "_canary_cancelled_before_submission"


def cancelled_before_submission(exc: BaseException) -> bool:
    """Whether a cancellation interrupted only the wait before any HTTP submission.

    The original CancelledError is re-raised (marked, not subclassed) so
    asyncio.timeout/wait_for still convert an expired deadline to TimeoutError.
    """
    return isinstance(exc, asyncio.CancelledError) and getattr(exc, _UNSUBMITTED, False)


class AdmissionRejected(ValueError):
    """Request cannot fit the operator budget; no HTTP submission occurred."""


@dataclass(eq=False)
class _Reservation:
    started: float
    requests: int
    tokens: int


class Lease:
    def __init__(self, owner, pool, bucket=None, policy=None, reservation=None):
        self.owner, self.pool, self.bucket = owner, pool, bucket
        self.policy, self.reservation = policy or {}, reservation
        self.closed = False

    def observe(self, body: dict[str, Any]) -> None:
        usage = body.get("usage")
        if not self.policy.get("tokens_per_minute") or not isinstance(usage, dict):
            return
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
        if input_tokens is None or output_tokens is None:
            return
        try:
            tokens = int(input_tokens) + int(output_tokens) * self.policy.get("output_weight", 1)
        except (ValueError, TypeError, OverflowError):
            return  # Pacing metadata must never discard a paid result.
        self.owner.reconcile(self, max(0, tokens))

    def observe_response(self, response) -> None:
        if self.bucket and response.status_code == 429:
            raw = response.headers.get("retry-after", "")
            try:
                delay = float(raw)
            except (ValueError, TypeError):
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=datetime.UTC)
                    delay = (retry_at - datetime.datetime.now(datetime.UTC)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    delay = 4.0
            self.owner.cooldown(self.bucket, max(0, delay) if math.isfinite(delay) else 4.0)
        try:
            body = response.json()
        except (ValueError, TypeError):
            return
        if isinstance(body, dict):
            self.observe(body)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.owner.release(self.pool)


class AdmissionController:
    def __init__(self, settings: dict, *, clock: Callable[[], float] = time.monotonic, period: float = 60):
        if period <= 0 or any(int(limit) <= 0 for limit in settings["pools"].values()):
            raise ValueError("Admission period and concurrency must be positive")
        for policy in settings.get("budgets", {}).values():
            if policy["pool"] not in settings["pools"]:
                raise ValueError("Admission budget must use a configured pool")
            if any(policy.get(key) is not None and policy[key] <= 0
                   for key in ("tokens_per_minute", "requests_per_minute", "burst_tokens", "burst_requests")):
                raise ValueError("Admission rate budgets must be positive")
        self.settings, self.clock, self.period = settings, clock, period
        self._lock = threading.Lock()
        self._active: dict[str, int] = {}
        self._windows: dict[str, deque[_Reservation]] = {}
        self._virtual: dict[tuple[str, str], float] = {}
        self._blocked: dict[str, float] = {}
        self._waiters: dict[object, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}

    def _spec(self, url: str, params: dict, files: list | None):
        model = str(params.get("model") or "")
        image = "/images/" in urlsplit(url).path
        pool = "images" if image else None
        for name, policy in self.settings.get("budgets", {}).items():
            matches = (image and model in policy.get("aliases", ())) or (
                bool(policy.get("provider")) and text_wire(model).provider_key == policy["provider"] and not image
            )
            if matches:
                bucket = f"{name}:{model}" if policy.get("per_model") else name
                return policy["pool"], bucket, policy, self._estimate(params, files, policy, image)
        # Unmetered image routes still share provider Retry-After cooldowns.
        # Vertex image capacity has no published fixed minute allowance.
        return pool, f"{pool}:{model}" if pool else None, {}, (0, 0)

    @staticmethod
    def _estimate(params: dict, files: list | None, policy: dict, image: bool) -> tuple[int, int]:
        if image:
            count = max(1, int(params.get("n") or 1))
            quality = params.get("quality") or "auto"
            output = policy["image_output_tokens"].get(quality, policy["image_output_tokens"]["auto"])
            tokens = estimate_token_count(str(params.get("prompt") or ""))
            tokens += len(files or ()) * policy["image_input_tokens"] + count * output
            return count, tokens
        tokens = 0
        for message in params.get("messages", ()):
            content = message.get("content") or ""
            if isinstance(content, str):
                tokens += estimate_token_count(content)
            elif isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        tokens += estimate_token_count(str(part.get("text") or ""))
                    elif part.get("type") in {"image_url", "input_image"}:
                        tokens += policy["image_input_tokens"]
        for key in ("response_format", "tools"):
            if params.get(key):
                tokens += estimate_token_count(json.dumps(params[key], ensure_ascii=False))
        metadata = params.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                metadata = {}  # Pacing must not reject a request over its tracing metadata.
        if not isinstance(metadata, dict):
            metadata = {}
        feature = (metadata.get("metadata") or {}).get("feature", "")
        output = policy.get("output_tokens_by_feature", {}).get(feature, policy["estimated_output_tokens"])
        maximum = params.get("max_completion_tokens") or params.get("max_tokens")
        if maximum:
            output = min(output, int(maximum))
        return 1, int(tokens * 1.15) + output * policy["output_weight"]

    def _notify(self) -> None:
        for loop, event in self._waiters.values():
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(event.set)
                except RuntimeError:
                    pass  # The worker loop may close after the check above.

    def _prune(self, bucket: str, now: float) -> deque[_Reservation]:
        entries = self._windows.setdefault(bucket, deque())
        while entries and entries[0].started <= now - self.period:
            entries.popleft()
        return entries

    def _delay(self, bucket, policy, requests, tokens, now) -> float:
        entries = self._prune(bucket, now)
        delay = max(0.0, self._blocked.get(bucket, 0) - now)
        for kind, amount, limit, burst in (
            ("requests", requests, policy.get("requests_per_minute"), policy.get("burst_requests")),
            ("tokens", tokens, policy.get("tokens_per_minute"), policy.get("burst_tokens")),
        ):
            if not limit:
                continue
            if amount > limit:
                raise AdmissionRejected(f"Request exceeds configured {bucket} {kind} admission budget")
            # Rolling budget plus a smooth refill; allow six proofs to start together.
            used = sum(getattr(entry, kind) for entry in entries)
            for entry in entries:
                if used + amount <= limit:
                    break
                used -= getattr(entry, kind)
                delay = max(delay, entry.started + self.period - now)
            if burst:
                rate = limit / self.period
                virtual = max(now, self._virtual.get((bucket, kind), now))
                delay = max(delay, virtual + amount / rate - max(burst, amount) / rate - now)
        return max(0.0, delay)

    async def acquire(self, url: str, params: dict | None = None, files: list | None = None) -> Lease | None:
        pool, bucket, policy, (requests, tokens) = self._spec(url, params or {}, files)
        if pool is None:
            return None
        event = asyncio.Event()
        token = object()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._waiters[token] = (loop, event)
        try:
            while True:
                with self._lock:
                    event.clear()
                    now = self.clock()
                    delay = self._delay(bucket, policy, requests, tokens, now) if bucket else 0
                    if self._active.get(pool, 0) < self.settings["pools"][pool] and delay <= 0:
                        self._active[pool] = self._active.get(pool, 0) + 1
                        reservation = None
                        if bucket:
                            reservation = _Reservation(now, requests, tokens)
                            self._windows[bucket].append(reservation)
                            for kind, amount, limit in (
                                ("requests", requests, policy.get("requests_per_minute")),
                                ("tokens", tokens, policy.get("tokens_per_minute")),
                            ):
                                if limit:
                                    key = (bucket, kind)
                                    self._virtual[key] = max(now, self._virtual.get(key, now)) + amount * self.period / limit
                        return Lease(self, pool, bucket, policy, reservation)
                try:
                    await asyncio.wait_for(event.wait(), timeout=delay if delay > 0 else None)
                except TimeoutError:
                    pass
        except asyncio.CancelledError as exc:
            setattr(exc, _UNSUBMITTED, True)
            raise
        finally:
            with self._lock:
                self._waiters.pop(token, None)

    def reconcile(self, lease: Lease, tokens: int) -> None:
        with self._lock:
            now = self.clock()
            entries = self._prune(lease.bucket, now)
            previous = lease.reservation.tokens
            delta = tokens - previous
            if lease.reservation in entries:
                lease.reservation.tokens = tokens
            else:
                # A long stream's estimate may have expired. Charge excess usage
                # now, without refunding an already-expired reservation.
                if delta > 0:
                    entries.append(_Reservation(now, 0, delta))
                lease.reservation.tokens = tokens
                delta = max(0, delta)
            limit = lease.policy.get("tokens_per_minute")
            if limit:
                key = (lease.bucket, "tokens")
                self._virtual[key] = max(now, self._virtual.get(key, now) + delta * self.period / limit)
            self._notify()

    def release(self, pool: str) -> None:
        with self._lock:
            self._active[pool] -= 1
            self._notify()

    def cooldown(self, bucket: str, delay: float) -> None:
        with self._lock:
            self._blocked[bucket] = max(self._blocked.get(bucket, 0), self.clock() + delay)
            self._notify()


def new_controller() -> AdmissionController:
    path = Path(__file__).resolve().parents[1] / "ai_request_limits.yaml"
    return AdmissionController(yaml.safe_load(path.read_text()))


_controller = new_controller()


@asynccontextmanager
async def admitted(url: str, *, json: dict | None = None, data: dict | None = None, files: list | None = None):
    lease = await _controller.acquire(url, data if data is not None else json, files)
    try:
        yield lease
    finally:
        if lease:
            lease.close()


async def post(http, url: str, **kwargs):
    async with admitted(url, json=kwargs.get("json"), data=kwargs.get("data"), files=kwargs.get("files")) as lease:
        notify_execution_started()
        response = await http.post(url, **kwargs)
        if lease:
            lease.observe_response(response)
        return response


@asynccontextmanager
async def stream(http, method: str, url: str, **kwargs):
    async with admitted(url, json=kwargs.get("json"), data=kwargs.get("data"), files=kwargs.get("files")) as lease:
        notify_execution_started()
        async with http.stream(method, url, **kwargs) as response:
            yield response, lease
