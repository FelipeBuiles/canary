"""Pipeline state machine: read/write state.json, track stage progress."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from novel_to_comic.usage import UsageRecord

STALE_RUNNING_THRESHOLD = timedelta(minutes=5)


def hash_style_template(style_template: str) -> str:
    """Stable SHA-256 hex digest of a style template string.

    Whitespace-normalised so trivial editing changes (indentation, trailing
    newline) don't invalidate the pinned hash.
    """
    import hashlib
    normalised = " ".join((style_template or "").split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def style_template_drifted(state: "PipelineState", current_template: str) -> bool:
    """Return True when the pinned style hash exists and disagrees with the
    current template — i.e. the cast plates were rendered under a different
    style than the one downstream stages are about to use."""
    if not state.style_template_hash:
        return False
    return state.style_template_hash != hash_style_template(current_template)


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETE = "complete"
    FAILED = "failed"


class StageState(BaseModel):
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_progress_at: Optional[datetime] = None
    items_done: int = 0
    items_total: int = 0
    items_failed: list[str] = Field(default_factory=list)
    approved: Optional[bool] = None
    # estimated_cost_usd: set before the stage runs for credit reservation.
    # cost_usd: accumulates actual cost from real API usage during the run.
    estimated_cost_usd: float = 0.0
    cost_usd: float = 0.0
    # Append-only log of individual API call records. Preserved for audit and
    # future per-call billing. Stored as dicts for JSON portability.
    usage_log: list[dict] = Field(default_factory=list)
    error: Optional[str] = None
    # Bounded traceback retained for local-first debugging. The API only
    # exposes this field in development diagnostics mode.
    error_detail: Optional[str] = None
    # Structured credit-failure detail. Set only when a stage failed because
    # the user's balance couldn't cover the reservation (see fail_stage). Cleared
    # on every non-credit failure so a stale code can't linger across re-runs.
    error_code: Optional[str] = None
    balance_credits: Optional[int] = None
    required_credits: Optional[int] = None
    shortfall_credits: Optional[int] = None


STAGE_NAMES = [
    "extract",
    "brief",
    "style",
    "cast",
    "adapt",
    "plan",
    "draw",
    "finish",
]
CHECKPOINT_STAGES = {"brief", "style", "cast", "draw"}


class PipelineState(BaseModel):
    project_name: str
    novel_path: str
    created_at: datetime
    stages: dict[str, StageState] = Field(default_factory=dict)
    total_cost_usd: float = 0.0
    misc_cost_usd: float = 0.0
    style_template_hash: Optional[str] = None
    # SHA-256 hash of the style_template string at the moment the cast stage
    # generated character/location reference plates. Downstream stages check
    # this hash against the current config to detect style-drift: if the
    # template changed after cast ran, plates will not match new page artwork
    # and a re-run of cast is recommended.

    @model_validator(mode="after")
    def _validate_stage_names(self) -> "PipelineState":
        unknown = sorted(set(self.stages) - set(STAGE_NAMES))
        if unknown:
            raise ValueError(f"unknown pipeline stages: {', '.join(unknown)}")
        return self

    def model_post_init(self, __context: object) -> None:
        for name in STAGE_NAMES:
            if name not in self.stages:
                self.stages[name] = StageState()


def _state_path(project_dir: Path) -> Path:
    return project_dir / "state.json"


def load_state(project_dir: Path) -> PipelineState:
    """Load pipeline state from state.json."""
    path = _state_path(project_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"No pipeline state found at {path}\n"
            f"  Is '{project_dir}' a valid project directory?\n"
            f"  Run 'pipeline init <novel.txt>' to create a new project."
        )
    with open(path) as f:
        return PipelineState.model_validate_json(f.read())


def save_state(state: PipelineState, project_dir: Path) -> None:
    """Atomically write pipeline state to state.json.

    Writes to a temp file first, then renames — prevents corruption
    if the process crashes mid-write.
    """
    path = _state_path(project_dir)
    data = state.model_dump_json(indent=2)
    # Write to temp file in the same directory, then atomic rename
    fd, tmp_path = tempfile.mkstemp(dir=project_dir, suffix=".json.tmp")
    try:
        with open(fd, "w") as f:
            f.write(data)
        Path(tmp_path).replace(path)
    except BaseException:
        # Clean up temp file on failure
        Path(tmp_path).unlink(missing_ok=True)
        raise


def create_initial_state(project_name: str, novel_path: str) -> PipelineState:
    """Create a fresh pipeline state."""
    return PipelineState(
        project_name=project_name,
        novel_path=novel_path,
        created_at=datetime.now(timezone.utc),
    )


def begin_stage(
    state: PipelineState,
    stage: str,
    total: int = 0,
    estimated_cost_usd: float = 0.0,
) -> None:
    """Mark a stage as running. Resets counters for clean tracking.

    estimated_cost_usd should be set to a pre-run cost estimate so the
    credits layer can reserve the appropriate amount before generation starts.
    After the stage completes, cost_usd holds the actual amount.
    """
    s = state.stages[stage]
    s.status = StageStatus.RUNNING
    s.started_at = datetime.now(timezone.utc)
    s.finished_at = None
    s.last_progress_at = None
    s.items_total = total
    s.items_done = 0
    s.items_failed = []
    s.estimated_cost_usd = estimated_cost_usd
    s.cost_usd = 0.0
    s.usage_log = []
    s.error = None
    s.error_detail = None

def complete_stage(state: PipelineState, stage: str) -> None:
    """Mark a stage as complete (or awaiting review if it's a checkpoint stage)."""
    s = state.stages[stage]
    s.finished_at = datetime.now(timezone.utc)
    if stage in CHECKPOINT_STAGES:
        s.status = StageStatus.AWAITING_REVIEW
    else:
        s.status = StageStatus.COMPLETE
    state.total_cost_usd = sum(st.cost_usd for st in state.stages.values()) + state.misc_cost_usd


def fail_stage(
    state: PipelineState,
    stage: str,
    error: str,
    *,
    detail: dict | None = None,
    error_detail: str | None = None,
) -> None:
    """Mark a stage as failed and retain bounded local diagnostic detail.

    ``detail`` is the structured credit-failure payload. ``error_detail`` is a
    traceback or other developer-facing explanation and must never contain
    prompts or provider credentials.
    """
    s = state.stages[stage]
    s.status = StageStatus.FAILED
    s.finished_at = datetime.now(timezone.utc)
    s.error = error
    s.error_detail = (error_detail or "")[-12_000:] or None
    if detail and detail.get("error") == "insufficient_credits":
        s.error_code = "insufficient_credits"
        s.balance_credits = detail.get("balance_credits")
        s.required_credits = detail.get("required_credits")
        s.shortfall_credits = detail.get("shortfall_credits")
    else:
        s.error_code = "model_refusal" if detail and detail.get("error") == "model_refusal" else None
        s.balance_credits = None
        s.required_credits = None
        s.shortfall_credits = None
    state.total_cost_usd = sum(st.cost_usd for st in state.stages.values()) + state.misc_cost_usd


def approve_stage(state: PipelineState, stage: str) -> None:
    """Approve a checkpoint stage, moving it to complete."""
    s = state.stages[stage]
    if s.status != StageStatus.AWAITING_REVIEW:
        raise ValueError(f"Stage '{stage}' is not awaiting review (status: {s.status})")
    s.approved = True
    s.status = StageStatus.COMPLETE


def record_item_done(
    state: PipelineState,
    stage: str,
    cost: float = 0.0,
    usage: UsageRecord | None = None,
) -> None:
    """Increment items_done and record cost.

    Pass usage to derive cost from real token counts and append to the
    audit log. Pass cost directly (legacy) when no API call was made.
    """
    from novel_to_comic.usage import calculate_cost

    s = state.stages[stage]
    s.items_done += 1
    s.last_progress_at = datetime.now(timezone.utc)
    if usage is not None:
        s.usage_log.append(usage.model_dump())
        s.cost_usd += calculate_cost(usage)
    else:
        s.cost_usd += cost


def record_api_usage(state: PipelineState, stage: str, usage: UsageRecord) -> None:
    """Append an API usage record without incrementing items_done.

    Use this when a stage makes API calls that don't map 1:1 to items
    (e.g., layout planning builds all scenes in one async gather then
    records items_done separately).
    """
    from novel_to_comic.usage import calculate_cost

    s = state.stages[stage]
    s.usage_log.append(usage.model_dump())
    s.last_progress_at = datetime.now(timezone.utc)
    s.cost_usd += calculate_cost(usage)


def is_stale(stage_state: StageState) -> bool:
    """Heartbeat-based liveness check.

    A stage is stale when it claims RUNNING but no progress has been
    recorded recently. ``last_progress_at`` is updated on every
    ``record_item_done`` / ``record_api_usage`` call. We fall back to
    ``started_at`` for the window between begin and the first progress
    record.

    Note: callers should also AND with "no live asyncio task" to avoid
    flagging healthy long stages whose state.json hasn't been written
    in the threshold window. See ``_stage_payload`` in
    server/routers/projects.py.
    """
    if stage_state.status != StageStatus.RUNNING:
        return False
    last = stage_state.last_progress_at or stage_state.started_at
    if last is None:
        return False
    age = datetime.now(timezone.utc) - last
    return age > STALE_RUNNING_THRESHOLD


def get_stale_stages(state: PipelineState) -> list[str]:
    return [name for name, s in state.stages.items() if is_stale(s)]


def reset_stale_stages(state: PipelineState) -> list[str]:
    reset = []
    for name, s in state.stages.items():
        if is_stale(s):
            state.stages[name] = StageState()
            reset.append(name)
    return reset


def record_item_failed(state: PipelineState, stage: str, item_id: str) -> None:
    """Record a failed item for later retry."""
    s = state.stages[stage]
    s.items_failed.append(item_id)


def record_misc_usage(state: PipelineState, usage: UsageRecord) -> None:
    """Record cost from a non-stage API call (style samples, cover, etc.).

    Adds the cost to misc_cost_usd and updates total_cost_usd.
    """
    from novel_to_comic.usage import calculate_cost

    cost = calculate_cost(usage)
    state.misc_cost_usd += cost
    state.total_cost_usd = sum(st.cost_usd for st in state.stages.values()) + state.misc_cost_usd
