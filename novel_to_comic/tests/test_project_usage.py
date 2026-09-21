from novel_to_comic.project_usage import summarize_provider_usage


def test_provider_costs_count_failures_once_and_preserve_unknowns():
    events = [
        {"id": "image", "stage": "draw", "status": "succeeded", "cost_usd": 0.14},
        {"id": "edit", "stage": "draw", "status": "failed", "cost_usd": 0.09},
        {
            "id": "ocr",
            "stage": "draw",
            "feature": "draw.page_ocr",
            "status": "failed",
            "cost_usd": None,
        },
    ]
    links = {
        "image": {"page_number": 1, "category": "generation"},
        "edit": {"page_number": 1, "category": "correction"},
        "lost-event": {"page_number": 2, "category": "generation"},
    }
    result = summarize_provider_usage([*events, events[0]], links)
    assert result["known_cost_usd"] == 0.23
    assert result["call_count"] == 3
    assert result["failed_call_count"] == 2
    assert result["unknown_cost_count"] == 1
    assert result["artifact_calls_missing_from_events"] == 1
    assert result["complete"] is False
    assert {group["category"] for group in result["groups"]} == {
        "generation",
        "correction",
        "ocr",
    }


def test_subscription_unknown_cost_remains_unknown_in_funding_summary():
    event = {
        "id": "subscription", "stage": "extract", "status": "failed",
        "funding": "codex_subscription", "cost_usd": None,
        "cost_source": "codex_subscription",
    }
    result = summarize_provider_usage([event, event], {})
    assert result["funding_counts"] == {"codex_subscription": 1}
    assert result["unknown_cost_count"] == 1
    assert result["failed_call_count"] == 1
    assert result["complete"] is False
    assert result["groups"][0]["funding_counts"] == {"codex_subscription": 1}
