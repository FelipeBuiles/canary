"""Tests for narration_editor — estimate_patch_impact and apply_patch."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from novel_to_comic.models.layout_plan import (
    LayoutPlan,
    LayoutPlanMetadata,
    NarrationDecision,
)


def _metadata() -> LayoutPlanMetadata:
    return LayoutPlanMetadata(
        source_screenplay_hash="abc123",
        max_panels_per_page=6,
    )


def _decision(beat_id: str = "beat_001") -> NarrationDecision:
    return NarrationDecision(
        beat_id=beat_id,
        scene_id="scene_01",
        beat_index=0,
        source_text="The rain fell hard.",
        decision="dropped",
        decision_reason="Not needed",
    )


def _plan(decisions: list[NarrationDecision] | None = None) -> LayoutPlan:
    return LayoutPlan(
        metadata=_metadata(),
        narration_decisions=decisions if decisions is not None else [_decision()],
    )


class TestEstimatePatchImpact:
    def test_returns_impact_bundle_without_saving(self, tmp_path: Path):
        from novel_to_comic.server.narration_editor import estimate_patch_impact

        mock_config = MagicMock()
        mock_state = MagicMock()

        with patch("novel_to_comic.server.narration_editor.load_layout_plan") as mock_load, \
             patch("novel_to_comic.server.narration_editor.save_layout_plan") as mock_save, \
             patch("novel_to_comic.server.narration_editor.estimate_stage_credit_breakdown") as mock_credits:
            mock_load.return_value = _plan()
            mock_credits.return_value = MagicMock(
                estimate_credits=10, reserved_credits=15, confidence="low"
            )

            result = estimate_patch_impact(
                tmp_path, "beat_001", {"caption_text_override": "Hello"}, mock_config, mock_state
            )

        mock_save.assert_not_called()
        assert "impact" in result
        assert "affected_stages" in result
        assert "estimated_credits" in result

    def test_raises_key_error_for_unknown_beat(self, tmp_path: Path):
        from novel_to_comic.server.narration_editor import estimate_patch_impact

        mock_config = MagicMock()
        mock_state = MagicMock()

        with patch("novel_to_comic.server.narration_editor.load_layout_plan") as mock_load, \
             patch("novel_to_comic.server.narration_editor.estimate_stage_credit_breakdown"):
            mock_load.return_value = _plan(decisions=[])

            with pytest.raises(KeyError):
                estimate_patch_impact(
                    tmp_path, "nonexistent", {"caption_text_override": "x"}, mock_config, mock_state
                )


class TestApplyPatch:
    def test_saves_plan_after_patch(self, tmp_path: Path):
        from novel_to_comic.server.narration_editor import apply_patch

        with patch("novel_to_comic.server.narration_editor.load_layout_plan") as mock_load, \
             patch("novel_to_comic.server.narration_editor.save_layout_plan") as mock_save:
            mock_load.return_value = _plan()

            decision, impact = apply_patch(tmp_path, "beat_001", {"caption_text_override": "Hello"})

        mock_save.assert_called_once()
        assert decision.beat_id == "beat_001"
        assert "impact" in impact

    def test_returns_updated_decision_fields(self, tmp_path: Path):
        from novel_to_comic.server.narration_editor import apply_patch

        with patch("novel_to_comic.server.narration_editor.load_layout_plan") as mock_load, \
             patch("novel_to_comic.server.narration_editor.save_layout_plan"):
            mock_load.return_value = _plan()

            decision, _ = apply_patch(tmp_path, "beat_001", {"caption_text_override": "New caption"})

        assert decision.caption_text_override == "New caption"

    def test_raises_key_error_for_unknown_beat(self, tmp_path: Path):
        from novel_to_comic.server.narration_editor import apply_patch

        with patch("novel_to_comic.server.narration_editor.load_layout_plan") as mock_load, \
             patch("novel_to_comic.server.narration_editor.save_layout_plan"):
            mock_load.return_value = _plan(decisions=[])

            with pytest.raises(KeyError):
                apply_patch(tmp_path, "missing_beat", {"caption_text_override": "x"})
