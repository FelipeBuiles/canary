"""Stage runtime: owns the lifecycle of a single stage execution.

Every stage's ``run()`` function receives a ``StageRuntime`` instead of
threading ``on_event`` and calling state-mutation functions directly.  The
runtime owns:

- State transitions: begin → (progress×n) → complete | fail
- Event emission (stage_begin, stage_progress, stage_complete, stage_fail, log)
- State persistence (save_state) at each transition
- Usage / cost recording delegated to the underlying state functions

Usage in a stage::

    async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> MyResult:
        with ctx.execute(total=len(items)):
            for i, item in enumerate(items):
                result = await process(item)
                ctx.record_item_done(usage=result.usage)
                ctx.progress(i + 1, len(items))
        return result

The ``execute`` context manager calls ``begin`` on entry and ``complete`` on
clean exit; on exception it calls ``fail`` and re-raises.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Generator

from novel_to_comic.events import EventCallback, _NOOP
from novel_to_comic.state import (
    PipelineState,
    StageState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_api_usage,
    record_item_done,
    record_item_failed,
    save_state,
)

if TYPE_CHECKING:
    from novel_to_comic.usage import UsageRecord


class StageRuntime:
    """Owns state transitions, event emission, and persistence for one stage run."""

    def __init__(
        self,
        name: str,
        state: PipelineState,
        project_dir: Path,
        on_event: EventCallback | None = None,
    ) -> None:
        self.name = name
        self._state = state
        self._project_dir = project_dir
        self._on_event = on_event
        self._emit = on_event or _NOOP

    @property
    def on_event(self) -> EventCallback | None:
        """The raw on_event callback, or None if running CLI-only.

        Pass to ``make_progress()`` so helper functions can decide between
        a Rich progress bar (CLI) and a silent stand-in (web / TUI).
        """
        return self._on_event

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def state(self) -> PipelineState:
        """Full pipeline state — for reads (e.g. state.novel_path)."""
        return self._state

    @property
    def stage_state(self) -> StageState:
        return self._state.stages[self.name]

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def begin(self, total: int = 0, estimated_cost_usd: float = 0.0) -> None:
        begin_stage(self._state, self.name, total, estimated_cost_usd)
        self._emit({"type": "stage_begin", "stage": self.name, "total": total})
        save_state(self._state, self._project_dir)

    def complete(self) -> None:
        complete_stage(self._state, self.name)
        s = self._state.stages[self.name]
        self._emit({
            "type": "stage_complete",
            "stage": self.name,
            "done": s.items_done,
            "total": s.items_total,
        })
        save_state(self._state, self._project_dir)

    def fail(self, error: str) -> None:
        fail_stage(self._state, self.name, error)
        self._emit({"type": "stage_fail", "stage": self.name, "message": error})
        save_state(self._state, self._project_dir)

    @contextmanager
    def execute(
        self, total: int = 0, estimated_cost_usd: float = 0.0
    ) -> Generator[StageRuntime, None, None]:
        """Context manager: begin on entry, complete on success, fail+reraise on error."""
        self.begin(total, estimated_cost_usd)
        try:
            yield self
            self.complete()
        except Exception as exc:
            self.fail(str(exc))
            raise

    # ------------------------------------------------------------------
    # Progress / logging helpers
    # ------------------------------------------------------------------

    def progress(self, done: int, total: int) -> None:
        self._emit({"type": "stage_progress", "stage": self.name, "done": done, "total": total})

    def log(self, message: str, level: str = "info") -> None:
        self._emit({"type": "log", "stage": self.name, "level": level, "message": message})

    # ------------------------------------------------------------------
    # Usage / cost recording
    # ------------------------------------------------------------------

    def record_item_done(
        self, cost: float = 0.0, usage: UsageRecord | None = None
    ) -> None:
        record_item_done(self._state, self.name, cost, usage)

    def record_api_usage(self, usage: UsageRecord) -> None:
        record_api_usage(self._state, self.name, usage)

    def record_item_failed(self, item_id: str) -> None:
        record_item_failed(self._state, self.name, item_id)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        save_state(self._state, self._project_dir)

    # ------------------------------------------------------------------
    # Stage-specific state helpers
    # ------------------------------------------------------------------

    def set_style_template_hash(self, hash_value: str) -> None:
        """Record the style template hash after the cast stage completes."""
        self._state.style_template_hash = hash_value

    def set_estimated_cost(self, cost_usd: float) -> None:
        self._state.stages[self.name].estimated_cost_usd = cost_usd
