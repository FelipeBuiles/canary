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
