"""Credit reservation, model usage debits, and release against the Supabase ledger."""

from __future__ import annotations

import math
import os
import uuid as uuid_lib
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Literal, TypedDict

from fastapi import HTTPException
from supabase import Client

from novel_to_comic.config import Config
from novel_to_comic.state import PipelineState
from novel_to_comic.usage import UsageRecord, calculate_cost, calculate_cost_breakdown, estimate_image_cost, estimate_text_cost, usage_has_billable_activity

CostConfidence = Literal["low_variance", "usually_within_estimate", "variable"]


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
    cost_usd = estimate_stage_provider_cost_usd(config, project_dir, state, stage)
    return provider_usd_to_credits(cost_usd)


def stage_cost_confidence(stage: str) -> CostConfidence:
    _map: dict[str, CostConfidence] = {
        "extract": "usually_within_estimate",
        "style": "usually_within_estimate",
        "cast": "variable",
        "adapt": "usually_within_estimate",
        "plan": "usually_within_estimate",
        "storyboard": "low_variance",
        "direct": "low_variance",
        "draw": "variable",
        "compose": "low_variance",
    }
    return _map.get(stage, "variable")


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
    if stage == "extract":
        return _estimate_extract_cost(config, project_dir, state)
    if stage == "style":
        return _estimate_style_cost(config, project_dir)
    if stage == "cast":
        return _estimate_cast_cost(config, project_dir)
    if stage == "adapt":
        return _estimate_adapt_cost(config, project_dir)
    if stage == "plan":
        return _estimate_plan_cost(config, project_dir)
    if stage == "draw":
        return _estimate_draw_cost(config, project_dir)
    # storyboard, direct, compose: deterministic, no model cost
    return 0.0


def _safe_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text()
    except Exception:
        return default


def _estimate_extract_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.stages.s1_extract import PROMPT_PATH

    novel_path = Path(state.novel_path)
    if not novel_path.is_absolute():
        novel_path = project_dir / novel_path
    try:
        raw = novel_path.read_bytes()
    except Exception:
        raw = b""
    try:
        novel_text = raw.decode("utf-8")
        input_payload: str | int = _safe_text(PROMPT_PATH) + "\n" + novel_text
    except UnicodeDecodeError:
        input_payload = len(raw)
    return estimate_text_cost(
        config.effective_extraction_model(),
        input_payload,
        output_chars=65536 * 4,
    )


def _load_json_model(path: Path, model):
    try:
        return model.model_validate_json(path.read_text())
    except Exception:
        return None


def _estimate_style_cost(config: Config, project_dir: Path) -> float:
    from novel_to_comic import artifacts
    if artifacts.style_suggestions_path(project_dir).exists():
        return 0.0
    from novel_to_comic.usage import estimate_text_cost
    story_bible_path = artifacts.story_bible_path(project_dir)
    context = _safe_text(story_bible_path)[:3000]
    return estimate_text_cost(config.effective_prompt_model(), context)


def _estimate_cast_cost(config: Config, project_dir: Path) -> float:
    from novel_to_comic.models.story_bible import StoryBible

    story_bible = _load_json_model(project_dir / "story_bible.json", StoryBible)
    if story_bible is None:
        return 0.0
    missing_refs = sum(
        1 for char in story_bible.characters
        if not (project_dir / "refs" / char.id / "sheet.png").exists()
    )
    missing_plates = sum(
        1 for loc in story_bible.locations
        if not (project_dir / "plates" / f"{loc.id}.png").exists()
    )
    return estimate_image_cost(
        config.effective_image_model(),
        missing_refs + missing_plates,
        quality=getattr(config, "image_quality", None),
    )


def _estimate_adapt_cost(config: Config, project_dir: Path) -> float:
    from novel_to_comic.stages.s4_screenplay import PROMPT_PATH
    from novel_to_comic.models.story_bible import StoryBible

    story_bible = _load_json_model(project_dir / "story_bible.json", StoryBible)
    if story_bible is None:
        return 0.0
    system_prompt = _safe_text(PROMPT_PATH)
    total = 0.0
    for scene in story_bible.scenes:
        if (project_dir / "screenplays" / f"{scene.id}.json").exists():
            continue
        scene_text = _safe_text(project_dir / "scenes" / f"{scene.id}.txt", "x" * 8000)
        total += estimate_text_cost(
            config.effective_screenplay_model(),
            system_prompt + "\n" + scene_text,
            output_chars=12000,
        )
    return total


def _estimate_plan_cost(config: Config, project_dir: Path) -> float:
    from novel_to_comic.models.story_bible import StoryBible
    from novel_to_comic.stages.s5_layout_plan import _PLAN_SCENE_SYSTEM

    story_bible = _load_json_model(project_dir / "story_bible.json", StoryBible)
    if story_bible is None:
        return 0.0
    total = 0.0
    for scene in story_bible.scenes:
        sp_path = project_dir / "screenplays" / f"{scene.id}.json"
        if not sp_path.exists():
            continue
        sp_text = _safe_text(sp_path, "x" * 4000)
        total += estimate_text_cost(
            config.effective_panel_model(),
            _PLAN_SCENE_SYSTEM + "\n" + sp_text,
            output_chars=8000,
        )
    return total


def _estimate_draw_cost(config: Config, project_dir: Path) -> float:
    from novel_to_comic.models.story_bible import StoryBible
    from novel_to_comic.stages.s7_draw import _find_style_sample, estimate_panel_image_cost_usd

    prompts_dir = project_dir / "direct"
    if not prompts_dir.exists():
        return 0.0
    total = 0.0
    model = config.effective_image_model()
    quality = getattr(config, "image_quality", None)
    style_sample = _find_style_sample(project_dir, config.style_template)
    scene_to_location: dict[str, str] = {}
    story_bible = _load_json_model(project_dir / "story_bible.json", StoryBible)
    if story_bible is not None:
        scene_to_location = {scene.id: scene.location_id for scene in story_bible.scenes}
    for prompt_path in prompts_dir.glob("*/panel_*.json"):
        try:
            scene_id = prompt_path.parent.name
            panel_number = int(prompt_path.stem.split("_")[1])
        except (IndexError, ValueError):
            total += estimate_image_cost(model, 1, quality=quality)
            continue
        output_path = project_dir / "draw" / scene_id / f"panel_{panel_number:03d}.png"
        if not output_path.exists():
            try:
                total += estimate_panel_image_cost_usd(
                    config,
                    project_dir,
                    prompt_path,
                    style_sample=style_sample,
                    scene_to_location=scene_to_location,
                )
            except Exception:
                total += estimate_image_cost(model, 1, quality=quality)
    return total


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
            f"Insufficient credits — {balance} available, {amount_credits} required for '{stage}'",
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
    """Insert one settled credit ledger row for one model-provider call."""
    credits, cost_usd = usage_to_credit_debit(usage)
    try:
        cost = calculate_cost_breakdown(usage)
    except Exception:
        cost = None
    if credits <= 0:
        return
    db.table("credit_ledger").upsert(
        {
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
            "job_id": job_id,
        },
        on_conflict="usage_call_id",
    ).execute()


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
