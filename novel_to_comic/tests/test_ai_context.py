from novel_to_comic.ai import AIRequestContext, ai_request_context, current_ai_request_context


def test_default_ai_request_context_is_empty():
    assert current_ai_request_context() == AIRequestContext()


def test_ai_request_context_sets_and_resets_values():
    with ai_request_context(
        user_id="user-1",
        project_id="project-1",
        project_name="Test Project",
        workspace_id="workspace-1",
        stage="extract",
        request_id="request-1",
    ) as context:
        assert context.user_id == "user-1"
        assert current_ai_request_context() == context

    assert current_ai_request_context() == AIRequestContext()


def test_nested_ai_request_context_restores_outer_context():
    with ai_request_context(user_id="outer") as outer:
        with ai_request_context(user_id="inner") as inner:
            assert current_ai_request_context() == inner
        assert current_ai_request_context() == outer
