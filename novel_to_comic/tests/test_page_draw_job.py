"""Durable page policy follows frozen inputs and preserves the command wire format."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from novel_to_comic.config import Config
from novel_to_comic.server.job_commands import command
from novel_to_comic.server.page_draw_job import PageDrawJob
from .test_complete_page_draw import _compile, _page


@pytest.mark.parametrize("provider,correction,edit_source,limit,pool", [
    ("fal-queue", False, False, 12, "page"),
    ("openai-fal", True, False, 12, "page"),
    ("vertex-multimodal", False, False, 12, "page"),
    ("codex-dev", False, False, 2, "codex-page"),
    ("codex-dev", True, False, 0, "codex-page"),
    ("codex-dev", False, True, 0, "codex-page"),
    ("other", False, False, 0, "page"),
])
def test_frozen_routing_policy(provider, correction, edit_source, limit, pool):
    descriptor = SimpleNamespace(arguments={"request": {
        "provider": provider, "correction": {} if correction else None,
    }, "edit_source": "digest" if edit_source else None})
    page_job = PageDrawJob(descriptor)
    assert page_job.parallel_limit == limit
    assert page_job.pool == pool


@pytest.mark.parametrize("status,started,expected", [
    ("queued", False, True), ("queued", True, False), ("running", True, False),
    ("failed", False, False), ("complete", True, False),
])
def test_cancellation_requires_unstarted_queue(status, started, expected):
    page_job = PageDrawJob(None, status, datetime.now(timezone.utc) if started else None)
    assert page_job.can_cancel is expected


@pytest.mark.parametrize("phase,page_phase,expected", [
    (None, None, None), (None, "analysis", "analysis"),
    ("ambiguous_submission", "generation", "ambiguous_submission"),
])
def test_failure_phase_keeps_ambiguity_and_saved_artwork(phase, page_phase, expected):
    error = RuntimeError("draw failed")
    error.phase, error.page_failure_phase = phase, page_phase
    assert PageDrawJob.failure_phase(error) == expected


def test_typed_view_does_not_change_serialized_command_or_frozen_request(tmp_path):
    compiled = _compile(tmp_path)
    spec = command("page_draw", tmp_path, Config(),
        request=compiled.request.model_dump(mode="json"), page=_page().model_dump(mode="json"),
        references=["a" * 64] * len(compiled.reference_bytes))
    before = spec.model_dump_json()
    typed = PageDrawJob(spec).arguments
    assert typed.request.model_dump_json() == compiled.request.model_dump_json()
    assert type(spec).model_validate_json(before).model_dump_json() == before
    assert spec.model_dump_json() == before
