"""Provider-free policy checks; visual improvement is a separate acceptance gate."""
from dataclasses import asdict

import pytest

from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.generation_prompt import generate_system_constraints, render_canonical_body
from novel_to_comic.models.generation import PromptAnchor, PromptSubject
from novel_to_comic.rendering_fidelity import (
    RENDERING_FIDELITY_BLOCK, RENDERING_FIDELITY_CONSTRAINTS, RENDERING_FIDELITY_MARKER,
)
from novel_to_comic.style_contract import (
    DEFAULT_PAGE_FRAMING_STANDARD, page_art_style_template, page_style_template,
    post_production_lettering_direction, rendering_style_template, style_template_for_suggestion,
)


@pytest.mark.parametrize("kind", [
    "character_ref", "location_plate", "prop_ref", "style_sample",
    "style_calibration", "project_cover",
])
@pytest.mark.parametrize("has_references", [False, True])
def test_every_asset_gets_one_shared_policy_without_mutating_input(kind, has_references):
    prompt = GenerationPromptInput(
        subjects=(PromptSubject(name="Aster", identity="Three wings; deliberate stippled skin."),),
        style="Flat vector shapes with deliberate screen-print grain.",
        editorial_addendum="Preserve the deliberately distressed finish.",
    )
    before = asdict(prompt)
    lines = generate_system_constraints(
        prompt, asset_kind=kind, has_style_reference=has_references,
        has_subject_references=has_references,
    )
    assert all(lines.count(rule) == 1 for rule in RENDERING_FIDELITY_CONSTRAINTS)
    assert asdict(prompt) == before
    assert "explicitly chosen artistic texture" in " ".join(lines)


@pytest.mark.parametrize("style", [
    "Transparent watercolor with granular washes on rough paper.",
    "Coarse stippling and deliberately distressed photocopied punk art.",
    "Flat vector shapes, smooth gradients and no grain.",
    "High-contrast woodcuts with dense crosshatching.",
    "Deliberately noisy analog photography.",
    "",
])
def test_page_policy_is_idempotent_and_does_not_rewrite_selected_medium(style):
    selected = page_style_template(style, lettering="A unique serif.", page_framing="Uneven ink frames.")
    projected = page_art_style_template(selected)
    assert rendering_style_template(projected) == style
    assert projected.count(RENDERING_FIDELITY_MARKER) == 1
    assert projected.endswith(RENDERING_FIDELITY_BLOCK)
    assert page_art_style_template(projected) == projected
    assert "Uneven ink frames." in projected
    assert "A unique serif." not in projected
    assert "LETTERING STANDARD" not in projected
    assert RENDERING_FIDELITY_MARKER not in selected
    assert post_production_lettering_direction(selected) == "A unique serif."


def test_suggestion_authority_and_baked_template_stay_unchanged():
    suggestion = {"template": "Intentional mottled gouache.", "lettering": "Serif captions.",
                  "page_framing": "Ragged borders.", "lettering_preset": "literary"}
    before = dict(suggestion)
    selected = style_template_for_suggestion(suggestion)
    assert suggestion == before
    assert RENDERING_FIDELITY_BLOCK not in selected
    assert "POST-PRODUCTION LETTERING PRESET" not in page_art_style_template(selected)
    assert page_style_template(selected) == selected


def test_empty_style_still_has_a_hybrid_finish_policy_and_default_frame():
    result = page_art_style_template("")
    assert DEFAULT_PAGE_FRAMING_STANDARD in result
    assert RENDERING_FIDELITY_BLOCK in result


def test_appearance_and_editorial_authority_survive_policy():
    subject = PromptSubject(name="Aster", identity="Three wings; stippled skin — intentional.",
                            appearance_state_id="winter", appearance_locked=True)
    anchor = PromptAnchor(kind="location", entity_id="abbey", name="Abbey",
                          text="Stone marked with a seven-pointed crown.")
    prompt = GenerationPromptInput(subjects=(subject,), anchors=(anchor,))
    body = render_canonical_body(prompt)
    assert subject.identity in body and anchor.text in body
    assert "fixed altered appearance" in body
    assert "no text, captions, speech balloons, or lettering" in body
    assert "keep untouched artwork and composition unchanged" in body
    assert "confine surface cleanup to the authorized change" in body
