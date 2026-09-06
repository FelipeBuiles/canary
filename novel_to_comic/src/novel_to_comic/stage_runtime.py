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

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
import logging
import time
import traceback
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


logger = logging.getLogger("canary.stage_cost")

# A streamed completion yields hundreds of chunks; SSE consumers only need
# enough to keep a bar moving and prove the request is alive.
_ACTIVITY_MIN_INTERVAL_S = 1.5
_ACTIVITY_MIN_FRACTION_DELTA = 0.02


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
        self._last_activity_at = 0.0
        self._last_activity_fraction: float | None = None

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
        if s.estimated_cost_usd > 0:
            ratio = s.cost_usd / s.estimated_cost_usd
            try:
                from novel_to_comic.server.metrics import observe

                observe("canary_stage_cost_ratio", ratio, stage=self.name)
            except Exception:
                pass
            if ratio > 2:
                logger.warning(
                    "Stage cost exceeded estimate stage=%s actual_usd=%.6f "
                    "estimated_usd=%.6f ratio=%.2f",
                    self.name,
                    s.cost_usd,
                    s.estimated_cost_usd,
                    ratio,
                )
        self._emit({
            "type": "stage_complete",
            "stage": self.name,
            "done": s.items_done,
            "total": s.items_total,
        })
        save_state(self._state, self._project_dir)

    def fail(self, error: str, *, error_detail: str | None = None) -> None:
        fail_stage(
            self._state,
            self.name,
            error,
            error_detail=error_detail,
        )
        try:
            from novel_to_comic.server.diagnostics import record_diagnostic

            record_diagnostic(
                self._project_dir,
                "stage_failed",
                stage=self.name,
                message=error,
                error_detail=error_detail,
            )
        except Exception:
            pass
        self._emit({"type": "stage_fail", "stage": self.name, "message": error})
        save_state(self._state, self._project_dir)

    @contextmanager
    def execute(
        self, total: int = 0, estimated_cost_usd: float = 0.0
    ) -> Generator[StageRuntime, None, None]:
        """Run one stage and optionally emit one local OTel span."""
        span_context = nullcontext()
        try:
            from opentelemetry import trace

            span_context = trace.get_tracer("canary.stage").start_as_current_span(
                f"stage.{self.name}",
                attributes={"canary.stage": self.name},
            )
        except Exception:
            pass
        with span_context as span:
            self.begin(total, estimated_cost_usd)
            try:
                yield self
                self.complete()
            except Exception as exc:
                if span is not None:
                    try:
                        span.record_exception(exc)
                    except Exception:
                        pass
                from novel_to_comic.text_utils import clean_exception_message
                from novel_to_comic.server.diagnostics import local_diagnostics_enabled

                self.fail(
                    clean_exception_message(exc),
                    error_detail=traceback.format_exc()
                    if local_diagnostics_enabled()
                    else None,
                )
                raise

    # ------------------------------------------------------------------
    # Progress / logging helpers
    # ------------------------------------------------------------------

    def progress(self, done: int, total: int) -> None:
        self._emit({"type": "stage_progress", "stage": self.name, "done": done, "total": total})

    def set_progress_total(self, total: int) -> None:
        """Update the total when a stage discovers its actual work.

        Some stages cannot know their work item count until an initial model
        response arrives. Never lower the total below work already completed,
        so a late estimate cannot make the UI report more than 100%.
        """

        if total < 0:
            raise ValueError("progress total cannot be negative")
        total = max(total, self.stage_state.items_done)
        self.stage_state.items_total = total
        self.save()
        self.progress(self.stage_state.items_done, total)

    def activity(
        self,
        *,
        fraction: float | None = None,
        detail: str | None = None,
        force: bool = False,
    ) -> None:
        """Report sub-item progress inside the item currently being worked on.

        Deliberately separate from ``progress``: this is not persisted and may
        move backwards (a retried request restarts its stream), so it must not
        touch the ``items_done`` counters the status poll reconciles against.

        Throttled, because a streamed completion emits hundreds of chunks —
        pass ``force`` for transitions the UI must not miss.
        """
        if fraction is not None:
            fraction = min(1.0, max(0.0, fraction))
        now = time.monotonic()
        if not force:
            moved = (
                fraction is not None
                and self._last_activity_fraction is not None
                and abs(fraction - self._last_activity_fraction)
                >= _ACTIVITY_MIN_FRACTION_DELTA
            )
            elapsed = now - self._last_activity_at
            if elapsed < _ACTIVITY_MIN_INTERVAL_S and not moved:
                return
        self._last_activity_at = now
        self._last_activity_fraction = fraction
        self._emit({
            "type": "stage_activity",
            "stage": self.name,
            "fraction": fraction,
            "detail": detail,
            "at": datetime.now(UTC).isoformat(),
        })

    def log(self, message: str, level: str = "info") -> None:
        self._emit({"type": "log", "stage": self.name, "level": level, "message": message})

    def emit_page_start(self, page_number: int) -> None:
        from datetime import datetime, timezone
        self._emit({
            "type": "page_start",
            "stage": self.name,
            "page_number": page_number,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

    def emit_page_done(
        self,
        page_number: int,
        *,
        revision: int,
        status: str,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        self._emit({
            "type": "page_done",
            "stage": self.name,
            "page_number": page_number,
            "revision": revision,
            "status": status,
            "duration_ms": duration_ms,
            "error": error,
        })

    # ------------------------------------------------------------------
    # Usage / cost recording
    # ------------------------------------------------------------------

    def record_item_done(
        self, cost: float = 0.0, usage: UsageRecord | None = None
    ) -> None:
        record_item_done(self._state, self.name, cost, usage)
        save_state(self._state, self._project_dir)

    def record_api_usage(self, usage: UsageRecord) -> None:
        record_api_usage(self._state, self.name, usage)
        save_state(self._state, self._project_dir)

    def record_item_failed(self, item_id: str) -> None:
        record_item_failed(self._state, self.name, item_id)
        save_state(self._state, self._project_dir)

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
        save_state(self._state, self._project_dir)
