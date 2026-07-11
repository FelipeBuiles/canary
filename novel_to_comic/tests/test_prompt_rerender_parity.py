"""Cross-path rerender parity — manual edit, instructed edit, and quick re-do all
hydrate missing derived fields through the same server-side path and never leave
stale derived state behind.

Slice 01 contract: an authoritative structured edit must never retain a stale
visual brief or layout.  Derived fields are either fresh (re-derived) or absent
(cleared) after every edit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_to_comic.models.prompt import ImagePrompt, PromptLayout, LayoutRegion, LayoutBbox, PromptSubject
from novel_to_comic.panel_store import (
    APPLY_PROMPT_PATCH_FORBIDDEN_KEYS,
    apply_prompt_patch,
    load_prompt,
    save_prompt,
)
from novel_to_comic.prompt_instructions import apply_instruction_patch, parse_instruction_patch


def _base_prompt(tmp_path: Path) -> ImagePrompt:
    """A prompt that already has both derived fields populated (the stale state)."""
    prompt = ImagePrompt(
        prompt_version=1,
        planned_panel_id="scene_01_panel_001",
        scene_id="scene_01",
        panel_number=1,
        full_prompt="",
        distilled_prompt="STALE distilled brief mentioning the old setting.",
        visual_brief="STALE visual brief describing the wrong composition.",
        style="ink-wash",
        composition="wide establishing shot",
        setting="market square at dawn",
        lighting="soft golden hour",
        mood="bustling",
        subjects=[
            PromptSubject(
                character_id="ada",
                name="Ada",
                identity="short black bob haircut, blue jacket",
                action="walking briskly",
                expression="focused",
                position="center frame",
            )
        ],
        constraints="exactly 1 character; no text, captions, speech balloons, or lettering anywhere in the image",
        layout=PromptLayout(
            prompt="old layout summary",
            regions=[
                LayoutRegion(
                    label="ada",
                    prompt="stale region prompt",
                    bbox=LayoutBbox(x0=0.2, y0=0.2, x1=0.8, y1=0.9),
                    reference_key="ada",
                )
            ],
        ),
        reference_image_paths=["refs/ada/front.png"],
        width=1024,
        height=576,
        steps=20,
    )
    return prompt


class TestSemanticPatchClearsDerivedState:
    """Deliverable 3a: semantic prompt change -> clear visual_brief and layout."""

    def test_composition_edit_clears_visual_brief_and_layout(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        updated = apply_prompt_patch(prompt, {"composition": "extreme close-up of Ada's hands"})

        assert updated.composition == "extreme close-up of Ada's hands"
        assert updated.visual_brief is None, "visual_brief must be cleared after a composition change"
        assert updated.layout is None, "layout must be cleared after a composition change"

    def test_setting_edit_clears_visual_brief_and_layout(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        updated = apply_prompt_patch(prompt, {"setting": "rain-soaked alley at midnight"})

        assert "rain-soaked alley" in updated.setting
        assert updated.visual_brief is None
        assert updated.layout is None

    def test_subject_position_edit_clears_layout(self, tmp_path: Path):
        """Deliverable: Subject-position edit clears old layout."""
        prompt = _base_prompt(tmp_path)
        updated = apply_prompt_patch(
            prompt,
            {"subjects": _with_position(prompt.subjects, 0, "far left edge, turned away")},
        )

        assert updated.subjects[0].position == "far left edge, turned away"
        assert updated.layout is None, "position change must invalidate the layout"
        assert updated.visual_brief is None, "subject change must invalidate the visual brief"

    def test_subject_action_edit_clears_both_derived(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        updated = apply_prompt_patch(
            prompt,
            {"subjects": _with_action(prompt.subjects, 0, "running hard")},
        )
        assert updated.subjects[0].action == "running hard"
        assert updated.visual_brief is None
        assert updated.layout is None

    def test_constraints_edit_clears_visual_brief(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        updated = apply_prompt_patch(
            prompt,
            {"constraints": "non-graphic implied action, avoid explicit injury"},
        )
        assert "non-graphic implied action" in updated.constraints
        assert updated.visual_brief is None
        assert updated.layout is None


class TestLayoutOnlyPatchSurvives:
    """Deliverable 3b: manual layout-only change -> preserve the supplied layout."""

    def test_layout_only_patch_preserves_layout(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        new_layout = PromptLayout(
            prompt="manual composition summary",
            regions=[
                LayoutRegion(
                    label="ada",
                    prompt="repositioned region",
                    bbox=LayoutBbox(x0=0.1, y0=0.1, x1=0.5, y1=0.8),
                    reference_key="ada",
                )
            ],
        )
        updated = apply_prompt_patch(prompt, {"layout": new_layout})

        assert updated.layout is not None
        assert updated.layout.regions[0].prompt == "repositioned region"
        # A layout-only edit must NOT clear the visual brief — the prose brief
        # still describes the same scene; only the spatial map changed.
        assert updated.visual_brief == "STALE visual brief describing the wrong composition."


class TestPatchContractRejectsForbiddenFields:
    """Deliverable 2 + test: client attempts to set visual_brief, anchors,
    reference data, or system constraints are ignored or rejected."""

    @pytest.mark.parametrize("forbidden", sorted(APPLY_PROMPT_PATCH_FORBIDDEN_KEYS))
    def test_forbidden_keys_are_rejected(self, tmp_path: Path, forbidden: str):
        prompt = _base_prompt(tmp_path)
        with pytest.raises(ValueError):
            apply_prompt_patch(prompt, {forbidden: "attacker-controlled value"})

    def test_reference_paths_cannot_be_overwritten(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        assert prompt.reference_image_paths == ["refs/ada/front.png"]
        with pytest.raises(ValueError):
            apply_prompt_patch(prompt, {"reference_image_paths": ["refs/evil/hijack.png"]})

    def test_full_prompt_cannot_be_set_directly(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        with pytest.raises(ValueError):
            apply_prompt_patch(prompt, {"full_prompt": "raw attacker text"})

    def test_distilled_prompt_cannot_be_set_directly(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        with pytest.raises(ValueError):
            apply_prompt_patch(prompt, {"distilled_prompt": "raw attacker text"})


class TestInstructedEditClearsLayout:
    """Deliverable 3c: any accepted instructed semantic change -> clear layout
    as well as both prompt bodies."""

    def test_instructed_edit_clears_visual_brief_distilled_and_layout(self, tmp_path: Path):
        prompt = _base_prompt(tmp_path)
        patch = parse_instruction_patch(
            {
                "status": "accepted",
                "message": "Made Ada run.",
                "operations": [
                    {
                        "type": "subject",
                        "subject_index": 0,
                        "field": "action",
                        "value": "sprinting across the square",
                    }
                ],
            }
        )
        updated = apply_instruction_patch(prompt, patch)

        assert updated.subjects[0].action == "sprinting across the square"
        assert updated.visual_brief is None, "instructed edit must clear the visual brief"
        assert updated.distilled_prompt is None, "instructed edit must clear the distilled prompt"
        assert updated.layout is None, "instructed edit must clear the layout"


class TestStructuredEditReachesProviderBody:
    """Deliverable + test: Saved structured edit appears in the provider-bound
    body after hydration."""

    def test_persisted_composition_edit_appears_in_full_prompt(self, tmp_path: Path):
        _prompt_dir(tmp_path, "scene_01")
        prompt = _base_prompt(tmp_path)
        save_prompt(tmp_path, "scene_01", 1, prompt.model_dump())

        # Simulate a structured composition patch through the new path.
        existing = load_prompt(tmp_path, "scene_01", 1)
        assert existing is not None
        patched = apply_prompt_patch(existing, {"composition": "dramatic low-angle hero shot"})
        save_prompt(tmp_path, "scene_01", 1, patched.model_dump())

        reloaded = load_prompt(tmp_path, "scene_01", 1)
        assert reloaded is not None
        assert "dramatic low-angle hero shot" in reloaded.full_prompt
        assert reloaded.visual_brief is None
        assert reloaded.layout is None


class TestPlainRerenderKeepsFreshDerived:
    """Deliverable: Plain rerender without an edit keeps fresh derived fields."""

    def test_save_without_semantic_change_preserves_visual_brief(self, tmp_path: Path):
        _prompt_dir(tmp_path, "scene_01")
        prompt = _base_prompt(tmp_path)
        # Clear the layout (a non-layout field round-trip should not drop it).
        prompt.layout = None
        save_prompt(tmp_path, "scene_01", 1, prompt.model_dump())

        reloaded = load_prompt(tmp_path, "scene_01", 1)
        assert reloaded is not None
        assert reloaded.visual_brief == prompt.visual_brief
        assert reloaded.full_prompt  # rebuilt, non-empty


# ── helpers ───────────────────────────────────────────────────────────────────


def _with_position(subjects: list[PromptSubject], index: int, position: str) -> list[PromptSubject]:
    out = [s.model_copy(deep=True) for s in subjects]
    out[index].position = position
    return out


def _with_action(subjects: list[PromptSubject], index: int, action: str) -> list[PromptSubject]:
    out = [s.model_copy(deep=True) for s in subjects]
    out[index].action = action
    return out


def _prompt_dir(project_dir: Path, scene_id: str) -> Path:
    d = project_dir / "direct" / scene_id
    d.mkdir(parents=True, exist_ok=True)
    return d
