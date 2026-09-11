import sys
import hashlib
import json
from pathlib import Path
import pytest
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[2]))

from litellm_handlers.vertex_multimodal import (
    _extract_image,
    _estimated_image_cost,
    _image_config_kwargs,
    _image_size_for_dimensions,
    _map_to_supported_aspect,
    _exact_complete_page_contents,
    _parse_complete_page_request,
    _requires_native_aspect_control,
    _translate_vertex_error,
    _verify_complete_page_images,
    litellm,
)


def _complete_page_manifest() -> dict:
    payload = {
        "page_number": 1,
        "prompt": "Render one complete page.",
        "artifact_kind": "complete_page",
        "references": [
            {
                "id": "ward-ref",
                "order": 1,
                "content_sha256": hashlib.sha256(b"ward").hexdigest(),
                "entity_id": "ward",
                "appearance_state_id": "ward-bloodied",
                "visual_anchor": "blood below the right eye",
            }
        ],
    }
    payload["request_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return payload


def test_complete_page_manifest_binds_exact_ordered_bytes_and_prompt():
    raw = _complete_page_manifest()
    manifest = _parse_complete_page_request(json.dumps(raw))
    _verify_complete_page_images(manifest, [("ward.png", b"ward", "image/png")])

    marker = object()
    contents = _exact_complete_page_contents(manifest, [marker])

    assert contents[0] is marker
    assert contents[-1] == "Render one complete page."


def test_complete_page_correction_accepts_parent_render_before_references():
    raw = _complete_page_manifest()
    raw["correction"] = {
        "issue_id": "issue-lettering",
        "parent_render_revision": 1,
        "parent_render_image_sha256": hashlib.sha256(b"parent-page").hexdigest(),
        "instruction": "Correct the visible lettering.",
    }
    raw["request_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in raw.items() if key != "request_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    manifest = _parse_complete_page_request(json.dumps(raw))
    images = [
        ("complete-page-edit-source.png", b"parent-page", "image/png"),
        ("ward.png", b"ward", "image/png"),
    ]

    _verify_complete_page_images(manifest, images)
    parent_part = object()
    reference_part = object()
    contents = _exact_complete_page_contents(
        manifest,
        [parent_part, reference_part],
    )

    assert contents[0] is parent_part
    assert contents[2] is reference_part
    assert contents[-1] == "Render one complete page."
    # A correction parent must never shift the approved image's binding.
    initial_contents = _exact_complete_page_contents(
        _complete_page_manifest(), [reference_part],
    )
    assert contents[3] == initial_contents[1]


def test_complete_page_count_mismatch_reports_safe_request_shape():
    raw = _complete_page_manifest()
    raw["correction"] = {
        "issue_id": "issue-lettering",
        "parent_render_revision": 1,
        "parent_render_image_sha256": hashlib.sha256(b"parent-page").hexdigest(),
        "instruction": "Correct the visible lettering.",
    }
    raw["request_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in raw.items() if key != "request_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    manifest = _parse_complete_page_request(json.dumps(raw))

    with pytest.raises(
        ValueError,
        match=(
            r"expected=2, received=1, references=1, correction=True, "
            r"files=\['complete-page-ref-1'\]"
        ),
    ):
        _verify_complete_page_images(
            manifest,
            [("complete-page-ref-1", b"ward", "image/png")],
        )


def test_complete_page_manifest_rejects_tampering():
    raw = _complete_page_manifest()
    raw["prompt"] = "Render a panel instead."

    with pytest.raises(ValueError, match="identity mismatch"):
        _parse_complete_page_request(json.dumps(raw))


def test_landscape_aspect_maps_to_native_gemini_mode():
    assert _map_to_supported_aspect(1344 / 768) == "16:9"
    assert _map_to_supported_aspect(768 / 1344) == "9:16"
    assert _image_config_kwargs(1344 / 768, "medium") == {
        "aspect_ratio": "16:9",
        "image_size": "2K",
    }


def test_flash_lite_image_clamps_unsupported_resolution_to_1k():
    assert _image_config_kwargs(
        4 / 5,
        "medium",
        model="gemini-3.1-flash-lite-image",
    ) == {
        "aspect_ratio": "4:5",
        "image_size": "1K",
    }


def test_complete_page_dimensions_select_native_2k_output():
    assert _image_size_for_dimensions(2048, 3072) == "2K"
    assert _image_config_kwargs(
        2 / 3,
        None,
        model="gemini-3-pro-image",
        image_size="2K",
    ) == {
        "aspect_ratio": "2:3",
        "image_size": "2K",
    }


def test_gemini_pro_ga_model_uses_current_image_and_reference_costs():
    assert _estimated_image_cost(
        "gemini-3-pro-image",
        2,
        image_size="2K",
    ) == pytest.approx(0.13624)


def test_legacy_vertex_sdk_can_safely_omit_square_aspect_control():
    assert not _requires_native_aspect_control(None)
    assert not _requires_native_aspect_control("1:1")
    assert _requires_native_aspect_control("16:9")
    assert _requires_native_aspect_control("9:16")


def test_translate_vertex_error_rate_limit():
    # Mock Vertex/Google GenAI error with code 429
    exc = Exception("Rate limit reached")
    exc.code = 429
    exc.status = "RESOURCE_EXHAUSTED"
    exc.message = "Resource has been exhausted"

    translated = _translate_vertex_error(exc, "gemini-3-pro-image")
    assert isinstance(translated, litellm.RateLimitError)
    assert "Vertex image generation failed" in str(translated)
    assert "RESOURCE_EXHAUSTED" in str(translated)


def test_translate_vertex_error_other_api_error():
    # Mock other Vertex API error
    exc = Exception("Bad request parameter")
    exc.code = 400
    exc.status = "INVALID_ARGUMENT"
    exc.message = "Invalid image size"

    translated = _translate_vertex_error(exc, "gemini-3-pro-image")
    assert isinstance(translated, litellm.APIError)
    assert translated.status_code == 400
    assert "Vertex image generation failed" in str(translated)
    assert "INVALID_ARGUMENT" in str(translated)


def test_translate_vertex_error_includes_safe_request_context():
    exc = Exception("Request contains an invalid argument")
    exc.code = 400
    exc.status = "INVALID_ARGUMENT"

    translated = _translate_vertex_error(
        exc,
        "gemini-3.1-flash-lite-image",
        request_context=(
            "model=gemini-3.1-flash-lite-image, location=global, "
            "image_config={'aspect_ratio': '4:5', 'image_size': '1K'}"
        ),
    )

    assert "model=gemini-3.1-flash-lite-image" in str(translated)
    assert "image_size': '1K'" in str(translated)


def test_extract_image_safety_block_diagnostics():
    # Simulate a response with no candidates but prompt feedback showing a safety block
    mock_rating = SimpleNamespace(category="HARM_CATEGORY_DANGEROUS_CONTENT", probability="HIGH", blocked=True)
    mock_feedback = SimpleNamespace(block_reason="SAFETY", safety_ratings=[mock_rating])
    response = SimpleNamespace(candidates=[], prompt_feedback=mock_feedback)

    with pytest.raises(litellm.APIError) as excinfo:
        _extract_image(response)

    err_msg = str(excinfo.value)
    assert excinfo.value.status_code == 400
    assert "no candidates returned" in err_msg
    assert "prompt_feedback: block_reason=SAFETY" in err_msg
    assert "HARM_CATEGORY_DANGEROUS_CONTENT(prob=HIGH, blocked=True)" in err_msg


def test_extract_image_other_prompt_block_is_a_typed_refusal():
    response = SimpleNamespace(
        candidates=None,
        prompt_feedback=SimpleNamespace(
            block_reason="OTHER",
            safety_ratings=None,
        ),
    )

    with pytest.raises(litellm.APIError) as excinfo:
        _extract_image(response)

    assert excinfo.value.status_code == 400
    assert "prompt_feedback: block_reason=OTHER" in str(excinfo.value)


def test_extract_image_candidate_finish_reason_diagnostics():
    # Simulate a candidate with safety block finish reason
    mock_rating = SimpleNamespace(category="HARM_CATEGORY_HARASSMENT", probability="MEDIUM", blocked=True)
    mock_candidate = SimpleNamespace(
        content=None,
        finish_reason="SAFETY",
        finish_message="Candidate blocked by safety",
        safety_ratings=[mock_rating]
    )
    response = SimpleNamespace(candidates=[mock_candidate], prompt_feedback=None)

    with pytest.raises(litellm.APIError) as excinfo:
        _extract_image(response)

    assert excinfo.value.status_code == 400
    err_msg = str(excinfo.value)
    assert "candidate #0" in err_msg
    assert "finish_reason=SAFETY" in err_msg
    assert "finish_message=Candidate blocked by safety" in err_msg
    assert "HARM_CATEGORY_HARASSMENT(prob=MEDIUM, blocked=True)" in err_msg


@pytest.mark.parametrize("reason", ["IMAGE_PROHIBITED_CONTENT", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "SAFETY"])
def test_candidate_policy_refusal_is_not_an_ambiguous_server_error(reason):
    response = SimpleNamespace(candidates=[SimpleNamespace(
        content=None, finish_reason=reason, finish_message="Blocked", safety_ratings=None,
    )], prompt_feedback=None, model_version="gemini-3-pro-image")
    with pytest.raises(litellm.APIError) as error:
        _extract_image(response)
    assert error.value.status_code == 400


def test_empty_image_with_unknown_finish_reason_remains_ambiguous():
    response = SimpleNamespace(candidates=[SimpleNamespace(
        content=None, finish_reason="STOP", finish_message=None, safety_ratings=None,
    )], prompt_feedback=None)
    with pytest.raises(ValueError, match="did not contain image bytes"):
        _extract_image(response)
