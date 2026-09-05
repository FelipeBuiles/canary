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


def test_usage_endpoint_scopes_every_database_page_to_authenticated_owner(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    from novel_to_comic.server.routers.pages import project_provider_usage

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.range.return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    with patch('novel_to_comic.server.db.get_db') as db:
        db.return_value.table.return_value = query
        result = project_provider_usage('project-uuid', project_dir=tmp_path, user_id='owner-uuid')
    assert ('user_id', 'owner-uuid') in [call.args for call in query.eq.call_args_list]
    assert ('project_id', 'project-uuid') in [call.args for call in query.eq.call_args_list]
    assert result['known_cost_usd'] == 0


def test_usage_report_keeps_costs_when_artifact_linkage_is_unavailable(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    from novel_to_comic.server.routers.pages import project_provider_usage
    from novel_to_comic.target_artifacts import ArtifactMissing

    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.range.return_value = query
    query.execute.return_value = SimpleNamespace(data=[{'id': 'paid', 'stage': 'draw', 'status': 'succeeded', 'cost_usd': 0.14}])
    with patch('novel_to_comic.server.db.get_db') as db, \
         patch('novel_to_comic.project_usage.page_usage_links', side_effect=ArtifactMissing('comic_page', tmp_path / 'missing.json')):
        db.return_value.table.return_value = query
        result = project_provider_usage('project', project_dir=tmp_path, user_id='owner')
    assert result['known_cost_usd'] == 0.14
    assert result['complete'] is False
    assert result['artifact_link_error']
