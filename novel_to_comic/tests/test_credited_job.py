"""Tests for the CreditedJob module (server/credited_job.py)."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch


from novel_to_comic.usage import ApiResult, UsageRecord


def _make_app() -> MagicMock:
    """Create a minimal FastAPI-like app stub for generation job tests."""
    app = MagicMock()
    app.state.generation_jobs = {}
    app.state.generation_job_sequence = 0
    app.state.generation_queue = asyncio.Queue()
    return app


def _dummy_usage() -> UsageRecord:
    return UsageRecord(
        provider="test",
        model="test-model",
        operation="image",
        image_count=1,
    )


class TestEnqueueCreditedJob:
    def test_returns_new_job_when_none_active(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job

        app = _make_app()

        async def _work():
            return ApiResult(value="done")

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits"):
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
                work=_work,
                debit_description="test debit",
            )

        assert created is True
        assert job.kind == "char_regen"
        assert job.payload == {"char_id": "foo"}

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
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits"):
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

    def test_calls_assert_credits_when_estimate_positive(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job

        app = _make_app()

        async def _work():
            return ApiResult(value=None)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits") as mock_assert:
            enqueue_credited_job(
                app,
                project_name="proj",
                user_id="u1",
                project_id="p1",
                project_dir=tmp_path,
                stage="draw",
                kind="panel_regen",
                label="panel",
                payload={},
                work=_work,
                debit_description="test",
                estimate_credits=5,
            )

        mock_assert.assert_called_once()
        call_kwargs = mock_assert.call_args
        assert call_kwargs[0][1] == "u1"
        assert call_kwargs[0][2] == 5

    def test_skips_assert_credits_when_estimate_zero(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job

        app = _make_app()

        async def _work():
            return ApiResult(value=None)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits") as mock_assert:
            enqueue_credited_job(
                app,
                project_name="proj",
                user_id="u1",
                project_id="p1",
                project_dir=tmp_path,
                stage="cast",
                kind="char_regen",
                label="char / foo",
                payload={"char_id": "foo"},
                work=_work,
                debit_description="test",
                estimate_credits=0,
            )

        mock_assert.assert_not_called()

    def test_runner_debits_on_success(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job

        app = _make_app()
        usage = _dummy_usage()

        async def _work():
            return ApiResult(value="ok", usage=usage)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits"), \
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
                debit_description="regen char c",
            )

            asyncio.run(job.runner())

        mock_debit.assert_called_once()
        debit_call = mock_debit.call_args
        assert debit_call[1]["description"] == "regen char c"
        assert debit_call[1]["stage"] == "cast"

    def test_runner_skips_debit_when_no_usage(self, tmp_path: Path):
        from novel_to_comic.server.credited_job import enqueue_credited_job

        app = _make_app()

        async def _work():
            return ApiResult(value="ok", usage=None)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits"), \
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
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits"), \
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
        state.stages["draw"].items_failed = ["scene_001/panel_001"]
        state.stages["draw"].items_done = 5
        state.stages["draw"].items_total = 10
        save_state(state, tmp_path)

        app = _make_app()

        async def _work():
            return ApiResult(value="ok", usage=None)

        with patch("novel_to_comic.server.credited_job.get_db"), \
             patch("novel_to_comic.server.credited_job.assert_sufficient_credits"), \
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
                kind="panel_regen",
                label="panel",
                payload={"scene_id": "scene_001", "panel_number": 1},
                work=_work,
                debit_description="regen",
            )

            asyncio.run(job.runner())

        # Verify the item has been removed from items_failed in state.json
        loaded_state = load_state(tmp_path)
        assert "scene_001/panel_001" not in loaded_state.stages["draw"].items_failed
        assert loaded_state.stages["draw"].items_done == 6
