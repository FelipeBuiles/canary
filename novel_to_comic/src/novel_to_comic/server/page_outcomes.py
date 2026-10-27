"""Author verdicts on rendered pages: the product's primary quality signal.

Each verdict is a content-free ``page_outcome`` product event naming the
render it judges and that render's generation. When the render's AI trace is
known, the verdict is also an ``$ai_metric`` on that trace, so it sits beside
the model, prompt and cost that produced the art. Recording never fails or
delays the author's action.
"""
from __future__ import annotations

import logging
import uuid

OUTCOMES = frozenset({
    "redraw_requested", "correction_submitted", "render_selected", "issue_reported",
    "issue_accepted", "issue_dismissed", "visual_review_requested", "replan_requested",
    "lettering_saved", "lettering_reset", "change_check_requested", "note_carried", "note_undone",
})
# Lettering is independent of the art; its verdicts never score the image.
# Checking draft changes precedes any verdict: the author has not asked for
# a redraw yet, and may not. A carried note changes the script or plan, not art.
_ART_VERDICTS = OUTCOMES - {"lettering_saved", "lettering_reset", "change_check_requested",
                             "note_carried", "note_undone"}


def record_page_outcome(app, outcome: str, *, user_id: str | None, project_id: str | None,
                        target, page_number: int, render_revision: int | None = None,
                        identity: str | None = None, category: str | None = None,
                        mode: str | None = None) -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown page outcome: {outcome}")
    try:
        from .lifecycle_events import capture
        from .telemetry import observe_ai_metric

        revision = render_revision if render_revision is not None else target.active_render_revision(page_number)
        provenance = None
        if revision is not None:
            try:
                provenance = target.read_provenance(page_number, revision)
            except Exception:
                provenance = None
        generation_id = provenance.usage.call_id if provenance is not None else None
        properties = {key: value for key, value in {
            "outcome": outcome, "page_number": page_number, "render_revision": revision,
            "generation_id": generation_id, "category": category, "mode": mode,
        }.items() if value is not None}
        capture(app, "page_outcome", f"{outcome}:{project_id}:{identity or uuid.uuid4()}",
                user_id=user_id, project_id=project_id, properties=properties)
        if outcome in _ART_VERDICTS and provenance is not None:
            observe_ai_metric(f"author_{outcome}", 1, trace_id=provenance.ai_trace_id,
                              parent_id=generation_id, user_id=user_id, project_id=project_id,
                              page_number=page_number, render_revision=revision, generation_id=generation_id, category=category)
    except Exception as exc:  # noqa: BLE001 - analytics never blocks the author
        logging.getLogger(__name__).warning("Page outcome capture failed outcome=%s type=%s",
                                            outcome, type(exc).__name__)
