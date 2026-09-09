"""Reconcile provider events with page artifacts without confusing costs and credits."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from novel_to_comic.target_artifacts import TargetArtifacts


def page_usage_links(artifacts: TargetArtifacts) -> dict[str, dict[str, Any]]:
    links = {}
    if not artifacts.plan_path.exists():
        return links
    for selected in artifacts.read_plan().pages:
        number = selected.page_number
        for revision in artifacts.provenance_revisions(number):
            provenance = artifacts.read_provenance(number, revision)
            links[provenance.usage.call_id] = {
                "page_number": number,
                "category": "correction"
                if provenance.render.parent_revision
                else "generation",
            }
            if artifacts.analysis_path(number, revision).exists():
                analysis = artifacts.read_analysis(number, revision)
                if analysis.analysis_usage:
                    links[analysis.analysis_usage.call_id] = {
                        "page_number": number,
                        "category": "ocr",
                    }
            for report in artifacts.read_visual_reviews(number, revision):
                if report.usage:
                    links[report.usage.call_id] = {
                        "page_number": number,
                        "category": "visual_review",
                    }
    return links


def summarize_provider_usage(
    events: Iterable[dict[str, Any]], links: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Each event counts once; unknown costs remain unknown, including failures."""
    groups: dict[tuple[int | None, str], dict[str, Any]] = {}
    seen = set()
    total = Decimal("0")
    unknown = 0
    failed = 0
    cost_sources: dict[str, int] = {}
    funding_counts: dict[str, int] = {}
    for event in events:
        event_id = str(event["id"])
        if event_id in seen:
            continue
        seen.add(event_id)
        funding = str(event.get("funding") or "api")
        funding_counts[funding] = funding_counts.get(funding, 0) + 1
        link = links.get(event_id, {})
        feature = str(event.get("feature") or "")
        metadata = event.get("metadata_json") or {}
        page_number = link.get("page_number", metadata.get("page_number"))
        if not isinstance(page_number, int) or page_number < 1:
            page_number = None
        category = link.get("category") or (
            "ocr"
            if feature == "draw.page_ocr"
            else "visual_review"
            if feature == "draw.visual_review"
            else "correction"
            if metadata.get("is_correction")
            else "generation"
            if event.get("stage") == "draw"
            else str(event.get("stage") or "other")
        )
        key = (page_number, category)
        group = groups.setdefault(
            key,
            {
                "page_number": page_number,
                "category": category,
                "call_count": 0,
                "failed_call_count": 0,
                "unknown_cost_count": 0,
                "known_cost_usd": Decimal("0"),
                "funding_counts": {},
            },
        )
        group["call_count"] += 1
        group["funding_counts"][funding] = group["funding_counts"].get(funding, 0) + 1
        if event.get("status") in {"failed", "cancelled"}:
            failed += 1
            group["failed_call_count"] += 1
        source = str(event.get("cost_source") or "unspecified")
        cost_sources[source] = cost_sources.get(source, 0) + 1
        cost = event.get("cost_usd")
        if cost is None:
            unknown += 1
            group["unknown_cost_count"] += 1
        else:
            amount = Decimal(str(cost))
            total += amount
            group["known_cost_usd"] += amount
    missing = len(set(links) - seen)
    return {
        "source": "provider_usage_events",
        "cost_sources": cost_sources,
        "funding_counts": funding_counts,
        "known_cost_usd": float(total),
        "call_count": len(seen),
        "failed_call_count": failed,
        "unknown_cost_count": unknown,
        "artifact_calls_missing_from_events": missing,
        "complete": unknown == 0 and missing == 0,
        "groups": [
            {**group, "known_cost_usd": float(group["known_cost_usd"])}
            for _, group in sorted(
                groups.items(), key=lambda pair: (pair[0][0] or 0, pair[0][1])
            )
        ],
    }
