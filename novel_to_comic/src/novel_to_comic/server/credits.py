"""Credit reservation, model usage debits, and release against the Supabase ledger."""

from __future__ import annotations

import logging
import math
import os
import uuid as uuid_lib
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Literal, TypedDict

from fastapi import HTTPException
from supabase import Client

from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.state import PipelineState
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


class CreditEstimate(TypedDict):
    estimate_credits: int
    reserved_credits: int | None
    reservation_multiplier: float
    confidence: CostConfidence

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
    """Return (credits, raw provider USD) for one model usage record.

    This is the only place where provider USD is converted to public credits.
    Keep purchase package math separate so margin is not applied twice.
    """
    if usage.cost_source == "mock":
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
    if mock_mode_active(config):
        return 0
    cost_usd = estimate_stage_provider_cost_usd(config, project_dir, state, stage)
    base_credits = provider_usd_to_credits(cost_usd)
    if base_credits <= 0:
        return 0
    return math.ceil(base_credits * reservation_buffer())


def estimate_stage_credit_cost(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    stage: str,
) -> int:
    """Unbuffered projected final cost in public credits."""
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
        "adapt": "usually_within_estimate",
        "plan": "usually_within_estimate",
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
) -> CreditEstimate:
    """Build the canonical CreditEstimate for one provider-cost figure.

    ``reserve=False`` is for fire-and-forget Generation jobs (no hold is
    placed, so reserved_credits is None). ``zero_cost_estimate`` floors the
    estimate when the provider cost can't be computed — regen estimates floor
    to 1 so the pre-check still runs.
    """
    estimate = max(1, provider_usd_to_credits(cost_usd)) if cost_usd > 0 else zero_cost_estimate
    multiplier = reservation_buffer()
    if reserve:
        reserved: int | None = math.ceil(estimate * multiplier) if estimate > 0 else 0
    else:
        reserved = None
    return CreditEstimate(
        estimate_credits=estimate,
        reserved_credits=reserved,
        reservation_multiplier=multiplier,
        confidence=stage_cost_confidence(stage),
    )


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
    )


def estimate_stage_provider_cost_usd(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    stage: str,
) -> float:
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
        if mock_mode_active(config):
            return CreditEstimate(
                estimate_credits=0,
                reserved_credits=None,
                reservation_multiplier=reservation_buffer(),
                confidence="low_variance",
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
    ) -> CreditEstimate:
        """Estimate the credits needed to regenerate a single cast asset (character sheet or plate)."""
        if mock_mode_active(config):
            return credit_estimate_for_provider_cost(0.0, "cast", reserve=False)
        ref_count = 0
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
        cost_usd = estimate_image_cost(
            config.effective_image_model(),
            1,
            quality=getattr(config, "image_quality", None),
            ref_count=ref_count,
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
    result = (
        db.rpc(
            "reserve_stage_credits",
            {
                "p_user_id": user_id,
                "p_project_id": project_id,
                "p_stage": stage,
                "p_amount_credits": amount_credits,
                "p_job_id": job_id,
            },
        )
        .execute()
    )
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
    return str(reservation_id), job_id


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
    without rounding every tiny request up independently. The direct upsert is
    a deployment fallback until the accompanying schema function is installed.
    """
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
    payload = {
        "user_id": user_id,
        "project_id": project_id,
        "amount_credits": -credits,
        "status": "settled",
        "stage": stage,
        "description": description,
        "usage_call_id": usage.call_id,
        "provider": usage.provider,
        "model": usage.model,
        "provider_model": cost.provider_model if cost else None,
        "operation": usage.operation,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "image_count": usage.image_count,
        "cost_usd": cost_usd,
        "cost_source": cost.source if cost else None,
        "pricing_snapshot": cost.pricing_snapshot if cost else None,
        "job_id": job_id,
    }
    if job_id:
        try:
            db.rpc(
                "settle_model_usage_credits",
                {
                    "p_user_id": user_id,
                    "p_project_id": project_id,
                    "p_job_id": job_id,
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
                },
            ).execute()
            return
        except Exception:
            log.warning(
                "Job-level credit settlement unavailable; falling back to per-call rounding",
                exc_info=True,
            )
    db.table("credit_ledger").upsert(payload, on_conflict="usage_call_id").execute()


def release_reservation(
    db: Client,
    reservation_id: str,
) -> None:
    """Mark the reservation RELEASED (stage failed or was reset)."""
    db.table("credit_ledger").update({"status": "released"}).eq("id", reservation_id).eq("status", "reserved").execute()


def release_stage_reservations(
    db: Client,
    user_id: str,
    project_id: str | None,
    stage: str,
) -> None:
    """Release any outstanding reservations for a project stage."""
    q = (
        db.table("credit_ledger")
        .update({"status": "released"})
        .eq("user_id", user_id)
        .eq("stage", stage)
        .eq("status", "reserved")
    )
    if project_id:
        q = q.eq("project_id", project_id)
    else:
        q = q.is_("project_id", "null")
    q.execute()


def release_all_stale_reservations(db: Client) -> int:
    """Release every in-flight reservation — safe to call on server startup when no pipeline is running."""
    result = (
        db.table("credit_ledger")
        .update({"status": "released"})
        .eq("status", "reserved")
        .execute()
    )
    return len(result.data) if result.data else 0
