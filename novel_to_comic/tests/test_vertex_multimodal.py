import sys
from pathlib import Path
import pytest
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[2]))

from litellm_handlers.vertex_multimodal import (
    _extract_image,
    _image_config_kwargs,
    _map_to_supported_aspect,
    _translate_vertex_error,
    litellm,
)


def test_landscape_aspect_maps_to_native_gemini_mode():
    assert _map_to_supported_aspect(1344 / 768) == "16:9"
    assert _map_to_supported_aspect(768 / 1344) == "9:16"
    assert _image_config_kwargs(1344 / 768, "medium") == {
        "aspect_ratio": "16:9",
        "image_size": "2K",
    }


def test_translate_vertex_error_rate_limit():
    # Mock Vertex/Google GenAI error with code 429
    exc = Exception("Rate limit reached")
    exc.code = 429
    exc.status = "RESOURCE_EXHAUSTED"
    exc.message = "Resource has been exhausted"

    translated = _translate_vertex_error(exc, "gemini-3-pro-image-preview")
    assert isinstance(translated, litellm.RateLimitError)
    assert "Vertex image generation failed" in str(translated)
    assert "RESOURCE_EXHAUSTED" in str(translated)


def test_translate_vertex_error_other_api_error():
    # Mock other Vertex API error
    exc = Exception("Bad request parameter")
    exc.code = 400
    exc.status = "INVALID_ARGUMENT"
    exc.message = "Invalid image size"

    translated = _translate_vertex_error(exc, "gemini-3-pro-image-preview")
    assert isinstance(translated, litellm.APIError)
    assert translated.status_code == 400
    assert "Vertex image generation failed" in str(translated)
    assert "INVALID_ARGUMENT" in str(translated)


def test_extract_image_safety_block_diagnostics():
    # Simulate a response with no candidates but prompt feedback showing a safety block
    mock_rating = SimpleNamespace(category="HARM_CATEGORY_DANGEROUS_CONTENT", probability="HIGH", blocked=True)
    mock_feedback = SimpleNamespace(block_reason="SAFETY", safety_ratings=[mock_rating])
    response = SimpleNamespace(candidates=[], prompt_feedback=mock_feedback)

    with pytest.raises(ValueError) as excinfo:
        _extract_image(response)

    err_msg = str(excinfo.value)
    assert "no candidates returned" in err_msg
    assert "prompt_feedback: block_reason=SAFETY" in err_msg
    assert "HARM_CATEGORY_DANGEROUS_CONTENT(prob=HIGH, blocked=True)" in err_msg


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

    with pytest.raises(ValueError) as excinfo:
        _extract_image(response)

    err_msg = str(excinfo.value)
    assert "candidate #0" in err_msg
    assert "finish_reason=SAFETY" in err_msg
    assert "finish_message=Candidate blocked by safety" in err_msg
    assert "HARM_CATEGORY_HARASSMENT(prob=MEDIUM, blocked=True)" in err_msg
