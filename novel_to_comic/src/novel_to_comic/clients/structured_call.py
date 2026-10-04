"""Schema-validated model calls with correction-feedback retry.

The "call model → parse → validate → repair locally or retry" loop that stages
otherwise hand-roll lives here. Callers supply a ``parse`` callable that turns
raw JSON into a typed value (raising on bad shape), an optional deterministic
``repair`` callable, and a ``correction`` callable that builds the next user
message from the failed output and its error. Temperature follows a ladder
clamped at its last rung, so a single-element ladder means a constant
temperature.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import ValidationError

from novel_to_comic.clients.text import generate_json
from novel_to_comic.config import Config
from novel_to_comic.usage import ApiResult, UsageRecord

T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class StructuredCallOutcome(Generic[T]):
    """A validated value plus the usage of every attempt that led to it."""

    value: T
    usage_records: list[UsageRecord]
    attempts: int


class StructuredCallError(Exception):
    """Every attempt failed.

    ``last_parsed`` is the most recent value that survived ``parse`` (it
    failed only ``validate``), letting callers run a deterministic fallback
    on structurally-sound-but-invalid output. None if parsing never succeeded.
    """

    def __init__(
        self,
        label: str,
        last_error: Exception,
        last_parsed: Any,
        usage_records: list[UsageRecord],
        attempts: int,
    ) -> None:
        super().__init__(f"{label} failed after {attempts} attempt(s): {last_error}")
        self.last_error = last_error
        self.last_parsed = last_parsed
        self.usage_records = usage_records
        self.attempts = attempts


def validation_error_summary(error: Exception) -> str:
    """Keep recoverable model-shape failures readable in operator logs."""

    if not isinstance(error, ValidationError):
        return " ".join(str(error).split())

    grouped: dict[tuple[tuple[object, ...], str], list[object]] = {}
    standalone: list[tuple[tuple[object, ...], str]] = []
    for item in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location = tuple(item["loc"])
        message = str(item["msg"])
        if location and isinstance(location[-1], int):
            grouped.setdefault((location[:-1], message), []).append(location[-1])
        else:
            standalone.append((location, message))

    summaries: list[str] = []
    for (prefix, message), indexes in grouped.items():
        path = ".".join(str(part) for part in prefix)
        suffix = ", ".join(str(index) for index in indexes)
        summaries.append(f"{path}[{suffix}]: {message}")
    for location, message in standalone:
        path = ".".join(str(part) for part in location) or "response"
        summaries.append(f"{path}: {message}")

    visible = summaries[:3]
    if len(summaries) > len(visible):
        visible.append(f"+{len(summaries) - len(visible)} more")
    return "; ".join(visible)


async def generate_validated_json(
    config: Config,
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    parse: Callable[[Any], T],
    correction: Callable[[Any, Exception], str],
    label: str,
    feature: str,
    max_output_tokens: int | None = None,
    json_schema: dict | None = None,
    retries: int = 2,
    temperatures: Sequence[float] = (0.4,),
    validate: Callable[[T], None] | None = None,
    repair: Callable[[T, Exception], T | None] | None = None,
    generate: Callable[..., Awaitable[ApiResult[Any]]] | None = None,
) -> StructuredCallOutcome[T]:
    """Generate JSON, prefer deterministic repair, then re-prompt if necessary.

    Raises StructuredCallError once ``retries`` corrections are exhausted.
    """
    from novel_to_comic.server.telemetry import ai_span, observation_context

    usage_records: list[UsageRecord] = []
    last_error: Exception | None = None
    last_parsed: T | None = None
    total_attempts = retries + 1

    # Telemetry tree: one span per call, one per attempt, so a provider
    # success that failed validation or needed local repair stays visible.
    with ai_span(f"structured.{feature}", feature=feature) as call_span:
        for attempt in range(total_attempts):
            temperature = temperatures[min(attempt, len(temperatures) - 1)]
            from novel_to_comic.ai.errors import AIStructuredResponseError
            with ai_span("attempt", attempt_number=attempt + 1) as attempt_span, \
                    observation_context(attempt_number=attempt + 1):
                try:
                    api_result = await (generate or generate_json)(
                        config=config,
                        model=model,
                        system_prompt=system_prompt,
                        user_content=user_content,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        feature=feature,
                        **({"json_schema": json_schema} if json_schema is not None else {}),
                    )
                except AIStructuredResponseError as exc:
                    attempt_span.set(outcome="unparseable")
                    call_span.set(outcome="failed", status="failed", attempts=attempt + 1)
                    raise AIStructuredResponseError(
                        str(exc), usage_records=(*usage_records, *exc.usage_records),
                    ) from exc
                try:
                    from novel_to_comic.server.metrics import record_structured_attempt

                    record_structured_attempt(feature=feature, retry=attempt > 0)
                except Exception:
                    pass
                usage_records.extend(api_result.additional_usage)
                if api_result.usage is not None:
                    usage_records.append(api_result.usage)
                parsed_this_attempt: T | None = None
                try:
                    parsed_this_attempt = parse(api_result.value)
                    last_parsed = parsed_this_attempt
                    if validate is not None:
                        validate(parsed_this_attempt)
                    if attempt > 0:
                        logger.info("%s recovered on retry %d", label, attempt)
                    attempt_span.set(outcome="accepted")
                    call_span.set(outcome="accepted" if attempt == 0 else "accepted_after_retry",
                                  attempts=attempt + 1)
                    return StructuredCallOutcome(
                        value=parsed_this_attempt, usage_records=usage_records, attempts=attempt + 1
                    )
                except Exception as exc:
                    last_error = exc
                    attempt_span.set(outcome="rejected", error_type=type(exc).__name__,
                                     validation_error_count=(exc.error_count()
                                                             if isinstance(exc, ValidationError) else None))
                    if repair is not None and parsed_this_attempt is not None:
                        try:
                            repaired = repair(parsed_this_attempt, exc)
                            if repaired is not None:
                                if validate is not None:
                                    validate(repaired)
                                logger.info("%s repaired locally after attempt %d", label, attempt + 1)
                                attempt_span.set(outcome="repaired")
                                call_span.set(outcome="repaired", attempts=attempt + 1)
                                return StructuredCallOutcome(
                                    value=repaired,
                                    usage_records=usage_records,
                                    attempts=attempt + 1,
                                )
                        except Exception:
                            logger.debug("%s local repair did not validate", label, exc_info=True)
                    action = "retrying" if attempt < total_attempts - 1 else "no retries left"
                    logger.warning(
                        "%s attempt %d/%d rejected; %s: %s",
                        label,
                        attempt + 1,
                        total_attempts,
                        action,
                        validation_error_summary(exc),
                    )
                    if attempt < total_attempts - 1:
                        user_content = correction(api_result.value, exc)
        call_span.set(outcome="failed", status="failed", attempts=total_attempts)

    assert last_error is not None
    raise StructuredCallError(label, last_error, last_parsed, usage_records, total_attempts)
