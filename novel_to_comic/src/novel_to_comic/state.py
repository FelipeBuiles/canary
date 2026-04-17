"""Pipeline state machine: read/write state.json, track stage progress."""

import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


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
    items_done: int = 0
    items_total: int = 0
    items_failed: list[str] = Field(default_factory=list)
    approved: Optional[bool] = None
    cost_usd: float = 0.0
    error: Optional[str] = None


STAGE_NAMES = ["extract", "index", "screenplay", "panels", "prompts", "generate", "assemble"]
CHECKPOINT_STAGES = {"extract", "index", "prompts", "generate"}


class PipelineState(BaseModel):
    project_name: str
    novel_path: str
    created_at: datetime
    stages: dict[str, StageState] = Field(default_factory=dict)
    total_cost_usd: float = 0.0

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


def begin_stage(state: PipelineState, stage: str, total: int = 0) -> None:
    """Mark a stage as running. Resets counters for clean tracking."""
    s = state.stages[stage]
    s.status = StageStatus.RUNNING
    s.started_at = datetime.now(timezone.utc)
    s.finished_at = None
    s.items_total = total
    s.items_done = 0
    s.items_failed = []
    s.cost_usd = 0.0
    s.error = None


def complete_stage(state: PipelineState, stage: str) -> None:
    """Mark a stage as complete (or awaiting review if it's a checkpoint stage)."""
    s = state.stages[stage]
    s.finished_at = datetime.now(timezone.utc)
    if stage in CHECKPOINT_STAGES:
        s.status = StageStatus.AWAITING_REVIEW
    else:
        s.status = StageStatus.COMPLETE
    state.total_cost_usd = sum(st.cost_usd for st in state.stages.values())


def fail_stage(state: PipelineState, stage: str, error: str) -> None:
    """Mark a stage as failed."""
    s = state.stages[stage]
    s.status = StageStatus.FAILED
    s.finished_at = datetime.now(timezone.utc)
    s.error = error
    state.total_cost_usd = sum(st.cost_usd for st in state.stages.values())


def approve_stage(state: PipelineState, stage: str) -> None:
    """Approve a checkpoint stage, moving it to complete."""
    s = state.stages[stage]
    if s.status != StageStatus.AWAITING_REVIEW:
        raise ValueError(f"Stage '{stage}' is not awaiting review (status: {s.status})")
    s.approved = True
    s.status = StageStatus.COMPLETE


def record_item_done(state: PipelineState, stage: str, cost: float = 0.0) -> None:
    """Increment the items_done counter and add cost."""
    s = state.stages[stage]
    s.items_done += 1
    s.cost_usd += cost


def record_item_failed(state: PipelineState, stage: str, item_id: str) -> None:
    """Record a failed item for later retry."""
    s = state.stages[stage]
    s.items_failed.append(item_id)
