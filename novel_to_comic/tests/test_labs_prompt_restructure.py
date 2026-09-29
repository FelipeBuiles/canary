"""Labs restructured prompts: same request, plain structure, verbatim authorities."""
import re

import pytest

from novel_to_comic.labs import prompt_restructure as pr
from novel_to_comic.models.draw import RetryProvenance
from novel_to_comic.page_drawing import (
    _integrated_page_profile,
    compile_page_generation_request,
    select_book_edition,
    sunburst_fallback_page_capability_profile,
)
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_MARKER
from tests.test_complete_page_draw import _inventory, _page, _reference_files

STYLE = "Ink and flat colour.\n\nLETTERING STANDARD — Serif captions.\n\nPAGE FRAMING STANDARD — Thin borders."


@pytest.mark.parametrize("integrated", [True, False])
def test_page_restructure_keeps_every_authority_and_drops_the_scaffolding(tmp_path, integrated):
    profile = sunburst_fallback_page_capability_profile()
    profile = _integrated_page_profile(profile) if integrated else profile
    request = compile_page_generation_request(
        _page(), select_book_edition(edition_id="test", profile=profile), _inventory(),
        _reference_files(tmp_path), retry=RetryProvenance(attempt=1), style_template=STYLE,
    ).request

    restructured = pr.restructure_page_prompt(request.prompt, width=request.output_width, height=request.output_height)

    required = pr.required_page_verbatim(request.prompt)
    assert required and [text for text in required if text not in restructured] == []
    assert len(restructured) < len(request.prompt)
    assert not re.search(r"\b(asset|subject)-[A-Z]+\b", restructured)
    assert "{" not in restructured and RENDERING_FIDELITY_MARKER not in restructured
    assert f"{request.output_width}×{request.output_height}" in restructured
    for ref in request.references:
        assert f"{ref.order}. {ref.label}: \"{ref.visual_anchor}\"" in restructured
    lettering = [item.text for content in _page().content for item in content.lettering]
    if integrated:
        assert "Lettering: letter exactly these strings" in restructured
    else:
        assert "Artwork only" in restructured
        assert not any(text in restructured for text in lettering if len(text) >= 12)


ASSET_PROMPT = """Constraints
- exactly 1 distinct listed character
- Surface fidelity: preserve the selected medium and deliberate texture, including authored grain.
- Detail hierarchy: keep focal contours legible at the intended viewing size.

Secondary style notes
Secondary textual style notes; the approved visual style reference owns the intended rendering language: Ink and flat colour. RENDERING APPROACH — Clearly stylized. CHARACTER DESIGN — elongated: Tall figures.

Protected anchors
Ada [char_001 / canonical]: 1woman, adult female, tall

Reference images
Reference 0: sole visual rendering style authority for selected style — preserve everything.

Scene direction
Composition: Wide turnaround sheet.
Visual brief: Five views of Ada on a plain background.

User constraint notes
Include "Hello there." exactly once.

Generation geometry
Output dimensions: 1536x1024

Image operation: create a new image from the specification."""


def test_asset_restructure_leads_with_the_picture_and_keeps_authorities():
    restructured = pr.restructure_asset_prompt(ASSET_PROMPT, [
        {"role": "style", "role_label": "style:selected style", "entity_id": None},
    ], width=1536, height=1024)

    assert restructured.startswith("Wide turnaround sheet. Five views of Ada on a plain background.\n"
                                   "Canvas: landscape 1536x1024.")
    assert [text for text in pr.required_asset_verbatim(ASSET_PROMPT) if text not in restructured] == []
    assert pr.required_asset_verbatim(ASSET_PROMPT) == [
        "1woman, adult female, tall", "Ink and flat colour.", "RENDERING APPROACH — Clearly stylized.",
        "CHARACTER DESIGN — elongated: Tall figures.", "Hello there.",
    ]
    assert "- exactly 1 distinct listed character" in restructured
    for dropped in ("Surface fidelity", "Detail hierarchy", "sole visual rendering style authority",
                    "Generation geometry", "Image operation", "Secondary textual style notes"):
        assert dropped not in restructured
    assert "1. Shows only how to paint" in restructured
