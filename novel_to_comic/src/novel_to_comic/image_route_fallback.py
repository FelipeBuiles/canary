"""OpenAI-first Sunburst routing with one FAL attempt as backup.

Every new Sunburst image (Draw pages, Style samples, Cast references, covers)
tries OpenAI first. One FAL attempt follows only when OpenAI failed for
availability. An OpenAI attempt with an unknown outcome also falls back once:
the Images API has no result retrieval, so its image can never arrive later
and no duplicate can be published. Canary absorbs that attempt's possible
charge — its call guarantee is released and the job hold is not retained for
it — while the attempt stays recorded in provenance. This is the one approved
exception to "no automatic retry after an ambiguous paid image submission";
do not extend it to other routes.

While the Runware grant is enabled (``CANARY_RUNWARE_FIRST_ENABLED``), new
Sunburst work uses a separate identity that tries Runware before that chain.
Runware falls back only when its attempt definitely did not run (Runware
reports explicit task errors and does not bill failed tasks). A Runware attempt
with an unknown outcome stops: its result may still be recoverable, so it is
never resubmitted elsewhere.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from novel_to_comic.image_models import (
    GATEWAY_IMAGE_SUNBURST_OPENAI,
    GATEWAY_IMAGE_SUNBURST_RUNWARE,
    IMAGE_PROVIDER_OPENAI_FAL,
    IMAGE_PROVIDER_RUNWARE_OPENAI_FAL,
)

logger = logging.getLogger(__name__)

#: Provider key of the multi-route Sunburst identity. Frozen into Draw
#: profiles and non-panel wires; the route order is part of that identity.
SUNBURST_FALLBACK_PROVIDER = IMAGE_PROVIDER_OPENAI_FAL
#: Gateway deployments for each route. ``image-sunburst`` stays the FAL
#: deployment so retained FAL editions and frozen FAL wires keep their route.
OPENAI_SUNBURST_GATEWAY_MODEL = GATEWAY_IMAGE_SUNBURST_OPENAI
FAL_SUNBURST_GATEWAY_MODEL = "image-sunburst"
#: Runware first, then the whole OpenAI-first chain above.
RUNWARE_FIRST_PROVIDER = IMAGE_PROVIDER_RUNWARE_OPENAI_FAL
RUNWARE_SUNBURST_GATEWAY_MODEL = GATEWAY_IMAGE_SUNBURST_RUNWARE

Surface = Literal["draw", "asset"]
T = TypeVar("T")

# The streaming OpenAI gateway handler tags failures with the phase they
# happened in; the proxy wraps them in a generic HTTP 500, keeping the message.
_OPENAI_IMAGE_PHASE = re.compile(
    r"OpenAI image (?P<phase>[a-z_]+) failed for [\w./-]+(?:; upstream_status=(?P<status>\d{3}))?"
)
# OpenAI's safety refusal codes. A refusal can arrive before acceptance (a
# submit 400) or inside an accepted event stream; either way it is the
# request's fault, never a lost result. The redacting wire transport copies the
# code as ``openai_block`` so it survives without the provider message.
_OPENAI_IMAGE_BLOCK = re.compile(
    r'(?:\bcode=|"openai_block": ")(?P<code>moderation_blocked|content_policy_violation)\b'
)
# Set by the non-panel wire transport when the gateway itself was unreachable.
_GATEWAY_UNREACHABLE_MARKER = "gateway connection could not be established"
# Failures after which OpenAI cannot have charged for the attempt.
UNCHARGED_REASONS = frozenset({"gateway_unreachable", "not_submitted", "capacity", "credentials"})
# The Runware gateway handler's phase-tagged failures (``runware_provider``).
_RUNWARE_IMAGE_PHASE = re.compile(
    r"Runware image (?P<phase>[a-z_]+) failed for [\w./-]+(?:; upstream_status=(?P<status>\d{3}))?"
)


def openai_image_failure_marker(message: str) -> str | None:
    """The bounded, prompt-free phase marker inside a gateway error message."""
    match = _OPENAI_IMAGE_PHASE.search(message)
    return match.group(0) if match else None


def openai_image_block_code(message: str) -> str | None:
    """OpenAI's safety refusal code inside a gateway error message, if any."""
    match = _OPENAI_IMAGE_BLOCK.search(message)
    return match["code"] if match else None


def classify_openai_image_failure(exc: BaseException) -> str | None:
    """Why a failed OpenAI attempt may fall back to FAL, or None to stop.

    Stops on refusals, invalid requests, cancellation, and completed output
    that failed validation: another provider would not fix those.
    """
    import httpx
    from novel_to_comic.ai.errors import AITransportError

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return "gateway_unreachable"
    if not isinstance(exc, AITransportError):
        return None
    if exc.phase == "ambiguous_submission":
        return "unknown_outcome"
    if exc.phase != "gateway_request":
        return None
    if openai_image_block_code(str(exc)):
        return None
    match = _OPENAI_IMAGE_PHASE.search(str(exc))
    if match is None:
        if _GATEWAY_UNREACHABLE_MARKER in str(exc):
            return "gateway_unreachable"
        status = exc.response.status_code if exc.response is not None else None
        return "unknown_outcome" if status is not None and status >= 500 else None
    phase, status = match["phase"], int(match["status"]) if match["status"] else None
    if phase == "submit_connect":
        return "not_submitted"
    if phase == "submit":
        if status in {429, 503}:
            return "capacity"
        if status in {401, 403}:
            return "credentials"
        # 400/404/413/422 (including moderation) are the request's fault.
        return "unknown_outcome" if status is not None and status >= 500 else None
    if phase in {"submit_transport", "stream", "result"}:
        return "unknown_outcome"
    return None


def runware_image_failure_marker(message: str) -> str | None:
    """The bounded, prompt-free phase marker of a Runware gateway error."""
    match = _RUNWARE_IMAGE_PHASE.search(message)
    return match.group(0) if match else None


def classify_runware_image_failure(exc: BaseException) -> str | None:
    """Why a failed Runware attempt may move on to OpenAI, or None to stop.

    Every reason is a definite outcome without a charge: the task never
    reached Runware, or Runware answered it with an explicit error (failed
    tasks are not billed). Stops on the request's own faults, which another
    provider of the same model would repeat, and on any unknown outcome.
    """
    import httpx
    from novel_to_comic.ai.errors import AITransportError

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return "gateway_unreachable"
    if not isinstance(exc, AITransportError) or exc.phase != "gateway_request":
        return None
    match = _RUNWARE_IMAGE_PHASE.search(str(exc))
    if match is None:
        return "gateway_unreachable" if _GATEWAY_UNREACHABLE_MARKER in str(exc) else None
    phase, status = match["phase"], int(match["status"]) if match["status"] else None
    if phase in {"upload", "submit_connect"}:
        return "not_submitted"
    if phase != "submit":
        # request_validation, unknown_outcome and result stop here.
        return None
    if status == 402:
        return "credits"
    if status in {401, 403}:
        return "credentials"
    if status in {429, 503}:
        return "capacity"
    if status is None or status >= 500:
        # An explicit task error (including one found by recovery) or a
        # Runware/provider server error: definite, and not billed.
        return "provider_error"
    return None


class RouteCircuit:
    """Skip a route after repeated failures, bounding paid double attempts.

    Process-local: each worker learns independently, and a restart retries.
    Shared by every Sunburst surface, since they use the same OpenAI route.
    """

    def __init__(self, *, threshold: int = 3, cooldown_seconds: float = 900.0,
                 route: str = "openai", next_route: str = "FAL") -> None:
        self._route = route
        self._next_route = next_route
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._open_until = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = time.monotonic() + self._cooldown
            self._failures = 0
            logger.error("%s Sunburst route disabled for %.0fs after %d consecutive failures; "
                         "images go straight to %s", self._route, self._cooldown, self._threshold,
                         self._next_route)
            increment_metric("canary_image_route_circuit_opened_total", route=self._route)

    def reset(self) -> None:
        self._failures = 0
        self._open_until = 0.0


OPENAI_SUNBURST_CIRCUIT = RouteCircuit()
#: A spent grant answers every task with 402; skip Runware instead of paying
#: a gateway round trip per image until the cooldown ends.
RUNWARE_CIRCUIT = RouteCircuit(route="runware", next_route="OpenAI")


def increment_metric(name: str, **labels: str) -> None:
    try:
        from novel_to_comic.server.metrics import increment

        increment(name, 1.0, **labels)
    except Exception:
        pass


async def run_openai_first(
    *,
    primary: Callable[[], Awaitable[T]],
    backup: Callable[[], Awaitable[T]],
    surface: Surface,
    request_key: str,
    estimate_openai_usd: Callable[[], float],
) -> tuple[T, str, dict[str, object] | None]:
    """Run ``primary`` (OpenAI), falling back once to ``backup`` (FAL).

    Returns the result, the route that produced it, and fallback evidence for
    provenance (``None`` when OpenAI succeeded).
    """
    from novel_to_comic.server.telemetry import ai_span

    with ai_span("image_route", surface=surface) as span:
        result, route, fallback = await _run_openai_first(
            primary=primary, backup=backup, surface=surface, request_key=request_key,
            estimate_openai_usd=estimate_openai_usd,
        )
        # The absorbed attempt keeps its own generation in the tree.
        span.set(route=route, fallback_reason=(fallback or {}).get("reason"))
        return result, route, fallback


async def _run_openai_first(
    *,
    primary: Callable[[], Awaitable[T]],
    backup: Callable[[], Awaitable[T]],
    surface: Surface,
    request_key: str,
    estimate_openai_usd: Callable[[], float],
) -> tuple[T, str, dict[str, object] | None]:
    if OPENAI_SUNBURST_CIRCUIT.is_open():
        increment_metric("canary_image_route_fallbacks_total", reason="circuit_open", surface=surface)
        return await backup(), "fal-queue", {"from_route": "openai", "reason": "circuit_open"}
    from novel_to_comic.ai.context import current_ai_request_context
    from novel_to_comic.server.credits import deferred_ambiguity

    with deferred_ambiguity() as scope:
        try:
            result = await primary()
        except asyncio.CancelledError:
            scope.commit()
            raise
        except Exception as exc:
            reason = classify_openai_image_failure(exc)
            if reason is None:
                scope.commit()
                raise
            failure = exc
        else:
            OPENAI_SUNBURST_CIRCUIT.record_success()
            scope.commit()
            return result, "openai", None
        absorbed_calls = list(dict.fromkeys(
            [*scope.call_ids, *filter(None, [getattr(failure, "canary_usage_event_id", None)])]
        ))
        await _release(scope)
    OPENAI_SUNBURST_CIRCUIT.record_failure()
    fallback: dict[str, object] = {"from_route": "openai", "reason": reason}
    increment_metric("canary_image_route_fallbacks_total", reason=reason, surface=surface)
    if reason not in UNCHARGED_REASONS:
        estimate = estimate_openai_usd()
        fallback.update({"absorbed_call_ids": absorbed_calls, "absorbed_estimated_cost_usd": estimate})
        increment_metric("canary_absorbed_image_attempts_total", route="openai", surface=surface)
        logger.error(
            "Absorbing OpenAI Sunburst attempt with unknown outcome; falling back to FAL "
            "surface=%s request=%s job_id=%s call_ids=%s estimated_cost_usd=%.4f error=%s",
            surface, request_key, current_ai_request_context().job_id,
            absorbed_calls, estimate, type(failure).__name__,
        )
    elif reason == "credentials":
        logger.error("OpenAI Sunburst credentials rejected; falling back to FAL surface=%s request=%s",
                     surface, request_key)
    else:
        logger.warning("OpenAI Sunburst unavailable (%s); falling back to FAL surface=%s request=%s",
                       reason, surface, request_key)
    return await backup(), "fal-queue", fallback


async def _release(scope) -> None:
    """Free the OpenAI attempt's call guarantee before the FAL attempt
    authorizes its own, so the fallback never needs two guarantees."""
    from novel_to_comic.ai.context import current_ai_request_context

    user_id = current_ai_request_context().user_id
    if not user_id or not scope.call_ids:
        scope.jobs.clear()
        scope.resolved = True
        return
    from novel_to_comic.server.db import get_db

    await asyncio.to_thread(scope.release, get_db(), user_id=user_id)


async def run_runware_first(
    *,
    primary: Callable[[], Awaitable[T]],
    backup: Callable[[], Awaitable[tuple[T, str, dict[str, object] | None]]],
    surface: Surface,
    request_key: str,
) -> tuple[T, str, dict[str, object] | None]:
    """Run ``primary`` (Runware), then ``backup`` (the OpenAI-first chain)
    only when Runware definitely did not run the task.

    Returns the result, the route that produced it, and fallback evidence for
    provenance (``None`` when Runware succeeded). A Runware fallback keeps the
    chain's own evidence under ``then``.
    """
    from novel_to_comic.server.telemetry import ai_span

    with ai_span("image_route", surface=surface, first_route="runware") as span:
        result, route, fallback = await _run_runware_first(
            primary=primary, backup=backup, surface=surface, request_key=request_key,
        )
        span.set(route=route, fallback_reason=(fallback or {}).get("reason"))
        return result, route, fallback


async def _run_runware_first(
    *,
    primary: Callable[[], Awaitable[T]],
    backup: Callable[[], Awaitable[tuple[T, str, dict[str, object] | None]]],
    surface: Surface,
    request_key: str,
) -> tuple[T, str, dict[str, object] | None]:
    if RUNWARE_CIRCUIT.is_open():
        reason = "circuit_open"
    else:
        from novel_to_comic.server.credits import deferred_ambiguity

        with deferred_ambiguity() as scope:
            try:
                result = await primary()
            except asyncio.CancelledError:
                scope.commit()
                raise
            except Exception as exc:
                reason = classify_runware_image_failure(exc)
                if reason is None:
                    scope.commit()
                    raise
            else:
                RUNWARE_CIRCUIT.record_success()
                scope.commit()
                return result, "runware", None
            # Definite and uncharged: free its call guarantee before the
            # next route authorizes its own.
            await _release(scope)
        RUNWARE_CIRCUIT.record_failure()
        log = logger.error if reason in {"credits", "credentials"} else logger.warning
        log("Runware Sunburst unavailable (%s); falling back to OpenAI surface=%s request=%s",
            reason, surface, request_key)
    increment_metric("canary_image_route_fallbacks_total", reason=reason, surface=surface)
    result, route, then = await backup()
    fallback: dict[str, object] = {"from_route": "runware", "reason": reason}
    if then is not None:
        fallback["then"] = then
    return result, route, fallback
