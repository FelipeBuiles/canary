"""Narration decision editing — single owner of load → patch → classify → estimate → save.

The ``estimate_narration_decision_impact`` and ``update_narration_decision``
routes used to duplicate the patch logic and compose the helpers by hand.  This
module owns the complete flow so both routes become thin dispatchers and the
patch logic has exactly one implementation.
"""

from pathlib import Path
from typing import Any

from novel_to_comic.config import Config
from novel_to_comic.layout_planning import (
    NarrationChangeImpact,
    apply_narration_decision_patch,
    load_layout_plan,
    save_layout_plan,
)
from novel_to_comic.models.layout_plan import NarrationDecision
from novel_to_comic.state import PipelineState

from .credits import CreditEstimate, estimate_stage_credit_breakdown

_COSTED_STAGES = frozenset({"adapt", "plan", "storyboard", "direct", "draw", "compose"})


def _add_credit_estimates(
    impact: NarrationChangeImpact,
    config: Config,
    project_dir: Path,
    state: PipelineState,
) -> dict[str, Any]:
    """Augment a NarrationChangeImpact dict with per-stage credit estimates."""
    stage_costs: dict[str, CreditEstimate] = {
        stage: estimate_stage_credit_breakdown(config, project_dir, state, stage)
        for stage in impact["affected_stages"]
        if stage in _COSTED_STAGES
    }
    result: dict[str, Any] = dict(impact)
    result["estimated_credits"] = sum(s["estimate_credits"] for s in stage_costs.values())
    result["reserved_credits"] = sum(
        s["reserved_credits"] for s in stage_costs.values() if s["reserved_credits"] is not None
    )
    result["stage_credits"] = {
        stage: {
            "estimate_credits": s["estimate_credits"],
            "reserved_credits": s["reserved_credits"],
            "confidence": s["confidence"],
        }
        for stage, s in stage_costs.items()
    }
    return result


def estimate_patch_impact(
    project_dir: Path,
    beat_id: str,
    patch: dict,
    config: Config,
    state: PipelineState,
) -> dict[str, Any]:
    """Apply ``patch`` to the narration decision in-memory and return the impact bundle.

    Raises ``FileNotFoundError`` if the layout plan doesn't exist, ``KeyError``
    if ``beat_id`` is not found.  Does NOT save the plan.
    """
    plan = load_layout_plan(project_dir)
    _, impact = apply_narration_decision_patch(plan, beat_id, patch)
    return _add_credit_estimates(impact, config, project_dir, state)


def apply_patch(
    project_dir: Path,
    beat_id: str,
    patch: dict,
) -> tuple[NarrationDecision, NarrationChangeImpact]:
    """Apply ``patch``, persist the plan, and return ``(decision, impact)``.

    Raises ``FileNotFoundError`` if the layout plan doesn't exist, ``KeyError``
    if ``beat_id`` is not found.
    """
    plan = load_layout_plan(project_dir)
    plan, impact = apply_narration_decision_patch(plan, beat_id, patch)
    save_layout_plan(project_dir, plan)
    decision = next(d for d in plan.narration_decisions if d.beat_id == beat_id)
    return decision, impact
