"""Tests for prompt_assembly — narration constraint idempotency and rerender path."""

import pytest

from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.prompt_assembly import _apply_narration_constraint, rerender_prompt_body

_NOTE = (
    "narration caption will be lettered in post-production only; "
    "do not draw caption boxes, speech bubbles, labels, signs, or readable text"
)


class TestApplyNarrationConstraint:
    def test_adds_note_when_flag_true_and_no_prior_note(self):
        result = _apply_narration_constraint("exactly 1 character; no text", has_narration_caption=True)
        assert _NOTE in result
        assert "exactly 1 character; no text" in result

    def test_removes_note_when_flag_false(self):
        existing = f"exactly 1 character; no text; {_NOTE}"
        result = _apply_narration_constraint(existing, has_narration_caption=False)
        assert _NOTE not in result
        assert "exactly 1 character; no text" in result

    def test_idempotent_when_note_already_present(self):
        base = f"exactly 1 character; {_NOTE}"
        result_once = _apply_narration_constraint(base, has_narration_caption=True)
        result_twice = _apply_narration_constraint(result_once, has_narration_caption=True)
        assert result_once == result_twice
        assert result_once.count(_NOTE) == 1

    def test_returns_none_for_empty_constraints_without_flag(self):
        result = _apply_narration_constraint(None, has_narration_caption=False)
        assert result is None

    def test_returns_just_note_for_empty_constraints_with_flag(self):
        result = _apply_narration_constraint(None, has_narration_caption=True)
        assert result == _NOTE


class TestRerenderPromptBody:
    def _make_prompt(self, *, has_narration_caption: bool = False, constraints: str | None = None) -> ImagePrompt:
        return ImagePrompt(
            prompt_version=1,
            planned_panel_id="scene_01_panel_001",
            scene_id="scene_01",
            panel_number=1,
            generation_mode="standard",
            shape_intent="landscape",
            full_prompt="",
            style="test-style",
            composition="close-up shot",
            setting="interior office",
            lighting="natural light",
            mood="tense",
            constraints=constraints,
            has_narration_caption=has_narration_caption,
            width=1024,
            height=576,
            steps=20,
        )

    def test_rerender_produces_nonempty_body(self):
        prompt = self._make_prompt()
        body = rerender_prompt_body(prompt)
        assert len(body) > 0

    def test_narration_note_not_doubled_when_already_in_constraints(self):
        # Simulate a prompt built with the old code that embedded the note
        constraints_with_note = f"exactly 1 character; no text; {_NOTE}"
        prompt = self._make_prompt(has_narration_caption=True, constraints=constraints_with_note)
        body = rerender_prompt_body(prompt)
        assert body.count(_NOTE) == 1

    def test_narration_note_present_when_flag_true(self):
        prompt = self._make_prompt(has_narration_caption=True, constraints="exactly 1 character; no text")
        body = rerender_prompt_body(prompt)
        assert _NOTE in body

    def test_narration_note_absent_when_flag_false(self):
        prompt = self._make_prompt(has_narration_caption=False, constraints="exactly 1 character; no text")
        body = rerender_prompt_body(prompt)
        assert _NOTE not in body

    def test_rerender_idempotent(self):
        """Editing a prompt and re-rendering should give same result each time."""
        prompt = self._make_prompt(has_narration_caption=True, constraints="exactly 1 character; no text")
        body1 = rerender_prompt_body(prompt)
        prompt.full_prompt = body1
        body2 = rerender_prompt_body(prompt)
        assert body1 == body2
