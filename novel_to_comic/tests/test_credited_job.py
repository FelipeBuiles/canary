"""Production command admission, settlement, and cancellation boundaries."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from unittest.mock import patch

from novel_to_comic.server import credited_job, credits
from novel_to_comic.usage import ApiResult, UsageRecord
from tests.queue_fixtures import enqueue_test_operation


@pytest.fixture
def ledger(monkeypatch):
    db = object()
    reserve = MagicMock(return_value=("hold", "command-ledger-job"))
    release = MagicMock()
    debit = MagicMock()
    monkeypatch.setattr(credited_job, "get_db", lambda: db)
    monkeypatch.setattr(credited_job, "assert_sufficient_credits", lambda *a, **kw: None)
    monkeypatch.setattr("novel_to_comic.server.db.get_db", lambda: db)
    monkeypatch.setattr(credits, "reserve_credits", reserve)
    monkeypatch.setattr(credits, "release_reservation", release)
    monkeypatch.setattr(credits, "debit_model_usage", debit)
    monkeypatch.setattr(credits, "assert_reservation_active", lambda *a: None)
    yield SimpleNamespace(db=db, reserve=reserve, release=release, debit=debit)
    credits._unsettled_jobs.discard("command-ledger-job")


def admit(tmp_path, work, app=None, **kwargs):
    app = app or SimpleNamespace(state=SimpleNamespace(
        generation_jobs={}, generation_job_sequence=0, generation_queue=asyncio.Queue(),
    ))
    return app, enqueue_test_operation(app, project_name="u1:book", user_id="u1",
        project_id="book", project_dir=tmp_path, stage="cast", kind="project_cover",
        label="Cover", payload={}, work=work, debit_description="Cover",
        reservation_credits=5, operations=(("image", "image-gpt-2"),), **kwargs)


def test_duplicate_admission_and_queued_cancel_take_no_hold(tmp_path, ledger):
    async def forbidden():
        raise AssertionError("unstarted operation reached provider")
    app, (job, created) = admit(tmp_path, forbidden)
    _, (duplicate, created_again) = admit(tmp_path, forbidden, app)
    assert created and not created_again and duplicate is job
    ledger.reserve.assert_not_called()
    job.status = "cancelled"
    from novel_to_comic.server.generation_jobs import run_generation_job
    asyncio.run(run_generation_job(app, job))
    ledger.reserve.assert_not_called()
    ledger.release.assert_not_called()


def test_no_usage_releases_once_without_debit(tmp_path, ledger):
    async def work():
        from novel_to_comic.ai.context import current_ai_request_context
        assert current_ai_request_context().job_id == "command-ledger-job"
        return ApiResult(value="saved", usage=None)
    _, (job, _) = admit(tmp_path, work)
    ledger.reserve.assert_not_called()
    asyncio.run(job.runner())
    ledger.reserve.assert_called_once()
    assert ledger.reserve.call_args.kwargs["job_id"] == job.command.ledger_job_id
    ledger.debit.assert_not_called()
    ledger.release.assert_called_once_with(ledger.db, "hold")


def test_expired_execution_hold_never_calls_provider(tmp_path, ledger, monkeypatch):
    work = MagicMock(side_effect=AssertionError("expired hold reached provider"))
    monkeypatch.setattr(credits, "assert_reservation_active", MagicMock(side_effect=RuntimeError("lease expired")))
    _, (job, _) = admit(tmp_path, work)
    with pytest.raises(RuntimeError, match="lease expired"):
        asyncio.run(job.runner())
    work.assert_not_called()
    ledger.release.assert_called_once_with(ledger.db, "hold")


def test_completion_waits_for_every_debit_and_failed_settlement_never_completes(tmp_path, ledger):
    events = []
    usage = UsageRecord(provider="fixture", model="fixture", operation="text", input_tokens=1)
    async def work():
        return ApiResult(value="saved art", usage=usage, additional_usage=(usage,))
    def settle(*args, **kwargs):
        events.append("settled")
        if len(events) == 2:
            raise RuntimeError("ambiguous settlement")
    ledger.debit.side_effect = settle
    app, (job, _) = admit(tmp_path, work, on_settled=lambda result: events.append("complete"))
    from novel_to_comic.server.generation_jobs import run_generation_job
    async def handler(*args):
        return await work(), lambda result: events.append("complete")
    with patch("novel_to_comic.server.job_execution._operate", new=handler):
        asyncio.run(run_generation_job(app, job))
    assert events == ["settled", "settled"]
    ledger.release.assert_called_once_with(ledger.db, "hold")
    # run_generation_job reconstructs the production handler, so substitute only
    # the provider operation while keeping all state and settlement transitions.
    assert job.status == "failed"
    assert "complete" not in events


def test_page_check_sets_billing_context_and_releases_hold_on_failure(tmp_path):
    import pytest
    from novel_to_comic.ai.context import current_ai_request_context
    from novel_to_comic.server.credited_job import run_credited_page_check

    async def work():
        ctx = current_ai_request_context()
        assert (ctx.user_id, ctx.project_id, ctx.page_number, ctx.stage) == ('u1', 'p1', 7, 'draw')
        raise RuntimeError('vision service unavailable')

    with patch('novel_to_comic.server.credited_job.get_db') as db, \
         patch('novel_to_comic.server.credited_job.reserve_credits', return_value=('hold', 'job')) as reserve, \
         patch('novel_to_comic.server.credited_job.assert_reservation_active'), \
         patch('novel_to_comic.server.credited_job.release_reservation') as release:
        with pytest.raises(RuntimeError):
            asyncio.run(run_credited_page_check(user_id='u1', project_id='p1', project_dir=tmp_path,
                page_number=7, estimated_cost_usd=0.02, work=work, operations=(("text", "gemini-3.8-flash"),)))
        assert reserve.call_args.args[-1] > 0
        release.assert_called_once_with(db.return_value, 'hold')
    assert current_ai_request_context().user_id is None
