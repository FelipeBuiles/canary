"""Generated software styles, clean reference proofs and insertion affordances."""
from __future__ import annotations

import asyncio
import copy
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from novel_to_comic import artifacts as paths
from novel_to_comic.config import Config, save_config
from novel_to_comic.lettering import service
from novel_to_comic.lettering.proof import render_style_proof, style_proof_state
from novel_to_comic.models.lettering import LetteringDesign, LetteringStyle
from novel_to_comic.models.page import PinnedGeometry
from novel_to_comic.server.routers import lettering, pipeline, styles
from novel_to_comic.stages.s2_style import (
    StyleSuggestionBatch, build_style_sample_request, generate_sample_image,
    normalize_suggestion, save_suggestions,
)
from novel_to_comic.state import create_initial_state
from novel_to_comic.style_contract import (
    DESIGN_MARKER, page_art_style_template, rendering_style_template,
    style_template_for_suggestion,
)
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult
from tests.test_style_stage import _batch, _bible


def suggestion():
    candidate = _batch()["styles"][0]
    candidate["lettering_design"]["label"] = "Moonlit ink"
    candidate["lettering_design"]["roles"]["speech"].update(fill="#fff6d9", stroke="#342818")
    return normalize_suggestion(candidate)


def test_generated_design_is_required_closed_and_retained_through_selection():
    schema = StyleSuggestionBatch.model_json_schema()
    assert "lettering_design" in schema["$defs"]["StyleSuggestion"]["required"]
    assert set(schema["$defs"]["DesignedLetteringRoles"]["required"]) == {"caption", "speech", "thought", "sfx"}
    item = suggestion()
    assert normalize_suggestion(item)["id"] == item["id"]
    template = style_template_for_suggestion(item)
    style = service.style_from_template(template)
    assert style.label == "Moonlit ink"
    assert style.roles.speech.fill == "#fff6d9"
    assert style.roles == LetteringStyle(revision=1, roles=item["lettering_design"]["roles"]).roles
    invalid = _batch()
    del invalid["styles"][0]["lettering_design"]
    with pytest.raises(ValidationError, match="lettering_design"):
        StyleSuggestionBatch.model_validate(invalid)
    invalid = _batch() | {"lettering_design": item["lettering_design"]}
    with pytest.raises(ValidationError, match="Extra inputs"):
        StyleSuggestionBatch.model_validate(invalid)


@pytest.mark.parametrize("defect", ["missing_role", "font", "range", "color", "extra"])
def test_invalid_generated_tokens_fail_instead_of_silently_choosing_a_preset(defect):
    design = copy.deepcopy(suggestion()["lettering_design"])
    if defect == "missing_role":
        del design["roles"]["thought"]
    elif defect == "font":
        design["roles"]["speech"]["font"] = "A font not shipped with Canary"
    elif defect == "range":
        design["roles"]["speech"]["min_font_size"] = 99
    elif defect == "color":
        design["roles"]["caption"]["fill"] = "url(https://example.invalid)"
    else:
        design["arbitrary_code"] = "never execute"
    with pytest.raises(ValidationError):
        LetteringDesign.model_validate(design)


def test_software_design_never_leaks_into_generation_or_changes_art_projection():
    item = suggestion()
    template = style_template_for_suggestion(item)
    modified = copy.deepcopy(item)
    modified["lettering_design"]["roles"]["speech"]["fill"] = "#ffffff"
    other = style_template_for_suggestion(modified)
    assert template != other
    assert page_art_style_template(template) == page_art_style_template(other)
    assert rendering_style_template(template) == rendering_style_template(other)
    requests = [build_style_sample_request(Config(style_template=value), _bible(), "A quiet scene.", candidate_id="same-art") for value in (template, other)]
    assert requests[0].compiled.final_prompt == requests[1].compiled.final_prompt
    prompt = requests[0].compiled.final_prompt
    assert DESIGN_MARKER not in prompt
    assert "The night held its breath." not in prompt
    assert "We keep moving." not in prompt
    assert "KRAK" not in prompt
    assert "Do not draw any lettering" in prompt
    assert "(.54,.37,.40,.13)" in prompt


@pytest.mark.parametrize("stage", ["cast", "adapt", "plan"])
def test_style_saved_before_pages_survives_downstream_reruns(tmp_path, stage):
    target = TargetArtifacts(tmp_path)
    save_config(Config(style_template=style_template_for_suggestion(suggestion())), tmp_path)
    initial = service.ensure_style(target)
    incoming = LetteringStyle.model_validate(initial.model_dump() | {"label": "Author adjusted", "content_sha256": ""})
    saved = service.save_style(target, incoming, expected_revision=initial.revision)
    assert saved.revision == 2
    original_bytes = target.lettering_style_path.read_bytes()
    target.lettering_path(1).parent.mkdir(parents=True, exist_ok=True)
    target.lettering_path(1).write_text("obsolete layout")
    pipeline._clear_outputs_for_rerun(tmp_path, stage)
    assert target.lettering_style_path.read_bytes() == original_bytes
    assert not target.lettering_path(1).exists()
    assert service.ensure_style(target) == saved
    with pytest.raises(service.LetteringConflict):
        service.save_style(target, incoming, expected_revision=initial.revision)
    project = (tmp_path, Config(), create_initial_state("demo", "novel.txt"))
    assert lettering.get_lettering_style(project)["style"] == saved


@pytest.mark.parametrize("bounds", [(.2,.2,.4,.2), (.2,.9,.4,.08), (.01,.01,.7,.98), (.29,.01,.7,.98)])
def test_provisional_pointer_is_inside_page_and_outside_body(bounds):
    body = PinnedGeometry(**dict(zip(("x", "y", "width", "height"), bounds)))
    target = service.default_tail_target(body)
    assert target is not None
    assert 0 <= target.x <= 1 and 0 <= target.y <= 1
    assert not (body.x <= target.x <= body.x+body.width and body.y <= target.y <= body.y+body.height)


def test_seed_preserves_plan_targets_and_does_not_invent_offscreen_speakers():
    box = PinnedGeometry(x=.15, y=.15, width=.35, height=.16)
    items = [SimpleNamespace(id=f"item-{i}", kind=kind, text="A line.", delivery=delivery)
             for i, (kind, delivery) in enumerate((("dialogue", "onscreen"), ("thought", "onscreen"), ("dialogue", "offscreen"), ("caption", "narration")))]
    reservations = [SimpleNamespace(lettering_item_id=item.id, bounds=box, tail_target=None) for item in items]
    page = SimpleNamespace(content=[SimpleNamespace(order=1, lettering=items)], lettering_reservations=reservations, page_number=1, content_sha256="a"*64)
    state = service.seed_lettering(page, SimpleNamespace(width=1000, height=1250), service.preset_style())
    assert state.elements[0].tail_target is not None
    assert state.elements[1].tail_target is not None
    assert state.elements[2].tail_target is None
    assert state.elements[3].tail_target is None
    reservations[0].tail_target = {"x": .7, "y": .7}
    state = service.seed_lettering(page, SimpleNamespace(width=1000, height=1250), service.preset_style())
    assert state.elements[0].tail_target.model_dump() == reservations[0].tail_target


def test_proof_uses_shared_renderer_caches_and_never_modifies_reference_art(tmp_path, monkeypatch):
    target = TargetArtifacts(tmp_path)
    image = io.BytesIO()
    Image.new("RGB", (1000, 1250), "#d4d0c4").save(image, "PNG")
    raw = image.getvalue()
    source = paths.style_sample_path(tmp_path, 1)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(raw)
    style = service.style_from_template(style_template_for_suggestion(suggestion()))
    state = style_proof_state(style, 1000, 1250)
    assert {item.role for item in state.elements} == {"caption", "speech", "thought", "sfx"}
    composite, identity = render_style_proof(target, style, source.read_bytes())
    assert composite != raw
    assert source.read_bytes() == raw
    assert target.lettering_proof_path(identity).read_bytes() == composite
    different = LetteringStyle.model_validate(style.model_dump() | {"label": "A new design", "content_sha256": ""})
    _, next_identity = render_style_proof(target, different, raw)
    assert next_identity != identity
    monkeypatch.setattr("novel_to_comic.lettering.proof.resolve_lettering", lambda *_: pytest.fail("cache miss"))
    assert render_style_proof(target, style, raw) == (composite, identity)


def test_old_baked_proof_is_visible_but_never_gets_a_second_overlay(tmp_path):
    item = suggestion()
    save_suggestions(tmp_path, [item], _bible().title)
    paths.story_bible_path(tmp_path).write_text(_bible().model_dump_json())
    source = paths.style_sample_path(tmp_path, 1)
    source.write_bytes(b"old baked art")
    project = (tmp_path, Config(), create_initial_state("demo", "novel.txt"))
    result = styles.get_styles("demo", project)["suggestions"][0]
    assert result["has_sample"]
    assert result["sample_stale"]
    assert result["sample_preview_url"] is None
    with pytest.raises(HTTPException) as exc:
        styles.get_style_lettering_proof("demo", item["id"], "sample", project)
    assert exc.value.status_code == 409
    assert source.read_bytes() == b"old baked art"


def test_fresh_art_gets_a_software_proof_url_and_separate_immutable_bytes(tmp_path):
    item = suggestion()
    save_suggestions(tmp_path, [item], _bible().title)
    bible = _bible()
    paths.story_bible_path(tmp_path).write_text(bible.model_dump_json())
    config = Config(style_template=style_template_for_suggestion(item), style_sample_brief_enabled=False)
    raw_image = io.BytesIO()
    Image.new("RGB", (800, 1000), "#c3c2b5").save(raw_image, "PNG")
    raw = raw_image.getvalue()

    async def execute(*, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(raw)
        return ApiResult(value=output_path, usage=None)

    with patch("novel_to_comic.asset_generation.execute_frozen_request", new=AsyncMock(side_effect=execute)):
        asyncio.run(generate_sample_image(config, bible, paths.style_sample_path(tmp_path, 1), candidate_id=item["id"]))
    project = (tmp_path, config, create_initial_state("demo", "novel.txt"))
    result = styles.get_styles("demo", project)["suggestions"][0]
    assert not result["sample_stale"]
    assert f"/styles/{item['id']}/proof/sample?style=" in result["sample_preview_url"]
    response = styles.get_style_lettering_proof("demo", item["id"], "sample", project)
    assert response.media_type == "image/png"
    assert response.body != raw
    assert paths.style_sample_path(tmp_path, 1).read_bytes() == raw
