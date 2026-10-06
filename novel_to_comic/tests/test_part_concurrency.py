"""Parts progress independently: another part's work never blocks this one."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_to_comic.config import Config
from novel_to_comic.server.admission import mutation_conflicts, project_busy
from novel_to_comic.server.deps import event_key
from novel_to_comic.server.generation_jobs import GenerationJob, is_light_job
from novel_to_comic.server.job_commands import command


def _job(job_id: str, directory: Path | None, *, kind: str = "complete_page_draw", stage: str = "draw"):
    return GenerationJob(
        id=job_id, project_name="account:book", kind=kind, label=job_id,
        payload={"stage": stage}, sequence=1, runner=None,
        command=command("pipeline", directory, Config()).model_copy(update={"stage": stage}) if directory is not None else None,
    )


def _app(*jobs) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(
        generation_jobs={job.id: job for job in jobs},
    ))


def test_a_part_waits_only_for_its_own_and_series_work(tmp_path) -> None:
    root = tmp_path / "book"
    part_one = root / "parts" / "part_0001"
    drawing = _app(_job("draw", part_one))

    assert project_busy(drawing, "account:book")
    assert project_busy(drawing, "account:book", "part_0001")
    assert not project_busy(drawing, "account:book", "part_0002")
    assert not project_busy(drawing, "account:book", series=True)

    casting = _app(_job("cast", root, kind="character_ref_regen", stage="cast"))
    assert project_busy(casting, "account:book", "part_0002")
    assert project_busy(casting, "account:book", series=True)


def test_mutations_conflict_only_with_overlapping_work(tmp_path) -> None:
    root = tmp_path / "book"
    app = _app(_job("draw", root / "parts" / "part_0001"))

    assert not mutation_conflicts(app, "account:book", "/run", "part_0002")
    assert mutation_conflicts(app, "account:book", "/run", "part_0001")
    assert not mutation_conflicts(app, "account:book", "/parts")
    assert not mutation_conflicts(app, "account:book", "/parts/export")
    assert not mutation_conflicts(app, "account:book", "", "part_0001", method="PATCH")
    assert not mutation_conflicts(app, "account:book", "/approve/cast")
    assert not mutation_conflicts(app, "account:book", "/story-bible/characters/char_001")


@pytest.mark.parametrize('scope,part_busy,series_busy', [('sibling', False, False), ('own', True, False), ('series', True, True)])
def test_status_projects_the_same_busy_scope_as_admission(tmp_path, monkeypatch, scope, part_busy, series_busy):
    from novel_to_comic.server.routers import projects, parts
    from novel_to_comic.state import create_initial_state
    root = tmp_path / 'account' / 'book'
    part = root / 'parts' / 'part_0002'
    directory = root if scope == 'series' else part if scope == 'own' else root / 'parts' / 'part_0001'
    job = _job('active', directory, kind='character_ref_regen' if scope == 'series' else 'complete_page_draw',
               stage='cast' if scope == 'series' else 'draw')
    app = _app(job)
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    monkeypatch.setattr(projects, 'get_db', lambda: db)
    monkeypatch.setattr(projects, '_reconcile_series_stages', lambda *a: False)
    monkeypatch.setattr(projects, '_reopen_unapproved_brief', lambda *a: False)
    monkeypatch.setattr(projects, '_stage_payload', lambda *a, **kw: {'status': 'pending'})
    monkeypatch.setattr(projects, '_series_cost_usd', lambda *a: (0, 0))
    monkeypatch.setattr(parts, 'part_summaries', lambda *a: [])
    state = create_initial_state('Book', 'source.txt')
    result = projects._project_status_payload(SimpleNamespace(app=app), 'book', root, part, Config(), 'account',
                                              series_state=state, part_state=state)
    assert result['is_running'] is result['part_busy'] is part_busy
    assert result['series_busy'] is series_busy
    assert bool(result['active_jobs']) is part_busy


def test_story_bible_edits_wait_for_an_extraction(tmp_path) -> None:
    extracting = _app(_job("extract", tmp_path / "book" / "parts" / "part_0002",
                           kind="pipeline_stage", stage="extract"))
    assert mutation_conflicts(extracting, "account:book", "/story-bible/characters/char_001")


def test_removals_and_merges_also_wait_for_adaptation(tmp_path) -> None:
    adapting = _app(_job("adapt", tmp_path / "book" / "parts" / "part_0002",
                         kind="pipeline_stage", stage="adapt"))
    assert not mutation_conflicts(adapting, "account:book", "/story-bible/characters/char_001", method="PATCH")
    assert mutation_conflicts(adapting, "account:book", "/story-bible/characters/char_001", method="DELETE")
    assert mutation_conflicts(adapting, "account:book", "/story-bible/characters/char_001/merge")


def test_keeping_or_reopening_cast_waits_only_for_series_work(tmp_path) -> None:
    drawing = _app(_job("draw", tmp_path / "book" / "parts" / "part_0001"))
    assert not mutation_conflicts(drawing, "account:book", "/cast/references/keep")
    assert not mutation_conflicts(drawing, "account:book", "/cast/reopen")
    casting = _app(_job("cast", tmp_path / "book", kind="character_ref_regen", stage="cast"))
    assert mutation_conflicts(casting, "account:book", "/cast/references/keep")


def test_text_stages_use_the_light_lane_and_streams_are_per_part(tmp_path) -> None:
    assert is_light_job(_job("e", None, kind="pipeline_stage", stage="extract"))
    assert is_light_job(_job("b", None, kind="pipeline_stage", stage="brief"))
    assert not is_light_job(_job("a", None, kind="pipeline_stage", stage="adapt"))
    assert not is_light_job(_job("d", None))

    assert event_key("account:book", tmp_path / "book") == "account:book"
    assert event_key("account:book", tmp_path / "book" / "parts" / "part_0002") == "account:book/part_0002"
    assert event_key("account:book", part_id="part_0003") == "account:book/part_0003"


def test_a_part_stream_also_carries_series_events() -> None:
    import asyncio

    from novel_to_comic.server.event_channel import EventChannel
    from novel_to_comic.server.routers import pipeline

    series, part = EventChannel(), EventChannel()
    app = SimpleNamespace(state=SimpleNamespace(event_queues={"account:pid": series, "account:pid/part_0002": part}))

    class Request:
        path_params = {"part_id": "part_0002"}

        def __init__(self):
            self.app = app

        async def is_disconnected(self):
            return False

    async def exercise():
        stream = (await pipeline.event_stream(Request(), "pid", "account")).body_iterator
        series.put_nowait({"type": "pipeline_done", "stage": "cast"})  # series work ending doesn't close it
        first = await anext(stream)
        part.put_nowait({"type": "pipeline_done", "stage": "draw"})
        second = await anext(stream)
        return first, second, [chunk async for chunk in stream]

    first, second, rest = asyncio.run(exercise())
    assert '"cast"' in first and '"draw"' in second and rest == []
    assert not series.subscribers and not part.subscribers
