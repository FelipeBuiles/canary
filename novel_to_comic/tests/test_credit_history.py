from datetime import UTC, datetime, timedelta

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from novel_to_comic.server.routers.credits import _group_history_runs, history


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
        "model": "image-gemini-pro",
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
    assert "funding" not in run
    assert "cost_usd" not in run["rows"][0]
    assert "provider" not in run["rows"][0]
    assert "model" not in run["rows"][0]
    assert "provider_model" not in run["rows"][0]


def test_history_can_scope_customer_safe_activity_to_one_project():
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.range.return_value = query
    query.execute.return_value = SimpleNamespace(data=[])

    with patch("novel_to_comic.server.routers.credits.get_db") as get_db:
        get_db.return_value.table.return_value = query
        result = history(limit=30, offset=0, project_id="project-1", user_id="user-1")

    assert ("user_id", "user-1") in [call.args for call in query.eq.call_args_list]
    assert ("project_id", "project-1") in [call.args for call in query.eq.call_args_list]
    assert result["runs"] == []


def _described(row_id: str, description: str, *, amount: int = -2, stage: str = "draw", job_id: str = "job-1", minute: int = 1):
    return {**_row(row_id, amount=amount, stage=stage, job_id=job_id, minute=minute), "description": description}


def test_rows_name_what_they_paid_for_without_model_internals():
    run = _group_history_runs([
        _described("hold", "Credit hold", amount=-40, minute=0) | {"status": "released"},
        _described("art", "Complete page 7"),
        _described("check", "Model call: draw.visual_review"),
        _described("retry", "Model call failed: draw.visual_review"),
        _described("legacy", "Model call: draw.panel_image"),
    ])[0]

    assert [row["label"] for row in run["rows"]] == [
        "Credit hold", "Page art", "Visual check", "Visual check", "Other steps",
    ]
    assert run["page_number"] == 7
    assert run["rows"][1]["page_number"] == 7
    assert run["rows"][2]["page_number"] is None
    assert run["action"] is None
    assert "description" not in run["rows"][1]


def test_targeted_actions_name_the_run_but_stage_runs_do_not():
    regen, plan = _group_history_runs([
        _described("ref", "Model call: regenerate character ref ana", stage="cast", job_id="regen"),
        _described("review", "Model call: cast.visual_review", stage="cast", job_id="regen", minute=2),
        _described("map", "Model call: plan.map", stage="plan", job_id="plan", minute=3),
        _described("detail", "Model call: plan.detail", stage="plan", job_id="plan", minute=4),
    ])[::-1]

    assert regen["action"] == "Character reference"
    assert [row["label"] for row in regen["rows"]] == ["Character reference", "Visual check"]
    assert plan["action"] is None
    assert [row["label"] for row in plan["rows"]] == ["Page map", "Page details"]


def test_history_totals_final_charges_by_stage_across_every_page():
    rows = [
        _described("a", "Complete page 1", amount=-3, job_id="d1"),
        _described("b", "Complete page 2", amount=-2, job_id="d2"),
        _described("c", "Model call: plan.map", amount=-5, stage="plan", job_id="p"),
        _described("hold", "", amount=-50, stage="plan", job_id="p") | {"status": "reserved"},
        _row("purchase", amount=1200, stage=None),
    ]
    query = MagicMock()
    for name in ("select", "eq", "order", "range"):
        getattr(query, name).return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)

    with patch("novel_to_comic.server.routers.credits.get_db") as get_db:
        get_db.return_value.table.return_value = query
        result = history(limit=1, offset=0, project_id=None, user_id="user-1")

    assert len(result["runs"]) == 1
    assert result["spend_by_stage"] == {"draw": 5, "plan": 5}
