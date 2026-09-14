from novel_to_comic.image_failure import classify_image_failure, user_message_for_image_failure


def test_classifies_common_panel_failures():
    cases = [
        (ValueError("shape_mismatch: generated image aspect 1.0"), "shape_mismatch"),
        (ValueError("finish_reason=safety"), "provider_blocked"),
        (RuntimeError("429 Resource has been exhausted"), "rate_limited"),
        (TimeoutError("provider timed out"), "timed_out"),
        (ConnectionError("connection refused"), "service_unavailable"),
        (
            RuntimeError(
                'wire image transport failed ({"failure": "gateway connection '
                'could not be established"})'
            ),
            "service_unavailable",
        ),
        (
            RuntimeError("gateway disconnected before sending a response"),
            "service_unavailable",
        ),
        (ValueError("The image provider returned an empty response"), "empty_response"),
        (ValueError("FAL_KEY is not set"), "configuration_error"),
        (ValueError("unexpected provider response"), "generation_error"),
    ]

    for error, expected in cases:
        assert classify_image_failure(error) == expected
        assert user_message_for_image_failure(expected).strip()


def test_classifies_aspect_mismatch_without_relying_on_exception_text():
    assert classify_image_failure(ValueError("invalid image"), shape_mismatch=True) == "shape_mismatch"


def test_classifies_openai_output_moderation_wrapped_by_gateway():
    error = ValueError(
        'AI gateway request failed for complete_page_draw: 400 Bad Request — '
        'litellm.BadRequestError: OpenAIException - {"error": {'
        '"code": "moderation_blocked", "moderation_details": {'
        '"moderation_stage": "output", "categories": ["other"]}}}'
    )
    assert classify_image_failure(error) == "provider_blocked"


def test_classifies_openai_policy_violation():
    assert classify_image_failure(
        ValueError('{"error": {"code": "content_policy_violation"}}')
    ) == "provider_blocked"
