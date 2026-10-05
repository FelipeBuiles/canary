"""Credit reservation, model usage debits, and release against the Supabase ledger."""

from __future__ import annotations

import logging
import math
import os
import time
import uuid as uuid_lib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Event, Thread
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Literal, TypedDict

from fastapi import HTTPException
from supabase import Client
from postgrest.exceptions import APIError

from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.state import PipelineState
from novel_to_comic.codex_dev import Funding, classify_operations, is_subscription
from .codex_admission import (
    cast_asset_operations, image_operations, is_canonical_sheet_regen, prompt_image_operations,
    stage_operations, visual_review_operations,
)
from novel_to_comic.usage import (
    UsageRecord,
    calculate_cost,
    calculate_cost_breakdown,
    estimate_image_cost,
    estimate_text_cost,
    usage_has_billable_activity,
)

CostConfidence = Literal["low_variance", "usually_within_estimate", "variable"]

# Instructions are capped at 500 characters, but Cast text preprocessing also
# includes system rules and serialized asset context.
INSTRUCTION_REWRITE_INPUT_CHARS = 32_000
INSTRUCTION_REWRITE_OUTPUT_CHARS = 16_384
INSTRUCTION_TEXT_CALLS_BY_STAGE: dict[Literal["cast"], int] = {
    "cast": 1,
}

log = logging.getLogger("canary.credits")

RESERVATION_LEASE_SECONDS = 3600
_reservation_owner = str(uuid_lib.uuid4())
_lease_stop = Event()
_lease_thread: Thread | None = None
_reservation_jobs: dict[str, str] = {}
_unsettled_jobs: set[str] = set()
_lease_last_success: float | None = None


def reservation_leases_healthy() -> bool:
    """Recent success of the existing lease manager, not another lease owner."""
    return _lease_last_success is not None and time.monotonic() - _lease_last_success < 90


@dataclass
class DeferredAmbiguity:
    """Ambiguity and call guarantees from one attempt, held for a decision.

    The Draw fallback coordinator decides after an attempt fails whether Canary
    absorbs it (``release``) or the job keeps today's retained hold. Leaving the
    scope unresolved commits, so an unhandled path can never lose a hold.
    """

    jobs: set[str] = field(default_factory=set)
    call_ids: list[str] = field(default_factory=list)
    resolved: bool = False

    def release(self, db: Client, *, user_id: str) -> None:
        """Free this attempt's call guarantees; the user is not charged for it."""
        for call_id in self.call_ids:
            release_model_call_authorization(db, user_id=user_id, call_id=call_id)
        self.jobs.clear()
        self.resolved = True

    def commit(self) -> None:
        _unsettled_jobs.update(self.jobs)
        self.resolved = True


_deferred_ambiguity: ContextVar[DeferredAmbiguity | None] = ContextVar("canary_deferred_ambiguity", default=None)


@contextmanager
def deferred_ambiguity() -> Iterator[DeferredAmbiguity]:
    scope = DeferredAmbiguity()
    token = _deferred_ambiguity.set(scope)
    try:
        yield scope
    finally:
        _deferred_ambiguity.reset(token)
        if not scope.resolved:
            scope.commit()


def retain_ambiguous_job(job_id: str | None) -> None:
    """Retain the authoritative hold when submission or settlement is unknown."""
    if job_id:
        scope = _deferred_ambiguity.get()
        (scope.jobs if scope is not None else _unsettled_jobs).add(job_id)


def is_ambiguous_job(job_id: str | None) -> bool:
    scope = _deferred_ambiguity.get()
    return job_id is not None and (job_id in _unsettled_jobs or (scope is not None and job_id in scope.jobs))


def start_reservation_leases(db: Client) -> None:
    """Fail startup closed on missing lease migration, then renew owned holds."""
    global _lease_thread
    if _lease_thread is not None and _lease_thread.is_alive():
        return
    renew_reservation_leases(db)
    _lease_stop.clear()

    def heartbeat() -> None:
        while not _lease_stop.wait(30):
            try:
                renew_reservation_leases(db)
            except Exception:
                log.exception("Reservation lease renewal failed; expired work cannot start")

    _lease_thread = Thread(target=heartbeat, name="credit-reservation-leases", daemon=True)
    _lease_thread.start()


def stop_reservation_leases() -> None:
    """Stop only after work has drained; outstanding holds expire, never mass-release."""
    global _lease_thread
    _lease_stop.set()
    if _lease_thread is not None:
        _lease_thread.join(timeout=10)
        _lease_thread = None


def renew_reservation_leases(db: Client) -> None:
    global _lease_last_success
    try:
        db.rpc("renew_credit_reservation_leases", {
            "p_owner": _reservation_owner,
            "p_lease_seconds": RESERVATION_LEASE_SECONDS,
        }).execute()
    except Exception:
        _lease_last_success = None
        raise
    _lease_last_success = time.monotonic()


def assert_reservation_active(db: Client, reservation_id: str | None) -> None:
    if reservation_id is None:
        return
    result = db.rpc("check_credit_reservation_lease", {
        "p_reservation_id": reservation_id, "p_owner": _reservation_owner,
    }).execute()
    if result.data is not True:
        raise RuntimeError("Credit reservation expired or ownership was lost")


class CreditEstimate(TypedDict):
    estimate_credits: int
    reserved_credits: int | None
    reservation_multiplier: float
    confidence: CostConfidence
    funding: Funding

def credits_per_provider_usd() -> float:
    """Public credits charged per $1 of raw provider cost before markup."""
    return float(os.environ.get("PULP_CREDITS_PER_PROVIDER_USD", "100"))


def model_cost_markup() -> float:
    """Single markup multiplier for model-provider cost to public credits."""
    return float(os.environ.get("PULP_MODEL_COST_MARKUP", "1.0"))


def reservation_buffer() -> float:
    """Temporary authorization cushion. This is not part of final billing."""
    return float(os.environ.get("PULP_RESERVATION_BUFFER", "1.25"))


def provider_usd_to_credits(cost_usd: float) -> int:
    credits = (
        Decimal(str(cost_usd))
        * Decimal(str(credits_per_provider_usd()))
        * Decimal(str(model_cost_markup()))
    )
    return int(credits.to_integral_value(rounding=ROUND_CEILING))


def usage_to_credit_debit(usage: UsageRecord) -> tuple[int, float]:
    """Return (credits, monetary USD liability) for one model usage record.

    This is the only place where provider USD is converted to public credits.
    Keep purchase package math separate so margin is not applied twice.
    """
    if is_subscription(usage.funding) or usage.cost_source == "mock":
        return 0, 0.0
    cost_usd = calculate_cost(usage)
    credits = provider_usd_to_credits(cost_usd)
    if credits <= 0 and usage_has_billable_activity(usage):
        credits = 1
    return credits, cost_usd


def estimate_stage_credit_reservation(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    stage: str,
) -> int:
    """Estimate public credits to reserve for a stage from current project inputs."""
    operations = stage_operations(config, stage)
    if not operations or is_subscription(classify_operations(operations)):
        return 0
    if mock_mode_active(config):
        return 0
    cost_usd = estimate_stage_provider_cost_usd(config, project_dir, state, stage)
    base_credits = provider_usd_to_credits(cost_usd)
    if base_credits <= 0:
        # An API-funded stage still needs a hold before its first paid call.
        # Unknown call pricing is rejected again at the submission boundary.
        return 1
    return math.ceil(base_credits * reservation_buffer())


def estimate_stage_credit_cost(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    stage: str,
) -> int:
    """Unbuffered projected final cost in public credits."""
    if is_subscription(classify_operations(stage_operations(config, stage))):
        return 0
    if mock_mode_active(config):
        return 0
    cost_usd = estimate_stage_provider_cost_usd(config, project_dir, state, stage)
    return provider_usd_to_credits(cost_usd)


def stage_cost_confidence(stage: str) -> CostConfidence:
    _map: dict[str, CostConfidence] = {
        "extract": "usually_within_estimate",
        "brief": "usually_within_estimate",
        "style": "usually_within_estimate",
        "cast": "variable",
        "adapt": "variable",
        "plan": "variable",
        "draw": "variable",
        "finish": "low_variance",
    }
    return _map.get(stage, "variable")


def credit_estimate_for_provider_cost(
    cost_usd: float,
    stage: str,
    *,
    reserve: bool,
    zero_cost_estimate: int = 0,
    funding: Funding = "api",
) -> CreditEstimate:
    """Build the canonical CreditEstimate for one provider-cost figure.

    ``reserve=False`` is for fire-and-forget Generation jobs (no hold is
    placed, so reserved_credits is None). ``zero_cost_estimate`` floors the
    estimate when the provider cost can't be computed — regen estimates floor
    to 1 so the pre-check still runs.
    """
    estimate = (
        0 if is_subscription(funding)
        else max(1, provider_usd_to_credits(cost_usd)) if cost_usd > 0 else zero_cost_estimate
    )
    multiplier = reservation_buffer()
    if reserve or is_subscription(funding):
        reserved: int | None = math.ceil(estimate * multiplier) if estimate > 0 else 0
    else:
        reserved = None
    return CreditEstimate(
        estimate_credits=estimate,
        reserved_credits=reserved,
        reservation_multiplier=multiplier,
        confidence=stage_cost_confidence(stage),
        funding=funding,
    )


def estimate_adaptation_restart(config: Config, project_dir: Path, state: PipelineState) -> CreditEstimate:
    """Quote a new Adapt attempt, without credit for saved drafts or responses.

    Plan is estimated separately once the replacement script exists.
    """
    from novel_to_comic.stages.s4_adapt import estimate_cost

    funding = classify_operations(stage_operations(config, "adapt"))
    cost = 0.0 if mock_mode_active(config) or is_subscription(funding) else estimate_cost(
        config, project_dir, state, fresh=True,
    )
    return credit_estimate_for_provider_cost(cost, "adapt", reserve=True, funding=funding)


def estimate_stage_credit_breakdown(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    stage: str,
) -> CreditEstimate:
    """Full cost breakdown: estimate, reservation, multiplier, and confidence."""
    multiplier = reservation_buffer()
    estimate = estimate_stage_credit_cost(config, project_dir, state, stage)
    if estimate > 0:
        reserved: int | None = math.ceil(estimate * multiplier)
    else:
        reserved = 0
    return CreditEstimate(
        estimate_credits=estimate,
        reserved_credits=reserved,
        reservation_multiplier=multiplier,
        confidence=stage_cost_confidence(stage),
        funding=classify_operations(stage_operations(config, stage)),
    )


def estimate_stage_provider_cost_usd(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    stage: str,
) -> float:
    if is_subscription(classify_operations(stage_operations(config, stage))):
        return 0.0
    from novel_to_comic.stages import REGISTRY
    stage_obj = REGISTRY.get(stage)
    if stage_obj and stage_obj.estimate_cost:
        return stage_obj.estimate_cost(config, project_dir, state)
    return 0.0


class UnifiedCostResolver:
    @staticmethod
    def estimate_instructed_regen_cost(
        config: Config,
        image_estimate: CreditEstimate,
        stage: Literal["cast"],
    ) -> CreditEstimate:
        """Add the separately billed prompt rewrite to an image estimate."""
        # The image estimate may already include API work (a sheet's Character Check).
        funding = ("api" if image_estimate["funding"] == "api"
                   else classify_operations(prompt_image_operations(config)))
        if is_subscription(funding):
            return credit_estimate_for_provider_cost(0.0, stage, reserve=False, funding=funding)
        if mock_mode_active(config):
            return CreditEstimate(
                estimate_credits=0,
                reserved_credits=None,
                reservation_multiplier=reservation_buffer(),
                confidence="low_variance",
                funding=funding,
            )
        text_credits = 0
        for _ in range(INSTRUCTION_TEXT_CALLS_BY_STAGE[stage]):
            rewrite_cost_usd = estimate_text_cost(
                config.effective_prompt_model(),
                INSTRUCTION_REWRITE_INPUT_CHARS,
                output_chars=INSTRUCTION_REWRITE_OUTPUT_CHARS,
            )
            rewrite_estimate = credit_estimate_for_provider_cost(
                rewrite_cost_usd,
                stage,
                reserve=False,
                zero_cost_estimate=1,
                funding=classify_operations((("text", config.effective_prompt_model()),)),
            )
            text_credits += rewrite_estimate["estimate_credits"]
        return CreditEstimate(
            estimate_credits=(
                image_estimate["estimate_credits"]
                + text_credits
            ),
            reserved_credits=None,
            reservation_multiplier=reservation_buffer(),
            confidence="variable",
            funding=funding,
        )

    @staticmethod
    def estimate_stage_cost(
        config: Config,
        project_dir: Path,
        state: PipelineState,
        stage: str,
    ) -> CreditEstimate:
        """Estimate the credits to reserve/debit for a full stage run."""
        return estimate_stage_credit_breakdown(config, project_dir, state, stage)

    @staticmethod
    def estimate_asset_regen_cost(
        config: Config,
        project_dir: Path,
        asset_type: str,
        asset_id: str,
        additional_reference_count: int | None = None,
    ) -> CreditEstimate:
        """Estimate one cast asset redraw, plus the Character Check a sheet redraw re-runs."""
        image = UnifiedCostResolver._estimate_asset_image_cost(
            config, project_dir, asset_type, asset_id, additional_reference_count)
        if not is_canonical_sheet_regen(asset_type, asset_id) or mock_mode_active(config):
            return image
        from novel_to_comic.cast_design import estimate_review_cost
        from novel_to_comic.cast_roster import read_cast_story_bible
        review = credit_estimate_for_provider_cost(
            estimate_review_cost(config, read_cast_story_bible(project_dir)), "cast", reserve=False,
            funding=classify_operations(visual_review_operations(config)),
        )
        return CreditEstimate(
            estimate_credits=image["estimate_credits"] + review["estimate_credits"],
            reserved_credits=None,
            reservation_multiplier=reservation_buffer(),
            confidence="variable",
            funding=classify_operations(cast_asset_operations(config, asset_type, asset_id)),
        )

    @staticmethod
    def _estimate_asset_image_cost(
        config: Config,
        project_dir: Path,
        asset_type: str,
        asset_id: str,
        additional_reference_count: int | None = None,
    ) -> CreditEstimate:
        """Estimate the image call that regenerates a single cast asset."""
        funding = classify_operations(image_operations(config))
        if is_subscription(funding):
            return credit_estimate_for_provider_cost(0.0, "cast", reserve=False, funding=funding)
        if mock_mode_active(config):
            return credit_estimate_for_provider_cost(0.0, "cast", reserve=False)
        from novel_to_comic.cast_reference_inputs import saved_reference_inputs
        entity_id, _, state_id = asset_id.partition(":")
        kind_for_asset = {"character_ref_regen": "character", "location_plate_regen": "location", "prop_ref_regen": "prop"}
        if additional_reference_count is None:
            kind = kind_for_asset[asset_type]
            additional_reference_count = len(saved_reference_inputs(project_dir, kind, entity_id, state_id or None))
        ref_count = 1  # selected style authority
        if asset_type in {"character_ref_regen", "location_plate_regen"} and ":" in asset_id:
            entity_id, state_id = asset_id.split(":", 1)
            from novel_to_comic.stages.s3_cast import estimate_state_reference_count

            ref_count = estimate_state_reference_count(
                config,
                project_dir,
                "character" if asset_type == "character_ref_regen" else "location",
                entity_id,
                state_id,
            )
        from novel_to_comic.state_assets import state_reference_dimensions

        # Canonical sheets and plates share their state references' sizes.
        width, height = (
            state_reference_dimensions(config, kind_for_asset[asset_type])
            if asset_type in kind_for_asset else (None, None)
        )
        cost_usd = estimate_image_cost(
            config.effective_image_model(),
            1,
            quality=getattr(config, "image_quality", None),
            ref_count=ref_count + additional_reference_count,
            width=width,
            height=height,
        )
        return credit_estimate_for_provider_cost(
            cost_usd, "cast", reserve=False, zero_cost_estimate=1
        )


def get_balance_credits(db: Client, user_id: str) -> int:
    result = (
        db.table("user_credits")
        .select("balance_credits")
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0]["balance_credits"] if result.data else 0


def get_project_id(db: Client, user_id: str, project_name: str) -> str | None:
    result = (
        db.table("projects")
        .select("id")
        .eq("user_id", user_id)
        .eq("name", project_name)
        .execute()
    )
    return result.data[0]["id"] if result.data else None


def insufficient_credits_detail(
    *,
    balance: int,
    required: int,
    stage: str | None,
    action: str | None = None,
) -> dict:
    """Build the structured 402 payload the frontend renders into a buy-credits dialog."""
    label = stage or action or "this action"
    return {
        "error": "insufficient_credits",
        "balance_credits": int(balance),
        "required_credits": int(required),
        "shortfall_credits": max(0, int(required) - int(balance)),
        "stage": stage,
        "action": action,
        "message": (
            f"Insufficient credits — {balance} available, "
            f"{required} required for '{label}'"
        ),
    }


def assert_sufficient_credits(
    db: Client,
    user_id: str,
    required_credits: int,
    *,
    stage: str | None = None,
    action: str | None = None,
) -> None:
    """Raise a structured 402 if the user does not have enough credits for the action.

    Used as a fast pre-check before queuing async work so the client can render
    a buy-credits prompt instead of having to listen for an SSE failure.
    """
    if required_credits <= 0:
        return
    balance = get_balance_credits(db, user_id)
    if balance < required_credits:
        raise HTTPException(
            402,
            insufficient_credits_detail(
                balance=balance,
                required=required_credits,
                stage=stage,
                action=action,
            ),
        )


def reserve_credits(
    db: Client,
    user_id: str,
    project_id: str | None,
    stage: str,
    amount_credits: int,
    *,
    job_id: str | None = None,
) -> tuple[str | None, str]:
    """Atomically reserve credits and return (reservation_id, job_id).

    Generates a fresh job_id UUID if none is provided. Returns reservation_id=None
    when amount_credits <= 0 (no hold needed), but always returns a job_id.
    """
    if job_id is None:
        job_id = str(uuid_lib.uuid4())
    if amount_credits <= 0:
        return None, job_id
    try:
        result = db.rpc(
            "reserve_stage_credits",
            {
                "p_user_id": user_id,
                "p_project_id": project_id,
                "p_stage": stage,
                "p_amount_credits": amount_credits,
                "p_job_id": job_id,
                "p_owner": _reservation_owner,
                "p_lease_seconds": RESERVATION_LEASE_SECONDS,
                "p_credits_per_usd": credits_per_provider_usd(),
                "p_markup": model_cost_markup(),
            },
        ).execute()
    except APIError as exc:
        if exc.message != "Expired credit reservation requires reconciliation":
            raise
        log.error("Credit database needs docs/sql/2026-09-11-reservation-isolation.sql")
        raise HTTPException(503, {
            "error": "credit_reservation_reconciliation",
            "message": "An earlier credit hold is blocking new work. No model request was started. "
            "The credit database needs maintenance; changing models or recreating the project will not fix this.",
        }) from exc
    reservation_id = result.data
    if not reservation_id:
        balance = get_balance_credits(db, user_id)
        raise HTTPException(
            402,
            insufficient_credits_detail(
                balance=balance,
                required=amount_credits,
                stage=stage,
            ),
        )
    _reservation_jobs[str(reservation_id)] = job_id
    return str(reservation_id), job_id


def authorize_model_call(
    db: Client,
    *,
    user_id: str,
    job_id: str | None,
    call_id: str,
    estimated_cost_usd: float | None,
) -> None:
    """Guarantee one API call against the active job hold before submission.

    The database accounts for other in-flight calls and extends the hold only
    when the user's unreserved balance can cover the additional guarantee.
    Unknown pricing fails closed before a provider request is submitted.
    """
    if not job_id:
        raise RuntimeError("Paid model call has no credit reservation job")
    if estimated_cost_usd is None or not math.isfinite(estimated_cost_usd) or estimated_cost_usd <= 0:
        raise RuntimeError("Paid model call has no usable price estimate")
    guarantee = max(1, math.ceil(provider_usd_to_credits(estimated_cost_usd) * 2))
    result = db.rpc("authorize_model_call_credits", {
        "p_user_id": user_id,
        "p_job_id": job_id,
        "p_usage_call_id": call_id,
        "p_amount_credits": guarantee,
        "p_owner": _reservation_owner,
        "p_credits_per_usd": credits_per_provider_usd(),
        "p_markup": model_cost_markup(),
    }).execute()
    if result.data is not True:
        raise HTTPException(402, {
            "error": "insufficient_credits",
            "message": "Insufficient credits for the next model call. The job stopped before submission.",
        })
    scope = _deferred_ambiguity.get()
    if scope is not None:
        scope.call_ids.append(call_id)


def release_model_call_authorization(db: Client, *, user_id: str, call_id: str) -> None:
    """Free a guarantee when a call is known not to be billable."""
    db.rpc("release_model_call_authorization", {
        "p_user_id": user_id,
        "p_usage_call_id": call_id,
    }).execute()


def debit_model_usage(
    db: Client,
    user_id: str,
    project_id: str | None,
    usage: UsageRecord,
    *,
    stage: str | None = None,
    description: str,
    job_id: str | None = None,
) -> None:
    """Insert one settled row, rounding public credits once per job.

    The database RPC serializes concurrent calls for the same job and assigns
    only the incremental whole-credit debit. This preserves per-call audit rows
    without rounding every tiny request up independently. Ambiguous responses
    are reconciled by retrying the immutable, idempotent database operation.
    """
    # Local Codex diagnostics live in AI usage events, never the credit ledger.
    if is_subscription(usage.funding):
        return
    if calculate_cost_breakdown(usage).source == "unknown_provider_usage":
        retain_ambiguous_job(job_id)
        raise RuntimeError("Provider image usage is incomplete; reconcile billing without regenerating the saved image")
    credits, cost_usd = usage_to_credit_debit(usage)
    try:
        cost = calculate_cost_breakdown(usage)
    except Exception:
        # The breakdown is optional metadata (provider_model, source, pricing
        # snapshot). The core debit still goes through; we just lose the
        # audit color. Log so a persistent pricing-resolver failure surfaces.
        log.warning("calculate_cost_breakdown failed; debiting without metadata", exc_info=True)
        cost = None
    if credits <= 0:
        return
    params = {
        "p_user_id": user_id,
        "p_project_id": project_id,
        "p_job_id": job_id or str(uuid_lib.uuid5(uuid_lib.NAMESPACE_URL, usage.call_id)),
        "p_stage": stage,
        "p_description": description,
        "p_usage_call_id": usage.call_id,
        "p_provider": usage.provider,
        "p_model": usage.model,
        "p_provider_model": cost.provider_model if cost else None,
        "p_operation": usage.operation,
        "p_input_tokens": usage.input_tokens,
        "p_output_tokens": usage.output_tokens,
        "p_image_count": usage.image_count,
        "p_cost_usd": cost_usd,
        "p_cost_source": cost.source if cost else None,
        "p_pricing_snapshot": cost.pricing_snapshot if cost else None,
        "p_credits_per_usd": credits_per_provider_usd(),
        "p_markup": model_cost_markup(),
        "p_billable": usage_has_billable_activity(usage),
        "p_funding": usage.funding,
    }
    try:
        db.rpc("settle_model_usage_credits", params).execute()
    except Exception:
        # A lost response is not evidence that the transaction rolled back.
        # Replay the exact call id; never overwrite a committed incremental zero.
        try:
            db.rpc("settle_model_usage_credits", params).execute()
        except Exception:
            _unsettled_jobs.add(params["p_job_id"])
            raise


def release_reservation(
    db: Client,
    reservation_id: str,
) -> None:
    """Mark the reservation RELEASED (stage failed or was reset)."""
    if _reservation_jobs.get(reservation_id) in _unsettled_jobs:
        log.error("Retaining reservation %s for ambiguous usage reconciliation", reservation_id)
        return
    db.rpc("release_credit_reservation", {
        "p_reservation_id": reservation_id, "p_owner": _reservation_owner,
    }).execute()
    _reservation_jobs.pop(reservation_id, None)
