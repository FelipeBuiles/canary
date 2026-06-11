"""Schema-validated model calls with correction-feedback retry.

The "call model → parse → validate → feed errors back → retry" loop that
stages otherwise hand-roll lives here. Callers supply a ``parse`` callable
that turns raw JSON into a typed value (raising on bad shape) and a
``correction`` callable that builds the next user message from the failed
output and its error. Temperature follows a ladder clamped at its last rung,
so a single-element ladder means a constant temperature.
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
) -> StructuredCallOutcome[T]:
    """Generate JSON and re-prompt with the validation error until it parses.

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
        if api_result.usage is not None:
            usage_records.append(api_result.usage)
        try:
            parsed = parse(api_result.value)
            last_parsed = parsed
            if validate is not None:
                validate(parsed)
            if attempt > 0:
                logger.info("%s recovered on retry %d", label, attempt)
            return StructuredCallOutcome(
                value=parsed, usage_records=usage_records, attempts=attempt + 1
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "%s rejected on attempt %d/%d: %s",
                label, attempt + 1, total_attempts, exc,
            )
            if attempt < total_attempts - 1:
                user_content = correction(api_result.value, exc)

    assert last_error is not None
    raise StructuredCallError(label, last_error, last_parsed, usage_records, total_attempts)
