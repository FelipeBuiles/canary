"""Real compiler/frozen-request integration, with no provider submissions."""
import hashlib
import json

from PIL import Image

from novel_to_comic.compiled_request import GenerationControls, _build_sections
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.models.draw import BookEdition, FrozenPageGenerationRequest, PageRenderCorrection, RetryProvenance
from novel_to_comic.models.generation import PromptSubject
from novel_to_comic.models.page import ApprovedVisualReference, ApprovedVisualReferenceInventory, ComicPage, PageContent
from novel_to_comic import page_drawing
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_CONSTRAINTS, RENDERING_FIDELITY_MARKER


def test_asset_policy_is_in_protected_semantic_section_before_freezing():
    identity = "Three translucent wings — deliberate stippled skin."
    style = "Watercolor with intentional granulation."
    prompt = GenerationPromptInput(subjects=(PromptSubject(name="Aster", identity=identity),), style=style)
    sections, final = _build_sections(
        prompt, style, (), GenerationControls(quality="high"), (1024, 1280),
        "portrait", None, "style_sample",
    )
    system = next(section for section in sections if section.kind == "system_constraints")
    assert all(f"- {rule}" in system.lines for rule in RENDERING_FIDELITY_CONSTRAINTS)
    assert identity in final and style in final
    assert all(final.count(rule) == 1 for rule in RENDERING_FIDELITY_CONSTRAINTS)


def page_inputs(tmp_path):
    page = ComicPage(
        revision=1, page_number=1, adaptation_revision=1, adaptation_sha256="a" * 64,
        page_turn_role="reveal", spread_role="right", emphasis="peak", density_intent="standard",
        rhythm_intent="A quiet establishing beat.", layout_intent="One wide scene.",
        content=[PageContent(id="scene-1", order=1, beat_ids=["beat-1"],
                             visual_intent="Moonlight at the abbey.", lettering=[], entity_ids=["abbey"])],
        reading_order=["scene-1"], lettering_reservations=[],
    )
    inventory = ApprovedVisualReferenceInventory(references=[ApprovedVisualReference(
        id="abbey-ref", entity_id="abbey", visual_anchor="Basalt stones and a seven-pointed arch.")])
    path = tmp_path / "abbey.png"
    Image.new("RGB", (32, 32)).save(path)
    files = {"abbey-ref": page_drawing.ApprovedReferenceFile(reference_id="abbey-ref", path=path, media_type="image/png")}
    profile = page_drawing.openai_page_capability_profile("gpt-image-2.5-sunburst")
    edition = BookEdition(revision=1, id="fidelity-test", capability_profile=profile)
    return page, edition, inventory, files


def test_hybrid_policy_changes_prompt_hash_not_refs_profile_or_old_frozen_request(tmp_path, monkeypatch):
    args = page_inputs(tmp_path)
    project = page_drawing.page_art_style_template
    style = "Nocturnal watercolor; intentional paper grain."
    with monkeypatch.context() as context:
        context.setattr(page_drawing, "page_art_style_template", lambda value: project(value).split(
            "\n\n" + RENDERING_FIDELITY_MARKER, 1)[0])
        baseline = page_drawing.compile_page_generation_request(*args, retry=RetryProvenance(attempt=1), style_template=style)
    frozen_baseline = baseline.request.model_dump_json()
    current = page_drawing.compile_page_generation_request(*args, retry=RetryProvenance(attempt=1), style_template=style)
    assert RENDERING_FIDELITY_MARKER not in baseline.request.prompt
    assert current.request.prompt.count(RENDERING_FIDELITY_MARKER) == 1
    assert current.request.request_sha256 != baseline.request.request_sha256
    assert current.request.references == baseline.request.references
    assert current.request.profile_sha256 == baseline.request.profile_sha256
    assert current.request.output_width == baseline.request.output_width == 1024
    assert current.request.output_height == baseline.request.output_height == 1536
    assert FrozenPageGenerationRequest.model_validate_json(frozen_baseline) == baseline.request
    payload = json.loads(current.request.prompt[current.request.prompt.index("{"):current.request.prompt.rindex("}") + 1])
    assert payload["project_style_direction"].startswith(style)
    assert "LETTERING STANDARD" not in payload["project_style_direction"]
    assert "Draw NO speech or thought balloons" in current.request.prompt
    assert "they do not prescribe an additional surface-texture layer" in current.request.prompt
    assert "Preserve authored markings and deliberate medium texture" in current.request.prompt
    assert args[2].references[0].visual_anchor in current.request.prompt


def test_correction_keeps_parent_and_explicit_cleanup_scope(tmp_path):
    args = page_inputs(tmp_path)
    initial = page_drawing.compile_page_generation_request(*args, retry=RetryProvenance(attempt=1))
    parent_bytes = (tmp_path / "abbey.png").read_bytes()
    parent_sha = hashlib.sha256(parent_bytes).hexdigest()
    page = args[0]
    instruction = "Clean accidental mottling in the sky only. Keep the inked ruins untouched."
    correction = PageRenderCorrection(
        page_number=page.page_number, comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256, parent_render_revision=1,
        parent_render_image_sha256=parent_sha, mode="instructed",
        instruction=instruction, note=instruction,
    )
    result = page_drawing.compile_page_generation_request(
        *args, retry=RetryProvenance(attempt=2, retries_request_sha256=initial.request.request_sha256),
        correction=correction, edit_source_bytes=parent_bytes,
    )
    assert result.request.correction.parent_render_image_sha256 == parent_sha
    assert instruction in result.request.prompt
    assert result.request.prompt.count(RENDERING_FIDELITY_MARKER) == 1
    assert "confine surface cleanup to the authorized change" in result.request.prompt
    assert (tmp_path / "abbey.png").read_bytes() == parent_bytes
