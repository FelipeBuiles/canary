"""Indexed operation summaries; bulky executable commands have a separate lifetime."""

import json


def initialize(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS jobs_status ON jobs(json_extract(payload,'$.status'))"
    )


def history(app, project, *, ids=None, part=None, before=None, limit=100):
    clauses, values = ["project=?"], [project]
    if ids is not None:
        if not ids:
            return [], None
        clauses.append("id IN (" + ",".join("?" for _ in ids) + ")")
        values.extend(ids)
    if part:
        clauses.append(
            "(json_extract(payload,'$.part_id')=? OR json_extract(payload,'$.part_id') IS NULL)"
        )
        values.append(part)
    if before is not None:
        clauses.append("rowid < ?")
        values.append(before)
    limit = min(max(limit, 1), 200)
    with app.state.admission.journal() as db:
        rows = db.execute(
            "SELECT rowid,payload FROM jobs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY rowid DESC LIMIT ?",
            (*values, limit + 1),
        ).fetchall()
    return [json.loads(raw) for _, raw in rows[:limit]], rows[limit - 1][0] if len(
        rows
    ) > limit else None
