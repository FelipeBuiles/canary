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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from novel_to_comic.clients.text import generate_json
from novel_to_comic.config import Config
from novel_to_comic.usage import UsageRecord

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
    retries: int = 2,
    temperatures: Sequence[float] = (0.4,),
    validate: Callable[[T], None] | None = None,
    repair: Callable[[T, Exception], T | None] | None = None,
) -> StructuredCallOutcome[T]:
    """Generate JSON, prefer deterministic repair, then re-prompt if necessary.

    Raises StructuredCallError once ``retries`` corrections are exhausted.
    """
    usage_records: list[UsageRecord] = []
    last_error: Exception | None = None
    last_parsed: T | None = None
    total_attempts = retries + 1

    for attempt in range(total_attempts):
        temperature = temperatures[min(attempt, len(temperatures) - 1)]
        api_result = await generate_json(
            config=config,
            model=model,
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            feature=feature,
        )
        try:
            from novel_to_comic.server.metrics import record_structured_attempt

            record_structured_attempt(feature=feature, retry=attempt > 0)
        except Exception:
            pass
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
            return StructuredCallOutcome(
                value=parsed_this_attempt, usage_records=usage_records, attempts=attempt + 1
            )
        except Exception as exc:
            last_error = exc
            if repair is not None and parsed_this_attempt is not None:
                try:
                    repaired = repair(parsed_this_attempt, exc)
                    if repaired is not None:
                        if validate is not None:
                            validate(repaired)
                        logger.info("%s repaired locally after attempt %d", label, attempt + 1)
                        return StructuredCallOutcome(
                            value=repaired,
                            usage_records=usage_records,
                            attempts=attempt + 1,
                        )
                except Exception:
                    logger.debug("%s local repair did not validate", label, exc_info=True)
            logger.warning(
                "%s rejected on attempt %d/%d: %s",
                label, attempt + 1, total_attempts, exc,
            )
            if attempt < total_attempts - 1:
                user_content = correction(api_result.value, exc)

    assert last_error is not None
    raise StructuredCallError(label, last_error, last_parsed, usage_records, total_attempts)
