"""Reservation admission errors must be actionable without retrying paid work."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError

from novel_to_comic.server.credits import reserve_credits
from novel_to_comic.server.credited_job import CreditReservationDenied, run_credited_stage
from novel_to_comic.config import Config
from novel_to_comic.state import PipelineState


def stale_hold_error():
    return APIError({"message": "Expired credit reservation requires reconciliation", "code": "P0001", "hint": None, "details": None})


def test_expired_hold_explains_maintenance_without_releasing_or_retrying():
    db = MagicMock()
    db.rpc.return_value.execute.side_effect = stale_hold_error()
    with pytest.raises(HTTPException) as result:
        reserve_credits(db, "user", "project", "extract", 10)
    assert result.value.status_code == 503
    assert result.value.detail["error"] == "credit_reservation_reconciliation"
    assert "No model request was started" in result.value.detail["message"]
    assert "recreating the project will not fix this" in result.value.detail["message"]
    assert db.rpc.call_count == 1
    assert db.rpc.call_args.args[0] == "reserve_stage_credits"


def test_other_database_errors_are_not_misdiagnosed():
    db = MagicMock()
    error = APIError({"message": "Database unavailable", "code": "P0001", "hint": None, "details": None})
    db.rpc.return_value.execute.side_effect = error
    with pytest.raises(APIError) as result:
        reserve_credits(db, "user", "project", "extract", 10)
    assert result.value is error


def test_blocked_reservation_never_enters_extraction(tmp_path):
    db = MagicMock()
    db.rpc.return_value.execute.side_effect = stale_hold_error()
    work = MagicMock()
    with patch("novel_to_comic.server.credited_job.get_db", return_value=db), \
         patch("novel_to_comic.server.credited_job.estimate_stage_credit_reservation", return_value=10):
        with pytest.raises(CreditReservationDenied, match="credit database needs maintenance"):
            asyncio.run(run_credited_stage(user_id="user", project_id="project", project_dir=tmp_path,
                                          config=Config(), state=PipelineState(project_name="demo", novel_path="story.txt", created_at=datetime.now(timezone.utc)), stage="extract", run=work))
    work.assert_not_called()


def test_restart_reserves_fresh_cost_before_running_and_releases_hold(tmp_path):
    work = AsyncMock()
    state = PipelineState(project_name="demo", novel_path="story.txt", created_at=datetime.now(timezone.utc))
    with patch("novel_to_comic.server.credited_job.get_db", return_value=MagicMock()), \
         patch("novel_to_comic.server.credited_job.estimate_stage_credit_reservation", side_effect=AssertionError("resume estimate used")), \
         patch("novel_to_comic.server.credited_job.estimate_adaptation_restart", return_value={"reserved_credits": 42}), \
         patch("novel_to_comic.server.credited_job.reserve_credits", return_value=("hold", "job")) as reserve, \
         patch("novel_to_comic.server.credited_job.assert_reservation_active") as active, \
         patch("novel_to_comic.server.credited_job.release_reservation") as release:
        async def execute():
            reserve.assert_called_once()
            assert reserve.call_args.args[-1] == 42
            active.assert_called_once()
            release.assert_not_called()
            await work()

        asyncio.run(run_credited_stage(user_id="user", project_id="project", project_dir=tmp_path,
                                      config=Config(), state=state, stage="adapt", run=execute, fresh_adaptation=True))
        work.assert_awaited_once()
        release.assert_called_once()
