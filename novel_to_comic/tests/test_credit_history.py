from datetime import UTC, datetime, timedelta

from novel_to_comic.server.routers.credits import _group_history_runs


def _row(
    row_id: str,
    *,
    amount: int,
    status: str = "settled",
    stage: str | None = "draw",
    job_id: str | None = None,
    minute: int = 0,
):
    created = datetime(2026, 7, 15, 12, 0, tzinfo=UTC) + timedelta(minutes=minute)
    return {
        "id": row_id,
        "amount_credits": amount,
        "status": status,
        "stage": stage,
        "description": "Model call: draw.panel_image",
        "created_at": created.isoformat(),
        "project_id": "project-1",
        "job_id": job_id,
        "provider": "gemini",
        "model": "image-balanced",
        "provider_model": "gemini-3-pro-image",
        "operation": "image",
        "input_tokens": 0,
        "output_tokens": 0,
        "image_count": 1,
        "cost_usd": 0.134,
    }


def test_history_groups_every_row_in_a_large_job_before_summarizing():
    job_id = "00000000-0000-0000-0000-000000000001"
    rows = [
        _row("reservation", amount=-500, status="released", job_id=job_id),
        *[
            _row(f"call-{index}", amount=-1, job_id=job_id, minute=index + 1)
            for index in range(131)
        ],
    ]

    runs = _group_history_runs(rows)

    assert len(runs) == 1
    assert runs[0]["estimate_credits"] == 500
    assert runs[0]["actual_credits"] == 131
    assert runs[0]["returned_credits"] == 369
    assert len(runs[0]["rows"]) == 132


def test_legacy_rows_use_the_same_run_shape_without_being_coalesced():
    rows = [
        _row("legacy-debit", amount=-4, stage="style"),
        _row("purchase", amount=1200, stage=None, minute=1),
    ]

    runs = _group_history_runs(rows)

    assert [run["run_id"] for run in runs] == ["purchase", "legacy-debit"]
    assert runs[0]["credits_added"] == 1200
    assert runs[0]["status"] == "complete"
    assert runs[1]["actual_credits"] == 4
    assert runs[1]["status"] == "complete"


def test_released_zero_usage_run_is_failed_but_unreserved_zero_row_is_complete():
    job_id = "00000000-0000-0000-0000-000000000002"
    rows = [_row("reservation", amount=-10, status="released", job_id=job_id)]

    runs = _group_history_runs(rows)

    assert runs[0]["status"] == "failed"
    assert runs[0]["returned_credits"] == 10


def test_subscription_failure_has_history_without_claiming_a_charge():
    row = {
        **_row("subscription-call", amount=0, job_id="subscription-job"),
        "funding": "codex_subscription",
        "cost_usd": None,
        "usage_status": "failed",
    }
    run = _group_history_runs([row])[0]
    assert run["status"] == "failed"
    assert run["actual_credits"] == 0
    assert run["funding"] == ["codex_subscription"]
    assert run["rows"][0]["cost_usd"] is None
