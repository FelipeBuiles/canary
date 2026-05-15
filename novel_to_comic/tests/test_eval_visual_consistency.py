"""Unit tests for the VLM eval module — exercises the response-parsing path
without making any network calls."""

from pathlib import Path

from novel_to_comic.eval.visual_consistency import (
    PanelEvalResult,
    _parse_response,
)


def test_parse_response_well_formed_json():
    raw = (
        '{"identity_match": 0.85, "location_continuity": 0.6, '
        '"forbidden_text_present": false, "notes": "minor wardrobe drift"}'
    )
    result = _parse_response(Path("/tmp/p1.png"), raw, "gemini-2.5-flash-lite")
    assert isinstance(result, PanelEvalResult)
    assert result.identity_match == 0.85
    assert result.location_continuity == 0.6
    assert result.forbidden_text_present is False
    assert "wardrobe" in result.notes


def test_parse_response_handles_fenced_json():
    raw = (
        "```json\n"
        '{"identity_match": null, "location_continuity": 1.0, '
        '"forbidden_text_present": true, "notes": "neon sign visible"}'
        "\n```"
    )
    result = _parse_response(Path("/tmp/p2.png"), raw, "gemini-2.5-flash-lite")
    assert result.identity_match is None
    assert result.location_continuity == 1.0
    assert result.forbidden_text_present is True


def test_parse_response_returns_error_result_on_invalid_json():
    raw = "I cannot evaluate this image."
    result = _parse_response(Path("/tmp/p3.png"), raw, "gemini-2.5-flash-lite")
    # The result is still a PanelEvalResult; it just carries the raw response
    # and a notes message — no crash.
    assert result.identity_match is None
    assert "not valid JSON" in result.notes


def test_parse_response_clamps_notes_length():
    long_note = "x" * 1000
    raw = (
        f'{{"identity_match": 0, "location_continuity": 0, '
        f'"forbidden_text_present": false, "notes": "{long_note}"}}'
    )
    result = _parse_response(Path("/tmp/p4.png"), raw, "gemini-2.5-flash-lite")
    assert len(result.notes) <= 300
