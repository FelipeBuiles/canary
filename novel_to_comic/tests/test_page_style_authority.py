"""Draw carries Cast authorities only; the Style proof conditions Cast, never pages.

A proof drawn from the book's own scene depicts the cast. Sent beside the
approved sheets it acts as a second, conflicting version of the same people
(Monkey's Paw 2026-10-14: Morris's proof costume replaced his Cast coat), so
style reaches Draw through the proof-conditioned Cast sheets and plates.
"""

import pytest

from novel_to_comic.models.draw import RetryProvenance
from novel_to_comic.page_drawing import compile_page_generation_request, _integrated_page_profile
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_MARKER
from novel_to_comic.style_reference import require_style_reference

from .style_reference_support import write_style_proof
from .test_complete_page_draw import _edition, _inventory, _page, _profile, _reference_files, _provider_brief


@pytest.mark.parametrize("integrated", [False, True])
def test_draw_uploads_only_cast_authorities_and_identity_pose_contract_survives(tmp_path, integrated):
    files = _reference_files(tmp_path)
    write_style_proof(tmp_path)
    edition = _edition(_integrated_page_profile(_profile()) if integrated else _profile())
    compiled = compile_page_generation_request(
        _page(), edition, _inventory(), files, retry=RetryProvenance(attempt=1),
        style_template="Torn paper silhouettes.",
    )
    request = compiled.request
    payload = _provider_brief(request.prompt)
    assert [ref.id for ref in request.references] == ["ward-bloodied-ref", "idol-ref"]
    assert [ref.order for ref in request.references] == [1, 2]
    assert compiled.reference_bytes == (files["ward-bloodied-ref"].path.read_bytes(),
                                       files["idol-ref"].path.read_bytes())
    assert "selected_style_proof" not in payload
    assert [ref["image"] for ref in payload["approved_page_references"]] == ["asset-A", "asset-B"]
    assert "proof" not in request.prompt.lower()
    assert "do not default to the reference portrait's three-quarter view" in payload["reference_scope"]
    assert "not a fixed pose, facing direction, gaze, expression or camera angle" in payload["reference_scope"]
    assert "do not mirror asymmetric features" in payload["reference_scope"]
    assert request.prompt.count(RENDERING_FIDELITY_MARKER) == 1
    assert "confine surface cleanup to the authorized change" in request.prompt
    assert len(request.lettering) == int(integrated)
    assert request.estimated_cost_usd == edition.capability_profile.price_per_page_usd + 2 * edition.capability_profile.price_per_reference_usd


def test_resolver_rejects_missing_or_different_proof_and_never_uses_lettered_derivative(tmp_path):
    proof = write_style_proof(tmp_path, "Flat ink.")
    assert require_style_reference(tmp_path, "Flat ink.") == proof
    with pytest.raises(ValueError, match="Rerun Style"):
        require_style_reference(tmp_path, "Photographic.")
    proof.rename(proof.with_name("style_1_lettered.png"))
    with pytest.raises(ValueError, match="Rerun Style"):
        require_style_reference(tmp_path, "Flat ink.")
