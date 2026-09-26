#!/usr/bin/env python3
"""Write a first-party weekly evidence note. No model calls or inferred sentiment.

Run with the application's environment and Python, e.g.
  python scripts/launch_learning_report.py --since 2026-09-26 --output work/learning.md
Review PostHog ordered funnels and private feedback before filling conclusions.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from novel_to_comic.server.db import get_db


def report(events, feedback, since):
    counts = Counter(row["event_name"] for row in events)
    users = {row["user_id"] for row in events if row.get("user_id")}
    categories = Counter(row["category"] for row in feedback)
    lines = [f"# Launch learning review: {since}", "", "Status: Evidence snapshot; conclusions require review.", "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}", f"Observed accounts: {len(users)}", "",
        "## Observed milestones", "", "These are event counts, not ordered conversion rates or proof of satisfaction.", "",
        "| Event | Count |", "| --- | ---: |"]
    lines += [f"| {name} | {count} |" for name, count in sorted(counts.items())]
    lines += ["", "## Feedback", "", "| Category | Count |", "| --- | ---: |"]
    lines += [f"| {name} | {count} |" for name, count in sorted(categories.items())]
    lines += ["", "## Learning to document", "",
        "- Question: Can a new author reach a useful first export independently?",
        "- Cohort and observation window: [Define; exclude staff/test traffic.]",
        "- Evidence: [Link the PostHog funnel and private feedback references.]",
        "- Finding: [Observed behavior; do not infer a reason for silence.]",
        "- Counter-evidence and uncertainty: [Include incomplete windows and low counts.]",
        "- Decision: [One change, or deliberately no change.]",
        "- Next review: [Date and the outcome that would change the decision.]", ""]
    return "\n".join(lines)


def rows(db, table, fields, since):
    offset = 0
    while True:
        result = db.table(table).select(fields).gte("occurred_at" if table == "product_events" else "created_at", since).order("id").range(offset, offset + 999).execute().data or []
        yield from result
        if len(result) < 1000:
            return
        offset += 1000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, type=lambda text: datetime.fromisoformat(text).isoformat())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    db = get_db()
    text = report(list(rows(db, "product_events", "id,event_name,user_id,occurred_at", args.since)),
                  list(rows(db, "customer_feedback", "id,category,created_at", args.since)), args.since)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
