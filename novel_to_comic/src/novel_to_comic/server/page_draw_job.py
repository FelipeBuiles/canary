"""Typed view of a durable page draw and its scheduling/recovery rules.

The serialized JobCommand remains the durable wire format. Workers and queue
policy use this view so provider/correction routing is interpreted in one place.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .job_commands import JobCommand, PageArguments

PARALLEL_PAGE_PROVIDERS = frozenset({"fal-queue", "openai", "openai-fal", "runware-openai-fal", "vertex-multimodal"})
PARALLEL_PAGES_PER_ACCOUNT = 12


@dataclass(frozen=True)
class PageDrawJob:
    command: JobCommand
    status: str = "queued"
    started_at: datetime | None = None

    @classmethod
    def from_job(cls, job) -> PageDrawJob | None:
        if job.kind != "complete_page_draw" or job.command is None or job.command.operation != "page_draw":
            return None
        return cls(job.command, job.status, job.started_at)

    @property
    def arguments(self) -> PageArguments:
        return PageArguments.model_validate(self.command.arguments)

    @property
    def parallel_limit(self) -> int:
        request = self.command.arguments["request"]
        if request["provider"] == "codex-dev":
            if request.get("correction") is not None or self.command.arguments.get("edit_source"):
                return 0
            from novel_to_comic.ai.codex_runtime import IMAGE_PARALLEL_CALLS
            return IMAGE_PARALLEL_CALLS
        return PARALLEL_PAGES_PER_ACCOUNT if request["provider"] in PARALLEL_PAGE_PROVIDERS else 0

    @property
    def pool(self) -> str:
        return "codex-page" if self.command.arguments["request"]["provider"] == "codex-dev" else "page"

    @property
    def can_cancel(self) -> bool:
        # A started submission can have incurred spend even without an answer.
        return self.status == "queued" and self.started_at is None

    @staticmethod
    def failure_phase(error: BaseException) -> str | None:
        if getattr(error, "phase", None) == "ambiguous_submission":
            return "ambiguous_submission"
        return getattr(error, "page_failure_phase", None)
