"""Credit balance and production-history endpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from novel_to_comic.codex_dev import is_subscription

from ..auth import get_current_user
from ..credits import get_balance_credits
from ..db import get_db

router = APIRouter()

_HISTORY_SELECT = (
    "id, amount_credits, status, stage, description, created_at, project_id, job_id, "
    "provider, model, provider_model, operation, input_tokens, output_tokens, image_count, "
    "cost_usd, cost_source, funding, usage_status"
)
_LEDGER_PAGE_SIZE = 1000


def _fetch_all_history_rows(
    db,
    user_id: str,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read complete ledger rows in bounded PostgREST pages.

    Grouping after a fixed row limit can cut a job in half and under-report its
    total. Fetching in pages keeps the endpoint correct without requiring a
    database migration or assuming a PostgREST server-row limit.
    """
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        query = (
            db.table("credit_ledger")
            .select(_HISTORY_SELECT)
            .eq("user_id", user_id)
        )
        if project_id is not None:
            query = query.eq("project_id", project_id)
        page = (
            query.order("created_at", desc=True)
            .range(start, start + _LEDGER_PAGE_SIZE - 1)
            .execute()
        ).data or []
        rows.extend(page)
        if len(page) < _LEDGER_PAGE_SIZE:
            return rows
        start += _LEDGER_PAGE_SIZE


def _history_run(row: dict[str, Any]) -> str:
    return str(row.get("job_id") or row["id"])


def _public_history_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return only customer-facing accounting facts, never provider internals."""
    return {
        key: row.get(key)
        for key in (
            "id",
            "amount_credits",
            "status",
            "stage",
            "created_at",
            "image_count",
        )
    }


def _group_history_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one canonical run shape for modern and legacy ledger rows."""
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_run[_history_run(row)].append(row)

    runs: list[dict[str, Any]] = []
    for run_id, run_rows in by_run.items():
        ordered = sorted(run_rows, key=lambda row: row["created_at"])
        reservation = next(
            (row for row in ordered if row.get("status") in {"reserved", "released"}),
            None,
        )
        settled = [row for row in ordered if row.get("status") == "settled"]
        estimate = abs(int(reservation["amount_credits"])) if reservation else 0
        actual = sum(
            abs(int(row["amount_credits"]))
            for row in settled
            if int(row["amount_credits"]) < 0
        )
        added = sum(
            int(row["amount_credits"])
            for row in settled
            if int(row["amount_credits"]) > 0
        )
        released = reservation is None or reservation.get("status") == "released"
        returned = max(0, estimate - actual) if released else 0
        if reservation and not released:
            status = "in_flight"
        elif any(
            is_subscription(row.get("funding"))
            and row.get("usage_status") in {"failed", "cancelled", "refused"}
            for row in settled
        ):
            status = "failed"
        elif reservation and not actual and not added:
            status = "failed"
        else:
            status = "complete"
        representative = reservation or (settled[0] if settled else ordered[0])
        runs.append(
            {
                "run_id": run_id,
                "job_id": representative.get("job_id"),
                "stage": representative.get("stage"),
                "project_id": representative.get("project_id"),
                "started_at": ordered[0]["created_at"],
                "last_activity_at": ordered[-1]["created_at"],
                "estimate_credits": estimate,
                "actual_credits": actual,
                "returned_credits": returned,
                "credits_added": added,
                "status": status,
                "rows": [_public_history_row(row) for row in ordered],
            }
        )
    return sorted(runs, key=lambda run: run["last_activity_at"], reverse=True)


def _month_used_credits(rows: list[dict[str, Any]]) -> int:
    now = datetime.now(UTC)
    prefix = f"{now.year:04d}-{now.month:02d}-"
    return sum(
        abs(int(row["amount_credits"]))
        for row in rows
        if row.get("status") == "settled"
        and int(row["amount_credits"]) < 0
        and str(row.get("created_at") or "").startswith(prefix)
    )


@router.get("/pricing-reference")
def pricing_reference():
    """Return guidance for the pricing reference display."""
    return {
        "notes": [
            "Costs are estimated where you start an action, using that project's model, quality, prompt size, and reference images.",
            "Final charges come from the model usage reported after the request finishes.",
            "Reservations can be higher than the final charge and are released after completion, reset, or failure.",
        ]
    }


@router.get("/balance")
def balance(user_id: str = Depends(get_current_user)):
    credits = get_balance_credits(get_db(), user_id)
    return {"balance_credits": credits}


@router.get("/history")
def history(
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    project_id: str | None = Query(default=None),
    user_id: str = Depends(get_current_user),
):
    rows = _fetch_all_history_rows(get_db(), user_id, project_id)
    runs = _group_history_runs(rows)
    page = runs[offset : offset + limit]
    return {
        "runs": page,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < len(runs),
        "month_used_credits": _month_used_credits(rows),
    }
