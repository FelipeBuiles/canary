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
from novel_to_comic.clients.validated_call import RetryPolicy, ValidatedCall
from novel_to_comic.text_models import TextModelJob
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
    job: TextModelJob | None = None,
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
    from novel_to_comic.ai.errors import AIStructuredResponseError

    if not temperatures:
        raise ValueError("A structured call needs at least one temperature")
    usage_records: list[UsageRecord] = []
    last_error: Exception | None = None
    last_parsed: T | None = None
    current_parsed: T | None = None
    attempts = 0

    def observe(result):
        usage_records.extend(result.additional_usage)
        if result.usage is not None:
            usage_records.append(result.usage)

    def parse_candidate(raw):
        nonlocal last_parsed, current_parsed, last_error
        current_parsed = None
        try:
            current_parsed = parse(raw)
            last_parsed = current_parsed
            if validate is not None:
                validate(current_parsed)
            return current_parsed
        except Exception as error:
            last_error = error
            raise

    def repair_candidate(raw, error):
        if repair is not None and current_parsed is not None:
            try:
                value = repair(current_parsed, error)
                if value is not None:
                    if validate is not None:
                        validate(value)
                    return value
            except Exception:
                logger.debug("%s local repair did not validate", label, exc_info=True)
        return None

    def rejected(request, raw, error):
        action = "retrying" if attempts < retries + 1 else "no retries left"
        logger.warning("%s attempt %d/%d rejected; %s: %s", label, attempts,
                       retries + 1, action, validation_error_summary(error))

    def prepare(request, attempt):
        nonlocal attempts
        attempts = attempt
        return {**request, "temperature": temperatures[min(attempt - 1, len(temperatures) - 1)]}

    try:
        outcome = await ValidatedCall(
            job or TextModelJob.for_feature(feature, model),
            RetryPolicy(retries + 1, (Exception,)), parse_candidate, correction,
            repair=repair_candidate if repair is not None else None,
        ).run(generate or generate_json, dict(
            config=config, model=model, system_prompt=system_prompt,
            user_content=user_content, max_output_tokens=max_output_tokens, feature=feature,
            **({"json_schema": json_schema} if json_schema is not None else {}),
        ), observe=observe, prepare_attempt=prepare, rejected=rejected)
    except AIStructuredResponseError as error:
        raise AIStructuredResponseError(
            str(error), usage_records=(*usage_records, *error.usage_records),
        ) from error
    except Exception as error:
        if error is not last_error:
            raise
        raise StructuredCallError(label, error, last_parsed, usage_records, attempts) from error
    return StructuredCallOutcome(outcome.value, usage_records, outcome.attempts)
