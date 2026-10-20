"""Exercise frozen draw quote/admission/execution without a provider or ledger."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from novel_to_comic.config import Config
from novel_to_comic.server.draw_submission import (
    enqueue_complete_page_draw, execute_page_draw, quote_page_draw,
)
from novel_to_comic.target_artifacts import TargetArtifacts
from .test_complete_page_draw import (
    _compile, _make_app, _page, _provider_result, _RecordingTransport, _vertex_adapter,
)


class FakeLedger:
    def __init__(self):
        self.submissions = []

    async def admit(self, app, **submission):
        self.submissions.append(submission)
        job = SimpleNamespace(
            id="fake-draw", project_name=submission["project_name"], kind=submission["kind"],
            status="queued", payload=submission["payload"], command=submission["command"],
        )
        app.state.generation_jobs[job.id] = job
        return job, True


def test_quote_submit_execute_keeps_frozen_request_and_single_admission(tmp_path):
    app = _make_app(tmp_path)
    directory = tmp_path / "user-1" / "project"
    target = TargetArtifacts(directory)
    compiled = _compile(tmp_path)
    transport = _RecordingTransport(_provider_result())
    adapter = _vertex_adapter(transport)
    ledger = FakeLedger()
    config = Config()
    quote = quote_page_draw(config, compiled, checks=False)
    original = compiled.request.model_dump_json()
    inputs = dict(project_name="project", user_id="user-1", project_id="project-1",
                  project_dir=directory, config=config, compiled=compiled, adapter=adapter,
                  artifacts=target, page=_page(), ledger=ledger)

    async def action():
        (job, created), (shared, duplicated) = await asyncio.gather(
            enqueue_complete_page_draw(app, **inputs), enqueue_complete_page_draw(app, **inputs),
        )
        assert created and not duplicated and shared is job
        changed = _compile(tmp_path, page=_page(visual_intent="Changed instructions"))
        with pytest.raises(HTTPException) as error:
            await enqueue_complete_page_draw(app, **(inputs | {"compiled": changed}))
        assert error.value.status_code == 409
        result, settled = await execute_page_draw(app, job, directory, config, adapter=adapter)
        return result

    asyncio.run(action())
    assert len(ledger.submissions) == 1
    assert ledger.submissions[0]["reservation_credits"] == quote["reserved_credits"]
    assert compiled.request.model_dump_json() == original
    assert target.read_request(7, 1).model_dump_json() == original
    assert target.read_render(7, 1) == b"complete-page-png"


def test_initial_batch_and_review_preparation_keep_the_same_frozen_inputs(tmp_path, monkeypatch):
    from novel_to_comic import page_draw_preparation
    from novel_to_comic.server import draw_submission
    from novel_to_comic.page_drawing import (
        compile_page_generation_request, ensure_current_page_edition, select_book_edition,
    )
    from novel_to_comic.page_visual_review import compile_visual_review
    from novel_to_comic.models.draw import RetryProvenance
    from .test_complete_page_draw import _edition, _inventory, _reference_files

    _make_app(tmp_path)
    directory = tmp_path / "user-1" / "project"
    target = TargetArtifacts(directory)
    target.write_book_edition(_edition())
    config = Config()
    edition = ensure_current_page_edition(target, target.read_book_edition(), config)
    files, inventory = _reference_files(directory), _inventory()
    monkeypatch.setattr(page_draw_preparation, "approved_reference_files", lambda path: files)
    monkeypatch.setattr(page_draw_preparation, "approved_visual_inventory", lambda path: inventory)
    monkeypatch.setattr(draw_submission, "require_draw_narrative_reviews", lambda target: None)
    page = target.read_page(7)
    expected = compile_page_generation_request(
        page, edition, inventory, files, retry=RetryProvenance(attempt=1),
        style_template=config.style_template,
    )
    before = target.book_edition_path.read_bytes()
    _, _, initial = draw_submission.prepare_initial_generation((directory, config, None), 7, "canonical", persist=False)
    _, _, batch = draw_submission.prepare_undrawn_pages(project_dir=directory, config=config, pages=frozenset({7}))
    review = compile_visual_review(directory, config, target, page)
    for compiled in (initial, batch[0][2], review):
        assert compiled.request.model_dump_json() == expected.request.model_dump_json()
        assert compiled.reference_bytes == expected.reference_bytes
    assert target.book_edition_path.read_bytes() == before
    # The stage-wide quote retains its historical synthetic identity and retry.
    quote = page_draw_preparation.DrawPreparation.load(target, config, quote_identity=True)
    quoted = quote.compile(page, retry=RetryProvenance(attempt=1))
    legacy_quote = compile_page_generation_request(
        page, select_book_edition(edition_id="estimate", profile=edition.capability_profile),
        inventory, files, retry=RetryProvenance(attempt=1), style_template=config.style_template,
    )
    assert quoted.request.model_dump_json() == legacy_quote.request.model_dump_json()


def test_batch_with_a_busy_page_is_refused_before_any_page_is_admitted(tmp_path):
    from novel_to_comic.server.draw_submission import require_batch_not_busy

    app = _make_app(tmp_path)
    directory = tmp_path / "user-1" / "project"
    target = TargetArtifacts(directory)
    compiled = _compile(tmp_path)
    ledger = FakeLedger()
    asyncio.run(enqueue_complete_page_draw(
        app, project_name="project", user_id="user-1", project_id="project-1",
        project_dir=directory, config=Config(), compiled=compiled,
        adapter=_vertex_adapter(_RecordingTransport(_provider_result())),
        artifacts=target, page=_page(), ledger=ledger,
    ))
    same = (7, _page(), compiled)
    changed = (7, _page(), _compile(tmp_path, page=_page(visual_intent="Changed instructions")))

    require_batch_not_busy(app, project_name="project", project_dir=directory, prepared=[same])
    with pytest.raises(HTTPException) as error:
        require_batch_not_busy(app, project_name="project", project_dir=directory, prepared=[same, changed])
    assert error.value.status_code == 409
    assert len(ledger.submissions) == 1
