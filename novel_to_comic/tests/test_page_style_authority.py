"""Selected proof survives compilation without becoming an identity/pose reference."""

import hashlib
import json

import pytest
from PIL import Image

from novel_to_comic.models.draw import FrozenPageGenerationRequest, PageRenderCorrection, RetryProvenance
from novel_to_comic.page_drawing import compile_page_generation_request, _prepare_complete_page, _integrated_page_profile
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_MARKER
from novel_to_comic.style_reference import require_style_reference

from .style_reference_support import write_style_proof
from .test_complete_page_draw import _edition, _inventory, _page, _profile, _reference_files, _provider_brief


@pytest.mark.parametrize("integrated", [False, True])
def test_proof_is_separate_rendering_authority_and_identity_pose_contract_survives(tmp_path, integrated):
    files = _reference_files(tmp_path)
    proof = write_style_proof(tmp_path)
    edition = _edition(_integrated_page_profile(_profile()) if integrated else _profile())
    compiled = compile_page_generation_request(
        _page(), edition, _inventory(), files, retry=RetryProvenance(attempt=1),
        style_reference_path=proof, style_template="Torn paper silhouettes.",
    )
    request = compiled.request
    payload = _provider_brief(request.prompt)
    assert [ref.id for ref in request.references] == ["ward-bloodied-ref", "idol-ref", "selected-style-proof"]
    assert compiled.reference_bytes == (files["ward-bloodied-ref"].path.read_bytes(),
                                       files["idol-ref"].path.read_bytes(), proof.read_bytes())
    assert request.references[-1].entity_id is None
    assert payload["selected_style_proof"]["image"] == "asset-C"
    assert len(payload["approved_page_references"]) == 2
    assert "facial abstraction" in payload["selected_style_proof"]["authority"]
    assert "not their identities" in payload["selected_style_proof"]["authority"]
    assert "do not default to the reference portrait's three-quarter view" in payload["reference_scope"]
    assert "not a fixed pose, facing direction, gaze, expression or camera angle" in payload["reference_scope"]
    assert "do not mirror asymmetric features" in payload["reference_scope"]
    assert request.prompt.count(RENDERING_FIDELITY_MARKER) == 1
    assert "confine surface cleanup to the authorized change" in request.prompt
    assert len(request.lettering) == int(integrated)
    assert request.estimated_cost_usd == edition.capability_profile.price_per_page_usd + 3 * edition.capability_profile.price_per_reference_usd
    assert _prepare_complete_page(compiled, edition.capability_profile).reference_bytes == compiled.reference_bytes


def test_proof_pixels_are_frozen_and_change_request_identity_without_rebinding_edition(tmp_path):
    files = _reference_files(tmp_path)
    proof = write_style_proof(tmp_path)
    args = (_page(), _edition(), _inventory(), files)
    before = compile_page_generation_request(*args, retry=RetryProvenance(attempt=1), style_reference_path=proof)
    saved = before.request.model_dump_json()
    Image.new("RGB", (32, 40), "blue").save(proof)
    after = compile_page_generation_request(*args, retry=RetryProvenance(attempt=1), style_reference_path=proof)
    assert before.request.request_sha256 != after.request.request_sha256
    assert before.request.references[:-1] == after.request.references[:-1]
    assert before.request.profile_sha256 == after.request.profile_sha256
    assert before.request.edition_sha256 == after.request.edition_sha256
    assert before.reference_bytes[-1] != proof.read_bytes()
    assert FrozenPageGenerationRequest.model_validate_json(saved) == before.request


@pytest.mark.parametrize("correction", [False, True])
def test_proof_and_edit_parent_reserve_slots_before_subject_packing(tmp_path, correction, monkeypatch):
    files = _reference_files(tmp_path)
    for ref in files.values():
        Image.new("RGB", (32, 40), "gray").save(ref.path)
    proof = write_style_proof(tmp_path)
    page = _page()
    parent = b"parent"
    edits = {}
    if correction:
        edits = dict(edit_source_bytes=parent, correction=PageRenderCorrection(
            page_number=page.page_number, comic_page_revision=page.revision,
            comic_page_sha256=page.content_sha256, parent_render_revision=1,
            parent_render_image_sha256=hashlib.sha256(parent).hexdigest(),
            mode="instructed", instruction="Turn Ward toward the idol.", note="Turn Ward toward the idol.",
        ))
    # Two subject refs fit in one lossless sheet; proof always has its own slot.
    profile = _profile(provider="codex-dev", model="gpt-image-2",
                       id="codex-dev-complete-page-hybrid-v1-" + "a" * 64,
                       max_image_references=2 + int(correction))
    monkeypatch.setattr("novel_to_comic.page_drawing.current_page_capability_profile", lambda: profile)
    compiled = compile_page_generation_request(
        page, _edition(profile), _inventory(), files, retry=RetryProvenance(attempt=1),
        style_reference_path=proof, **edits,
    )
    assert len(compiled.request.references) == 2
    sheet, style = compiled.request.references
    assert sheet.id.startswith("reference-sheet-")
    members = json.loads(sheet.visual_anchor)["members"]
    assert {member["authority"]["id"] for member in members} == {"ward-bloodied-ref", "idol-ref"}
    assert style.id == "selected-style-proof" and style.order == 2
    assert compiled.reference_bytes[-1] == proof.read_bytes()
    if correction:
        # Image 1 is the parent, so both sheet members bind upload 2.
        prompt = compiled.request.prompt
        assert prompt.count("Image 2 (asset-A) = ") == 2
        assert "sheet binding" in prompt
        assert "Image 3 (asset-B) = style proof" in prompt
    else:
        payload = _provider_brief(compiled.request.prompt)
        assert {ref["image"] for ref in payload["approved_page_references"]} == {"asset-A"}
        assert payload["selected_style_proof"]["image"] == "asset-B"
    assert _prepare_complete_page(compiled, profile).edit_source_bytes == (parent if correction else None)
    profile = _profile(provider="openai", max_image_references=2 + int(correction))
    with pytest.raises(ValueError, match="Identity references will not be silently dropped"):
        compile_page_generation_request(
            page, _edition(profile),
            _inventory(), files, retry=RetryProvenance(attempt=1), style_reference_path=proof, **edits,
        )


def test_resolver_rejects_missing_or_different_proof_and_never_uses_lettered_derivative(tmp_path):
    proof = write_style_proof(tmp_path, "Flat ink.")
    assert require_style_reference(tmp_path, "Flat ink.") == proof
    with pytest.raises(ValueError, match="Rerun Style"):
        require_style_reference(tmp_path, "Photographic.")
    proof.rename(proof.with_name("style_1_lettered.png"))
    with pytest.raises(ValueError, match="Rerun Style"):
        require_style_reference(tmp_path, "Flat ink.")


def test_gateway_labels_proof_by_authority_scope(tmp_path):
    from litellm_handlers.vertex_multimodal import _exact_complete_page_contents
    files = _reference_files(tmp_path)
    compiled = compile_page_generation_request(
        _page(), _edition(), _inventory(), files, retry=RetryProvenance(attempt=1),
        style_reference_path=write_style_proof(tmp_path),
    )
    parts = _exact_complete_page_contents(compiled.request.model_dump(mode="json"), ["cast", "prop", "proof"])
    assert parts[4] == "proof"
    assert "asset-C" in parts[5] and "authority scope" in parts[5]
    assert parts[-1] == compiled.request.prompt
