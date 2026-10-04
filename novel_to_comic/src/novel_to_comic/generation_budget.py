"""Persistent admission limits for Adapt/Plan text work, including explicit resumes.

A submission limit bounds amplification, not the price of an individual call.
Reserve before awaiting the provider; failed, cancelled and ambiguous work all
consume a slot. Completed checkpoints bypass this wrapper and consume none.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.ai.context import execution_observer
from novel_to_comic.gemini_tuning import tuned_request
from novel_to_comic.usage import calculate_cost_breakdown


class GenerationWorkLimitError(RuntimeError):
    """No more calls are admitted for these unchanged stage inputs."""


class GenerationCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    request_sha256: str
    feature: str
    model: str
    admitted_at: str
    # When the provider began executing. Serialized transports queue admitted
    # calls, so admitted-but-not-started is waiting, not in flight.
    started_at: str | None = None
    status: Literal["admitted", "completed", "unresolved"] = "admitted"
    finished_at: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    accounted_cost_usd: float | None = None
    cost_source: str | None = None
    funding: str | None = None


class GenerationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    lineage: str
    limit: int = Field(ge=1)
    calls: list[GenerationCall] = Field(default_factory=list)


def generation_lineage(inputs) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode()).hexdigest()


def budgeted_generator(generate, *, artifacts, stage, model, inputs, max_calls, override_limit=False):
    """Limit structured requests across models and resumptions of the same work.

    The identity deliberately excludes model and attempt timestamps. Changing
    source, approved intent or stage authorities creates different work. Only an
    explicit configured limit can raise the baseline-derived default ceiling.
    """
    lineage = generation_lineage(inputs)
    path = artifacts.generation_budget_path(stage, lineage)

    def update(mutate):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            budget = (artifacts.read_generation_budget(stage, lineage) if path.exists()
                      else GenerationBudget(lineage=lineage, limit=max_calls))
            if budget.version != 1 or budget.lineage != lineage:
                raise ValueError("Generation budget is incompatible; inspect the saved work before continuing.")
            # A configured change is explicit; ordinary resume keeps the same
            # computed limit and can never reset the already admitted call count.
            if override_limit:
                budget.limit = max_calls
            mutate(budget)
            artifacts.write_generation_budget(stage, lineage, budget)

    async def run(**request):
        call = GenerationCall(
            id=uuid4().hex, model=model, feature=request.get("feature", stage),
            request_sha256=hashlib.sha256(json.dumps(tuned_request(model, request), sort_keys=True,
                                                    ensure_ascii=False).encode()).hexdigest(),
            admitted_at=datetime.now(timezone.utc).isoformat(),
        )

        def admit(budget):
            if len(budget.calls) >= budget.limit:
                raise GenerationWorkLimitError(
                    f"{stage.title()} stopped at its cumulative limit of {budget.limit} structured requests "
                    "for these inputs. Completed work is saved. Resume cannot reset this limit. "
                    "Review the remaining findings before explicitly increasing the work limit."
                )
            budget.calls.append(call)

        update(admit)

        def started():
            if call.started_at is None:
                call.started_at = datetime.now(timezone.utc).isoformat()
                update(lambda budget: _replace_call(budget, call))

        try:
            with execution_observer(started):
                result = await generate(**request)
        except BaseException:
            # No replacement submission. Without a completed result, usage and
            # provider outcome may be unknown; admission still consumes a slot.
            call.status = "unresolved"
            call.finished_at = datetime.now(timezone.utc).isoformat()
            update(lambda budget: _replace_call(budget, call))
            raise
        call.status = "completed"
        call.finished_at = datetime.now(timezone.utc).isoformat()
        usages = [u for u in (result.usage, *result.additional_usage) if u is not None]
        if usages:
            call.input_tokens = sum(u.input_tokens for u in usages)
            call.output_tokens = sum(u.output_tokens for u in usages)
            call.funding = usages[0].funding
            costs = [calculate_cost_breakdown(u) for u in usages]
            call.accounted_cost_usd = (sum(c.cost_usd for c in costs)
                                       if all(c.cost_usd is not None for c in costs) else None)
            call.cost_source = "+".join(dict.fromkeys(c.source for c in costs))
        update(lambda budget: _replace_call(budget, call))
        return result

    return run


def _replace_call(budget, call):
    for index, previous in enumerate(budget.calls):
        if previous.id == call.id:
            budget.calls[index] = call
            return
    raise ValueError("Generation admission disappeared; inspect the saved budget.")
