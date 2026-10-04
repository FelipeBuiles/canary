"""Generated software styles, clean reference proofs and insertion affordances."""
from __future__ import annotations

import asyncio
import copy
import json
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
from novel_to_comic.lettering.proof import (
    LABEL_COPY, SPECIMEN_MAX_CHARS, ProofCopy, render_style_proof, resolve_style_proof, style_proof_state,
)
from novel_to_comic.models.lettering import LetteringDesign, LetteringStyle
from novel_to_comic.models.page import PinnedGeometry
from novel_to_comic.server.routers import lettering, pipeline, styles
from novel_to_comic.stages.s2_style import (
    StyleProduction, build_style_sample_request, generate_sample_image,
    normalize_suggestion, save_suggestions,
)
from novel_to_comic.state import create_initial_state
from novel_to_comic.style_contract import (
    DESIGN_MARKER, page_art_style_template, rendering_style_template,
    style_template_for_suggestion,
)
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult
from tests.test_style_stage import _batch, _bible, _production


def suggestion():
    candidate = _batch()["styles"][0] | _production()
    candidate["lettering_design"]["label"] = "Moonlit ink"
    candidate["lettering_design"]["roles"]["speech"].update(fill="#fff6d9", stroke="#342818")
    return normalize_suggestion(candidate)


def test_generated_design_is_required_closed_and_retained_through_selection():
    schema = StyleProduction.model_json_schema()
    assert "lettering_design" in schema["required"]
    assert set(schema["$defs"]["DesignedLetteringRoles"]["required"]) == {"caption", "speech", "thought", "sfx"}
    item = suggestion()
    assert normalize_suggestion(item)["id"] == item["id"]
    template = style_template_for_suggestion(item)
    style = service.style_from_template(template)
    assert style.label == "Moonlit ink"
    assert style.roles.speech.fill == "#fff6d9"
    assert style.roles == LetteringStyle(revision=1, roles=item["lettering_design"]["roles"]).roles
    invalid = _production()
    del invalid["lettering_design"]
    with pytest.raises(ValidationError, match="lettering_design"):
        StyleProduction.model_validate(invalid)
    invalid = _production() | {"lettering_designs": item["lettering_design"]}
    with pytest.raises(ValidationError, match="Extra inputs"):
        StyleProduction.model_validate(invalid)


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
    items = [SimpleNamespace(id=f"item-{i}", kind=kind, text="A line.", delivery=delivery, source_unit_ids=(), speaker_entity_id=None)
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
    specimens = {item.id: item for item in state.elements}
    assert specimens["proof-shout"].role == "speech"
    assert specimens["proof-shout"].style_override.shape == "burst"
    assert specimens["proof-sfx"].style_override is None
    composite, identity = render_style_proof(target, style, source.read_bytes())
    assert composite != raw
    assert source.read_bytes() == raw
    assert target.lettering_proof_path(identity).read_bytes() == composite
    different = LetteringStyle.model_validate(style.model_dump() | {"label": "A new design", "content_sha256": ""})
    _, next_identity = render_style_proof(target, different, raw)
    assert next_identity != identity
    monkeypatch.setattr("novel_to_comic.lettering.proof.resolve_lettering", lambda *_: pytest.fail("cache miss"))
    assert render_style_proof(target, style, raw) == (composite, identity)


@pytest.mark.parametrize("size", [(1000, 1250), (1024, 1536)])
def test_proof_tails_follow_fitted_bodies_and_specimens_do_not_overlap(size):
    style = service.preset_style("classic")
    state = resolve_style_proof(style, *size)
    boxes = []
    for element in state.elements:
        body = element.resolved
        assert not body.overflow
        x, y = element.placement.x, element.placement.y
        assert body.width <= element.placement.width
        bottom = y + body.height
        if element.role in {"speech", "thought"}:
            tail = element.tail_target
            assert x < tail.x < x + body.width
            assert 0 < (tail.y - bottom) / state.canvas_aspect_ratio * 1000 <= body.font_size * 1.26
            bottom = tail.y
        boxes.append((x, y, x + body.width, bottom))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


_LONGEST_STORY_COPY = ProofCopy(
    caption="The lamps of the harbor guttered out one by one.",
    speech="Where did they all go?",
    shout="Run now!",
    thought="Nobody else saw the ship sink.",
    sfx="WHOOOSHHH",
)


@pytest.mark.parametrize("preset", sorted(service.PRESETS))
def test_longest_story_copy_fits_every_preset_without_overlap(preset):
    # The ceilings in SPECIMEN_MAX_CHARS must fit every bundled design.
    assert all(len(getattr(_LONGEST_STORY_COPY, role)) == limit for role, limit in SPECIMEN_MAX_CHARS.items())
    state = resolve_style_proof(service.preset_style(preset), 1024, 1536, _LONGEST_STORY_COPY)
    assert {item.id.removeprefix("proof-"): item.resolved.text for item in state.elements} == (
        _LONGEST_STORY_COPY.model_dump())
    boxes = []
    for element in state.elements:
        body = element.resolved
        assert not body.overflow and not body.warnings
        x, y = element.placement.x, element.placement.y
        bottom = element.tail_target.y if element.tail_target else y + body.height
        boxes.append((x, y, x + body.width, bottom))
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_a_line_a_design_cannot_fit_shows_its_role_label(monkeypatch):
    from novel_to_comic.lettering import proof

    real = proof.resolve_lettering

    def overflowing_speech(state, style):
        resolved = real(state, style)
        return resolved.model_copy(update={"elements": tuple(
            element.model_copy(update={"resolved": element.resolved.model_copy(update={"overflow": True})})
            if element.id == "proof-speech" and element.text_by_locale["source"] != LABEL_COPY.speech
            else element
            for element in resolved.elements
        )})

    monkeypatch.setattr(proof, "resolve_lettering", overflowing_speech)
    state = resolve_style_proof(service.preset_style(), 1024, 1536, _LONGEST_STORY_COPY)
    texts = {item.id.removeprefix("proof-"): item.resolved.text for item in state.elements}
    assert texts["speech"] == LABEL_COPY.speech
    assert texts["caption"] == _LONGEST_STORY_COPY.caption


def test_story_copy_is_part_of_the_overlay_identity(tmp_path):
    image = io.BytesIO()
    Image.new("RGB", (1024, 1536), "#d4d0c4").save(image, "PNG")
    target = TargetArtifacts(tmp_path)
    style = service.preset_style()
    _, labelled = render_style_proof(target, style, image.getvalue())
    _, story = render_style_proof(target, style, image.getvalue(), _LONGEST_STORY_COPY)
    assert labelled != story


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


@pytest.mark.parametrize("mode", ["editable", "integrated"])
@pytest.mark.parametrize("kind", ["sample", "validation"])
def test_fresh_proofs_follow_mode_and_preserve_generated_lettering(tmp_path, mode, kind):
    item = suggestion()
    save_suggestions(tmp_path, [item], _bible().title)
    bible = _bible()
    paths.story_bible_path(tmp_path).write_text(bible.model_dump_json())
    config = Config(style_template=style_template_for_suggestion(item), style_sample_brief_enabled=False, lettering_mode=mode)
    raw_image = io.BytesIO()
    Image.new("RGB", (800, 1000), "#c3c2b5").save(raw_image, "PNG")
    raw = raw_image.getvalue()

    async def execute(*, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(raw)
        return ApiResult(value=output_path, usage=None)

    with patch("novel_to_comic.asset_generation.execute_frozen_request", new=AsyncMock(side_effect=execute)):
        from novel_to_comic.stages.s2_style import style_validation_brief, STYLE_VALIDATION_ACTION, STYLE_VALIDATION_COMPOSITION
        source = paths.style_sample_path(tmp_path, 1) if kind == "sample" else paths.style_validation_path(tmp_path, item["id"])
        kwargs = {} if kind == "sample" else dict(
            brief=style_validation_brief(bible), subject_action=STYLE_VALIDATION_ACTION,
            composition=STYLE_VALIDATION_COMPOSITION,
        )
        asyncio.run(generate_sample_image(config, bible, source, project_dir=tmp_path,
            candidate_id=item["id"] if kind == "sample" else f"{item['id']}:validation", **kwargs))
    project = (tmp_path, config, create_initial_state("demo", "novel.txt"))
    result = styles.get_styles("demo", project)["suggestions"][0]
    assert not result["sample_stale"]
    url = result["sample_preview_url"] if kind == "sample" else result["validation_url"]
    assert f"/styles/{item['id']}/proof/{kind}?style=" in url
    assert result["lettering_source"] == "generated"
    with patch.object(styles, "render_style_proof", wraps=render_style_proof) as compositor:
        response = styles.get_style_lettering_proof("demo", item["id"], kind, project)
    if mode == "integrated":
        compositor.assert_not_called()
    else:
        assert compositor.call_args.args[1].roles == service.style_from_template(config.style_template).roles
    assert response.media_type == "image/png"
    assert (response.body == raw) == (mode == "integrated")
    assert source.read_bytes() == raw
    other_mode = "editable" if mode == "integrated" else "integrated"
    other_project = (tmp_path, config.model_copy(update={"lettering_mode": other_mode}), project[2])
    with pytest.raises(HTTPException) as exc:
        styles.get_style_lettering_proof("demo", item["id"], kind, other_project)
    assert exc.value.status_code == 409


def test_integrated_style_prompt_draws_all_specimens_and_preserves_lettering_direction():
    from novel_to_comic.lettering.proof import LABEL_COPY, specimens
    item = suggestion()
    item["lettering"] = "Distinctive hand-painted captions, rounded speech, cloud thoughts and textured display effects."
    config = Config(lettering_mode="integrated", style_template=style_template_for_suggestion(item))
    prompt = build_style_sample_request(config, _bible(), "A quiet scene.", candidate_id="integrated").compiled.final_prompt
    assert item["lettering"] in prompt
    # Without story copy, the proof letters role names, never invented dialogue.
    for _role, text, _bounds in specimens(LABEL_COPY):
        assert json.dumps(text) in prompt
    assert "not dialogue" in prompt
    assert "Draw the lettering directly into the image" in prompt
    assert "Do not draw any lettering" not in prompt
    assert "Software adds them later" not in prompt
    assert DESIGN_MARKER not in prompt
    assert "POST-PRODUCTION LETTERING PRESET" not in prompt


def test_retained_integrated_edition_controls_style_proof_compilation(tmp_path):
    from novel_to_comic.page_drawing import select_book_edition, current_page_capability_profile
    integrated = Config(lettering_mode="integrated")
    TargetArtifacts(tmp_path).write_book_edition(select_book_edition(
        edition_id="retained", profile=current_page_capability_profile(integrated),
    ))
    prompt = build_style_sample_request(Config(), _bible(), "A quiet scene.",
        candidate_id="retained", project_dir=tmp_path).compiled.final_prompt
    assert "Draw the lettering directly into the image" in prompt
    assert "Do not draw any lettering" not in prompt
