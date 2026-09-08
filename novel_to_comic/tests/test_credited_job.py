"""Tests for the CreditedJob module (server/credited_job.py)."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch


from novel_to_comic.usage import ApiResult


def _make_app() -> MagicMock:
    """Create a minimal FastAPI-like app stub for generation job tests."""
    app = MagicMock()
    app.state.generation_jobs = {}
    app.state.generation_job_sequence = 0
    app.state.generation_queue = asyncio.Queue()
    return app


class TestEnqueueCreditedJob:
    def test_returns_existing_job_on_dedup(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job
        from novel_to_comic.server.generation_jobs import enqueue_generation_job

        app = _make_app()

        async def _noop():
            return ApiResult(value=None)

        # Pre-enqueue a matching job
        existing = enqueue_generation_job(
            app,
            project_name="proj",
            kind="char_regen",
            label="char / foo",
            payload={"char_id": "foo"},
            runner=_noop,
        )

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.reserve_credits", side_effect=AssertionError("duplicate reserved twice")):
            job, created = enqueue_credited_job(
                app,
                project_name="proj",
                user_id="u1",
                project_id="p1",
                project_dir=tmp_path,
                stage="cast",
                kind="char_regen",
                label="char / foo",
                payload={"char_id": "foo"},
                work=_noop,
                debit_description="test debit",
            )

        assert created is False
        assert job.id == existing.id


    def test_runner_skips_debit_when_no_usage(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job

        app = _make_app()

        async def _work():
            return ApiResult(value="ok", usage=None)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.reserve_credits", return_value=(None, "job")), \
             patch("novel_to_comic.server.credited_job.debit_model_usage") as mock_debit, \
             patch("novel_to_comic.server.credited_job.ai_request_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            job, _ = enqueue_credited_job(
                app,
                project_name="proj",
                user_id="u1",
                project_id="p1",
                project_dir=tmp_path,
                stage="cast",
                kind="char_regen",
                label="char",
                payload={"char_id": "c"},
                work=_work,
                debit_description="regen",
            )

            asyncio.run(job.runner())

        mock_debit.assert_not_called()

    def test_runner_clears_items_failed_cast_on_success(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job
        from novel_to_comic.state import create_initial_state, save_state, load_state

        # Setup initial state with a failed item
        state = create_initial_state("proj", "novel.txt")
        state.stages["cast"].items_failed = ["protagonist"]
        state.stages["cast"].items_done = 8
        state.stages["cast"].items_total = 10
        save_state(state, tmp_path)

        app = _make_app()

        async def _work():
            return ApiResult(value="ok", usage=None)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.reserve_credits", return_value=(None, "job")), \
             patch("novel_to_comic.server.credited_job.ai_request_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            job, _ = enqueue_credited_job(
                app,
                project_name="proj",
                user_id="u1",
                project_id="p1",
                project_dir=tmp_path,
                stage="cast",
                kind="character_ref_regen",
                label="char",
                payload={"char_id": "protagonist"},
                work=_work,
                debit_description="regen",
            )

            asyncio.run(job.runner())

        # Verify the item has been removed from items_failed in state.json
        loaded_state = load_state(tmp_path)
        assert "protagonist" not in loaded_state.stages["cast"].items_failed
        assert loaded_state.stages["cast"].items_done == 9

    def test_runner_clears_items_failed_draw_on_success(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job
        from novel_to_comic.state import create_initial_state, save_state, load_state

        # Setup initial state with a failed item
        state = create_initial_state("proj", "novel.txt")
        state.stages["draw"].items_failed = ["page_001"]
        state.stages["draw"].items_done = 5
        state.stages["draw"].items_total = 10
        save_state(state, tmp_path)

        app = _make_app()

        async def _work():
            return ApiResult(value="ok", usage=None)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.reserve_credits", return_value=(None, "job")), \
             patch("novel_to_comic.server.credited_job.ai_request_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            job, _ = enqueue_credited_job(
                app,
                project_name="proj",
                user_id="u1",
                project_id="p1",
                project_dir=tmp_path,
                stage="draw",
                kind="complete_page_draw",
                label="page",
                payload={"page_number": 1},
                work=_work,
                debit_description="regen",
            )

            asyncio.run(job.runner())

        # Verify the item has been removed from items_failed in state.json
        loaded_state = load_state(tmp_path)
        assert "page_001" not in loaded_state.stages["draw"].items_failed
        assert loaded_state.stages["draw"].items_done == 6


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
                page_number=7, estimated_cost_usd=0.02, work=work))
        assert reserve.call_args.args[-1] > 0
        release.assert_called_once_with(db.return_value, 'hold')
    assert current_ai_request_context().user_id is None


def test_expired_queued_job_never_calls_provider(tmp_path):
    import pytest
    from novel_to_comic.server.credited_job import enqueue_credited_job

    called = False

    async def work():
        nonlocal called
        called = True
        return ApiResult(value=None)

    with patch("novel_to_comic.server.credited_job.get_db"), \
         patch("novel_to_comic.server.credited_job.reserve_credits", return_value=("hold", "job")), \
         patch("novel_to_comic.server.credited_job.assert_reservation_active", side_effect=RuntimeError("lease expired")), \
         patch("novel_to_comic.server.credited_job.release_reservation"):
        job, _ = enqueue_credited_job(
            _make_app(), project_name="project", user_id="user", project_id=None,
            project_dir=tmp_path, stage="cast", kind="character_ref_regen",
            label="alice", payload={"char_id": "alice"}, work=work,
            debit_description="cast", estimate_credits=5,
        )
        with pytest.raises(RuntimeError, match="lease expired"):
            asyncio.run(job.runner())
    assert called is False
