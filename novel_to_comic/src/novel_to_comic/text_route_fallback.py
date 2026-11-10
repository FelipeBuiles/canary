"""Vertex-first Carbon text calls with Runware Argon as the rate-limit route.

A text model may name a ``rate_limit_fallback`` route sharing its tuning and
controls (``TextModel``). Runware does not offer Gemini 4 Carbon, so Carbon's
fallback is Runware's Gemini 4 Argon (operator-approved 2026-11-10). While
``CANARY_RUNWARE_TEXT_FALLBACK_ENABLED`` is set, a call
to it switches to that route only after the gateway answers 429: Vertex
rejects a rate-limited request before generation, so nothing ran and nothing
was billed. The primary attempt gets no 429 retries of its own; its failed
event stays recorded and the fallback is a separate, separately priced event.

Nothing else switches: timeouts, 5xx and unknown outcomes keep today's
behaviour on the primary route, and a call never returns to the primary once
it has moved. The first 429 opens a circuit so other calls go straight to the
fallback until it cools down.

This is the second approved route switch (AGENTS.md); do not extend it to
other models or failure kinds without approval.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.image_route_fallback import RouteCircuit, increment_metric
from novel_to_comic.text_models import text_wire

logger = logging.getLogger(__name__)

T = TypeVar("T")
CIRCUIT_COOLDOWN_SECONDS = 300.0
_CIRCUITS: dict[str, RouteCircuit] = {}
_pinned: ContextVar[bool] = ContextVar("text_route_pinned", default=False)


def fallback_enabled() -> bool:
    return os.environ.get("CANARY_RUNWARE_TEXT_FALLBACK_ENABLED", "").strip().lower() in {"1", "true"}


@contextmanager
def pinned_text_routes() -> Iterator[None]:
    """Run every text call on the model it names, as Labs comparisons need."""
    token = _pinned.set(True)
    try:
        yield
    finally:
        _pinned.reset(token)


def circuit(model: str) -> RouteCircuit:
    if model not in _CIRCUITS:
        _CIRCUITS[model] = RouteCircuit(
            threshold=1, cooldown_seconds=CIRCUIT_COOLDOWN_SECONDS, route=model,
            next_route=text_wire(model).rate_limit_fallback, subject="text",
            metric="canary_text_route_circuit_opened_total",
        )
    return _CIRCUITS[model]


def rate_limited(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    return isinstance(exc, AITransportError) and getattr(response, "status_code", None) == 429


async def run_rate_limit_fallback(
    model: str, feature: str, attempt: Callable[[str, bool], Awaitable[T]],
) -> T:
    """Run ``attempt(model, primary)`` on the primary route, or once on its fallback.

    ``primary`` is true for the attempt that may switch: it must not spend its
    own 429 retries, so the switch happens on the first rate limit.
    """
    fallback = text_wire(model).rate_limit_fallback
    if not fallback or _pinned.get() or not fallback_enabled():
        return await attempt(model, False)
    route_circuit = circuit(model)
    if route_circuit.is_open():
        reason = "circuit_open"
    else:
        try:
            result = await attempt(model, True)
        except AITransportError as exc:
            if not rate_limited(exc):
                raise
            route_circuit.record_failure()
            reason = "rate_limited"
        else:
            route_circuit.record_success()
            return result
    logger.warning("Text route fallback model=%s fallback=%s feature=%s reason=%s",
                   model, fallback, feature, reason)
    increment_metric("canary_text_route_fallback_total", model=model, fallback=fallback,
                     feature=feature, reason=reason)
    return await attempt(fallback, False)
