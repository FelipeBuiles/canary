"""Native TypeSafe Choice transport and opt-in, abstaining classifier cascade.

Not a chat/completions adapter. No hidden retries, model substitution, global
client, raw-text logs, project-config credentials, or automatic paid fallback.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import Field, StrictInt, model_validator

from novel_to_comic.decision_models import (
    ChoiceAnswer, ChoiceQuestion, DecisionCase, DecisionModel, DecisionPolicy,
    RUBRIC_VERSION, canonical_json, content_digest, eligibility_reason, question_for,
)
from novel_to_comic.usage import ApiResult, UsageRecord

ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class TypeSafeSettings(DecisionModel):
    # Configuration, not a price/latency guarantee. See dated research reference.
    model: str = Field(default="jev-1.13.0", pattern=r"^jev-\d+\.\d+\.\d+$")
    pricing_model: str = "jev-1.13.0"
    input_usd_per_million: float = Field(default=0.042, ge=0, allow_inf_nan=False)
    output_usd_per_million: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    deadline_seconds: float = Field(default=2.0, gt=0, le=120, allow_inf_nan=False)
    concurrency: int = Field(default=2, ge=1, le=8)
    # Conservative application byte bound, NOT a claim to have Jev's tokenizer.
    # It applies to the entire serialized request (including all rubrics).
    max_request_bytes: int = Field(default=24000, ge=1000, le=24000)
    max_response_bytes: int = Field(default=128000, ge=1000, le=256000)


    @model_validator(mode="after")
    def explicit_price_identity(self):
        if self.pricing_model != self.model:
            raise ValueError("changing model requires an explicit matching pricing_model and reviewed rates")
        return self


class TokenUsage(DecisionModel):
    input_tokens: StrictInt = Field(ge=0)
    output_tokens: StrictInt = Field(ge=0)


class DecisionObservation(DecisionModel):
    request_sha256: str
    requested_model: str
    resolved_model: str | None = None
    rubric_version: str = RUBRIC_VERSION
    answers: dict[str, ChoiceAnswer] = Field(default_factory=dict)
    usage: UsageRecord | None = None
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)
    attempted: bool = False
    reason: str | None = None


def strict_json(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-finite JSON number")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def request_body(state: dict, questions: dict[str, ChoiceQuestion], model: str) -> dict:
    return {"model": model, "state": state,
            "questions": {key: value.model_dump() for key, value in questions.items()}}


def case_request(case: DecisionCase, settings: TypeSafeSettings) -> dict:
    # Labels, group, ID and language metadata are deliberately excluded: no gold leakage.
    return request_body(case.state, {"decision": question_for(case.task)}, settings.model)


class TypeSafeDecisionClient:
    """One reusable HTTP pool and concurrency limiter per evaluation run.

    Inject an HTTP client for tests. The owner closes the injected client.
    Credentials are sent only to ENDPOINT; redirects are never followed.
    """
    def __init__(self, *, api_key: str, settings: TypeSafeSettings,
                 http_client: httpx.AsyncClient):
        if not api_key.strip():
            raise ValueError("a TypeSafe API key is required for an explicit live run")
        self.settings = settings
        self._key = api_key
        self._http = http_client
        self._semaphore = asyncio.Semaphore(settings.concurrency)

    async def evaluate(self, *, state: dict,
                       questions: dict[str, ChoiceQuestion]) -> DecisionObservation:
        body = request_body(state, questions, self.settings.model)
        wire = canonical_json(body).encode("utf-8")
        digest = content_digest(body)
        start = time.monotonic()
        attempted = False
        usage = None
        resolved_model = None

        def observation(reason=None, answers=None):
            return DecisionObservation(
                request_sha256=digest, requested_model=self.settings.model,
                resolved_model=resolved_model, answers=answers or {}, usage=usage,
                elapsed_ms=(time.monotonic() - start) * 1000,
                attempted=attempted, reason=reason,
            )

        if not 1 <= len(questions) <= 16 or any(not key for key in questions):
            return observation("invalid_questions")
        if len(wire) > self.settings.max_request_bytes:
            return observation("context_too_large")
        try:
            # Includes queue wait and response-body read, not just socket inactivity.
            async with asyncio.timeout(self.settings.deadline_seconds):
                async with self._semaphore:
                    attempted = True
                    async with self._http.stream(
                        "POST", ENDPOINT, content=wire, follow_redirects=False,
                        headers={"Authorization": f"Bearer {self._key}",
                                 "Content-Type": "application/json"},
                        timeout=self.settings.deadline_seconds,
                    ) as response:
                        chunks = bytearray()
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > self.settings.max_response_bytes:
                                return observation("response_too_large")
                        # Capture usage BEFORE checking status/answer protocol so a
                        # malformed answer or billable error cannot erase known spend.
                        try:
                            raw = strict_json(chunks.decode("utf-8"))
                        except (ValueError, UnicodeError):
                            return observation(f"http_{response.status_code}" if response.is_error
                                               else "invalid_response")
                        if not isinstance(raw, dict):
                            return observation("invalid_response")
                        resolved_model = raw.get("model") if isinstance(raw.get("model"), str) else None
                        if isinstance(raw.get("usage"), dict):
                            try:
                                tokens = TokenUsage.model_validate(raw["usage"])
                            except ValueError:
                                tokens = None
                            if tokens is not None:
                                price_known = resolved_model == self.settings.model
                                cost = (tokens.input_tokens * self.settings.input_usd_per_million
                                        + tokens.output_tokens * self.settings.output_usd_per_million) / 1e6
                                usage = UsageRecord(
                                    provider="typesafe", model=self.settings.model,
                                    provider_model=resolved_model, operation="text",
                                    input_tokens=tokens.input_tokens, output_tokens=tokens.output_tokens,
                                    cost_usd=cost if price_known else None,
                                    cost_source="configured_typesafe_rate" if price_known else "unknown_model_price",
                                )
                        if not response.is_success:
                            return observation(f"http_{response.status_code}")
                        if resolved_model != self.settings.model:
                            return observation("model_mismatch")
                        if usage is None:
                            return observation("missing_usage")
                        answers = raw.get("answers")
                        if not isinstance(answers, dict) or set(answers) != set(questions):
                            return observation("answer_ids_mismatch")
                        parsed = {key: ChoiceAnswer.model_validate(value) for key, value in answers.items()}
                        if any(set(parsed[key].probabilities) != set(question["criteria"])
                               for key, question in body["questions"].items()):
                            return observation("labels_mismatch")
                        return observation(answers=parsed)
        except (TimeoutError, httpx.TimeoutException):
            return observation("timeout")
        except httpx.HTTPError:
            return observation("transport_error")
        except ValueError:
            return observation("invalid_response")
        # CancelledError intentionally propagates; caller cancellation is not a fallback trigger.


async def decide_case(case: DecisionCase, *, client: TypeSafeDecisionClient,
                      policy: DecisionPolicy,
                      fallback: Callable[[], Awaitable[ApiResult[str]]] | None = None) -> ApiResult[str | None]:
    """Return a narrow accepted label, or abstain/use the explicitly supplied fallback.

    This is not wired into paid stage execution. A future caller must reserve
    BOTH providers, record every returned usage, and retain its own authority gates.
    """
    ineligible = eligibility_reason(case)
    if ineligible:
        observed = DecisionObservation(
            request_sha256=content_digest(case_request(case, client.settings)),
            requested_model=client.settings.model, elapsed_ms=0,
            reason=ineligible,
        )
    else:
        observed = await client.evaluate(state=case.state, questions={"decision": question_for(case.task)})
    answer = observed.answers.get("decision")
    accepted = (observed.reason is None and answer is not None
                and policy.accepts(case.task, answer, model=observed.resolved_model or "", language=case.language))
    metadata = {"decision_observation": observed.model_dump(mode="json"),
                "route": "typesafe" if accepted else "abstain"}
    if accepted:
        return ApiResult(answer.choice, usage=observed.usage, response_metadata=metadata)
    if fallback is None:
        return ApiResult(None, usage=observed.usage, response_metadata=metadata)
    try:
        result = await fallback()
    except Exception as error:
        # A caller can record these via StageRuntime even when the authoritative
        # fallback fails. Do not swallow cancellation or disguise it as success.
        raise DecisionFallbackError(observed, error) from error
    # Do not invent natural-language rationale or a fallback score.
    metadata["route"] = "fallback"
    metadata["fallback_label_valid"] = result.value in question_for(case.task).criteria
    return ApiResult(
        result.value if metadata["fallback_label_valid"] else None,
        usage=result.usage,
        additional_usage=(*((observed.usage,) if observed.usage else ()), *result.additional_usage),
        provider_request_id=result.provider_request_id,
        actual_provider_model=result.actual_provider_model,
        response_metadata={**(result.response_metadata or {}), **metadata},
    )


class DecisionFallbackError(RuntimeError):
    """Preserve the primary receipt when an explicitly requested fallback raises."""
    def __init__(self, observation: DecisionObservation, error: Exception):
        super().__init__("authoritative decision fallback failed")
        self.observation = observation
        self.usage_records = (
            *((observation.usage,) if observation.usage else ()),
            *getattr(error, "usage_records", ()),
        )
