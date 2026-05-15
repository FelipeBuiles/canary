import asyncio
import json
from types import SimpleNamespace

import pytest

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import Location, StoryBible
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.server.routers.stages import list_images
from novel_to_comic.state import create_initial_state
from novel_to_comic.stages import s3_cast
from novel_to_comic.stages import s7_draw
from novel_to_comic.usage import ApiResult


def test_generate_panel_writes_failure_metadata(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_001.json"
    prompt = ImagePrompt(
        prompt_version=s7_draw.IMAGE_PROMPT_VERSION,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A panel with difficult content.",
        width=768,
        height=1024,
        steps=28,
    )
    prompt_path.write_text(prompt.model_dump_json(indent=2))

    async def fail_generate_image_multi_ref(**kwargs):
        raise ValueError("No image part in Gemini response. Gemini details: IMAGE_PROHIBITED_CONTENT")

    monkeypatch.setattr(
        s7_draw.flux,
        "generate_image_multi_ref",
        fail_generate_image_multi_ref,
    )

    with pytest.raises(ValueError, match="No image part"):
        asyncio.run(
            s7_draw._generate_panel(
                Config(),
                tmp_path,
                prompt_path,
                asyncio.Semaphore(1),
                {},
                None,
                {},
                None,
                None,
            )
        )

    failure_path = tmp_path / "draw" / "scene_001" / "panel_001.png.failure.json"
    payload = json.loads(failure_path.read_text())

    image_path = tmp_path / "draw" / "scene_001" / "panel_001.png"
    assert not image_path.exists()
    assert payload["kind"] == "panel_image_failure"
    assert payload["classification"] == "provider_blocked"
    assert payload["recoverable"] is True
    assert "recovery" not in payload
    assert payload["parameters"]["planned_panel_id"] == "scene_001:panel_001"
    assert "Visual brief:\nA panel with difficult content." in payload["prompt"]
    assert payload["error"]["type"] == "ValueError"
    assert "IMAGE_PROHIBITED_CONTENT" in payload["error"]["message"]


def test_generate_panel_regenerates_stale_existing_image(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "direct" / "scene_004"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_004.json"
    prompt = ImagePrompt(
        prompt_version=s7_draw.IMAGE_PROMPT_VERSION,
        planned_panel_id="scene_004:panel_004",
        scene_id="scene_004",
        panel_number=4,
        composition="close-up detail shot, environment or object filling the panel",
        setting="leaf mold, dirt, rotted denim, corroded buckles, cracked bone",
        lighting="low diffuse woodland light",
        mood="macabre",
        visual_requirements=["cracked teeth", "corroded buckles", "rotted denim strips"],
        constraints="exactly 0 characters; no text",
        width=768,
        height=1024,
        steps=28,
    )
    prompt_path.write_text(prompt.model_dump_json(indent=2))

    image_path = tmp_path / "draw" / "scene_004" / "panel_004.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"old image")
    artifacts.write_asset_meta(image_path, {"kind": "panel_image", "prompt_sha256": "old"})

    calls = []

    async def fake_generate_image_multi_ref(**kwargs):
        calls.append(kwargs)
        kwargs["output_path"].write_bytes(b"new image")
        return ApiResult(value=kwargs["output_path"])

    monkeypatch.setattr(
        s7_draw.flux,
        "generate_image_multi_ref",
        fake_generate_image_multi_ref,
    )

    result = asyncio.run(
        s7_draw._generate_panel(
            Config(
                image_model="image-quality",
                style_template="Matte gouache, broad opaque shapes.",
            ),
            tmp_path,
            prompt_path,
            asyncio.Semaphore(1),
            {},
            None,
            {},
            None,
            None,
        )
    )

    meta = json.loads(artifacts.asset_meta_path(image_path).read_text())
    assert result.value == image_path
    assert len(calls) == 1
    assert image_path.read_bytes() == b"new image"
    assert "Rendering discipline:\nGPT-image-2 material discipline" in meta["prompt"]
    assert meta["prompt_sha256"] != "old"


def test_panel_estimate_counts_actual_uploaded_references(tmp_path):
    ref_dir = tmp_path / "refs" / "hero"
    ref_dir.mkdir(parents=True)
    ref_path = ref_dir / "sheet.png"
    ref_path.write_bytes(b"ref")

    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    style_path = sample_dir / "style_1.png"
    style_path.write_bytes(b"style")

    plate_dir = tmp_path / "plates"
    plate_dir.mkdir()
    plate_path = plate_dir / "loc_001.png"
    plate_path.write_bytes(b"plate")

    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_001.json"
    prompt_path.write_text(ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A panel.",
        reference_image_paths=["refs/hero/sheet.png", "refs/missing/sheet.png"],
        width=768,
        height=1024,
        steps=28,
    ).model_dump_json())

    config = Config(image_model="image-fast")
    cost = s7_draw.estimate_panel_image_cost_usd(
        config,
        tmp_path,
        prompt_path,
        style_sample=style_path,
        scene_to_location={"scene_001": "loc_001"},
    )

    assert cost == pytest.approx(0.06868)


def test_gpt_image_2_reference_resolution_keeps_location_plate_text_only(tmp_path):
    sample_dir = tmp_path / "samples"
    sample_dir.mkdir()
    style_path = sample_dir / "style_1.png"
    style_path.write_bytes(b"style")

    plate_dir = tmp_path / "plates"
    plate_dir.mkdir()
    plate_path = plate_dir / "loc_001.png"
    plate_path.write_bytes(b"plate")

    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A panel.",
        width=768,
        height=1024,
        steps=28,
    )

    gpt_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-quality"),
        tmp_path,
        prompt,
        style_sample=style_path,
        scene_to_location={"scene_001": "loc_001"},
    )
    gemini_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-balanced"),
        tmp_path,
        prompt,
        style_sample=style_path,
        scene_to_location={"scene_001": "loc_001"},
    )

    assert gpt_refs == []
    assert [(ref.path, ref.role) for ref in gemini_refs] == [
        (style_path, "style"),
        (plate_path, "location_plate"),
    ]


def test_gpt_image_2_reference_resolution_uses_minimal_subject_refs(tmp_path):
    char_dir = tmp_path / "refs" / "char_001"
    char_dir.mkdir(parents=True)
    front = char_dir / "front.png"
    three_quarter = char_dir / "three_quarter.png"
    gesture = char_dir / "gesture.png"
    for path in (front, three_quarter, gesture):
        path.write_bytes(b"char")

    prop_dir = tmp_path / "refs" / "props" / "prop_001"
    prop_dir.mkdir(parents=True)
    prop_ref = prop_dir / "ref.png"
    prop_ref.write_bytes(b"prop")

    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A panel.",
        reference_image_paths=[
            "refs/char_001/front.png",
            "refs/char_001/three_quarter.png",
            "refs/char_001/gesture.png",
            "refs/props/prop_001/ref.png",
        ],
        width=768,
        height=1024,
        steps=28,
    )

    gpt_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-quality"),
        tmp_path,
        prompt,
    )
    gemini_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-balanced"),
        tmp_path,
        prompt,
    )

    assert [ref.path for ref in gpt_refs] == [front]
    assert [ref.path for ref in gemini_refs] == [front, three_quarter, gesture, prop_ref]
    assert [ref.role for ref in gemini_refs] == ["subject", "subject", "subject", "prop"]


def test_gpt_image_2_cast_assets_skip_style_sample(tmp_path):
    style_path = tmp_path / "samples" / "style_1.png"

    assert s3_cast._cast_asset_style_ref(
        Config(image_model="image-quality"),
        style_path,
    ) is None
    assert s3_cast._cast_asset_style_ref(
        Config(image_model="image-balanced"),
        style_path,
    ) == style_path


def test_gpt_image_2_location_plate_prompt_uses_low_texture_plate_language(tmp_path):
    loc = SimpleNamespace(
        id="loc_002",
        visual_anchor=(
            "day, outdoors, dim lighting, damp, dense woods, fallen leaves, "
            "debris, large spreading oak tree, thick underbrush, wild ferns"
        ),
    )
    config = Config(
        image_model="image-quality",
        style_template="Matte gouache, broad opaque shapes and clean edges.",
    )

    prompt = s3_cast._location_plate_prompt(config, loc)
    width, height = s3_cast._location_plate_dimensions(config)
    meta = s3_cast._location_plate_meta(
        config,
        tmp_path,
        None,
        loc,
        prompt,
        width,
        height,
    )

    assert loc.visual_anchor in prompt
    assert "LOCATION DESIGN PLATE" in prompt
    assert "large simple readable masses" in prompt
    assert "summarize them as a few grouped shapes" in prompt
    assert "Do not render leaf-by-leaf" in prompt
    assert "No repeated stamps, pattern tiling" in prompt
    assert (width, height) == (1536, 1024)
    assert meta["width"] == 1536
    assert meta["height"] == 1024


def test_non_gpt_location_plate_prompt_keeps_existing_shape(tmp_path):
    loc = SimpleNamespace(
        id="loc_002",
        visual_anchor="day, outdoors, dense woods, fallen leaves",
    )
    config = Config(
        image_model="image-balanced",
        style_template="Matte gouache, broad opaque shapes and clean edges.",
    )

    prompt = s3_cast._location_plate_prompt(config, loc)
    width, height = s3_cast._location_plate_dimensions(config)
    meta = s3_cast._location_plate_meta(
        config,
        tmp_path,
        None,
        loc,
        prompt,
        width,
        height,
    )

    assert "LOCATION DESIGN PLATE" not in prompt
    assert "Wide establishing shot" in prompt
    assert (width, height) == (None, None)
    assert "width" not in meta
    assert "height" not in meta


def test_regenerate_gpt_location_plate_uses_landscape_text_only(tmp_path, monkeypatch):
    config = Config(
        image_model="image-quality",
        style_template="Matte gouache, broad opaque shapes and clean edges.",
    )
    story_bible = StoryBible(
        title="The Flowers",
        author="Alice Walker",
        total_scenes=0,
        characters=[],
        locations=[
            Location(
                id="loc_002",
                name="Gloomy cove",
                visual_anchor="day, outdoors, dense woods, fallen leaves, wild ferns",
                mood="gloomy",
            )
        ],
        scenes=[],
        narrative_arcs=[],
    )
    artifacts.write_story_bible(tmp_path, story_bible)

    style_path = artifacts.style_sample_path(tmp_path, 1)
    style_path.parent.mkdir(parents=True)
    style_path.write_bytes(b"style")
    artifacts.style_suggestions_path(tmp_path).write_text(
        json.dumps({"suggestions": [{"template": config.style_template}]})
    )

    captured = {}

    async def fake_generate_image(
        config,
        prompt,
        output_path,
        width=None,
        height=None,
        reference_image_path=None,
        ref_type="subject",
        feature="image.generate",
    ):
        captured.update(
            {
                "prompt": prompt,
                "width": width,
                "height": height,
                "reference_image_path": reference_image_path,
                "ref_type": ref_type,
                "feature": feature,
            }
        )
        output_path.write_bytes(b"plate")
        return ApiResult(value=output_path)

    monkeypatch.setattr(s3_cast.flux, "generate_image", fake_generate_image)

    result = asyncio.run(
        s3_cast.regenerate_location_plate(config, tmp_path, "loc_002")
    )

    meta = json.loads(artifacts.location_plate_meta_path(tmp_path, "loc_002").read_text())
    assert result.value == artifacts.location_plate_path(tmp_path, "loc_002")
    assert captured["width"] == 1536
    assert captured["height"] == 1024
    assert captured["reference_image_path"] is None
    assert captured["ref_type"] == "style"
    assert captured["feature"] == "cast.location_plate"
    assert "LOCATION DESIGN PLATE" in captured["prompt"]
    assert meta["width"] == 1536
    assert meta["height"] == 1024
    assert meta["style_ref"] is None


def test_gpt_image_continuity_refs_are_text_only(tmp_path):
    scene_dir = tmp_path / "draw" / "scene_001"
    scene_dir.mkdir(parents=True)
    prev_image = scene_dir / "panel_001.png"
    prev_image.write_bytes(b"previous image")

    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    current_prompt_path = prompt_dir / "panel_002.json"
    current_prompt_path.write_text(ImagePrompt(
        scene_id="scene_001",
        panel_number=2,
        full_prompt="A panel.",
        width=768,
        height=1024,
        steps=28,
    ).model_dump_json())

    smooth_prev = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        transition_out="smooth_continuation",
        full_prompt="Previous panel.",
        width=768,
        height=1024,
        steps=28,
    )
    (prompt_dir / "panel_001.json").write_text(smooth_prev.model_dump_json())
    current_prompt = ImagePrompt.model_validate_json(current_prompt_path.read_text())

    gpt_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-quality"),
        tmp_path,
        current_prompt,
        prompt_path=current_prompt_path,
        output_dir=scene_dir,
    )
    gemini_smooth_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-balanced"),
        tmp_path,
        current_prompt,
        prompt_path=current_prompt_path,
        output_dir=scene_dir,
    )

    assert gpt_refs == []
    assert gemini_smooth_refs == []

    match_prev = smooth_prev.model_copy(update={"transition_out": "match_cut"})
    (prompt_dir / "panel_001.json").write_text(match_prev.model_dump_json())

    match_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-quality"),
        tmp_path,
        current_prompt,
        prompt_path=current_prompt_path,
        output_dir=scene_dir,
    )

    assert match_refs == []

    gemini_match_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-balanced"),
        tmp_path,
        current_prompt,
        prompt_path=current_prompt_path,
        output_dir=scene_dir,
    )

    assert [(ref.path, ref.role) for ref in gemini_match_refs] == [(prev_image, "continuity")]


def test_list_images_marks_failure_metadata_as_failed_even_with_existing_image(tmp_path):
    scene_dir = tmp_path / "draw" / "scene_001"
    scene_dir.mkdir(parents=True)
    image_path = scene_dir / "panel_001.png"
    image_path.write_bytes(b"old image")
    (scene_dir / "panel_001.png.failure.json").write_text(json.dumps({
        "classification": "generation_error",
        "user_message": "Image generation failed during regeneration.",
    }))

    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "panel_001.json").write_text(ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A panel.",
        width=768,
        height=1024,
        steps=28,
    ).model_dump_json())

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(generation_jobs={})))
    result = list_images(
        request,
        "demo",
        project=(tmp_path, Config(), create_initial_state("demo", "novel.txt")),
        user_id="user",
    )

    assert result == [{
        "scene_id": "scene_001",
        "panel_number": 1,
        "planned_panel_id": None,
        "status": "failed",
        "image_available": True,
        "accepted": False,
        "version_count": 0,
        "failure_classification": "generation_error",
        "failure_message": "Image generation failed during regeneration.",
        "failure_detail": None,
    }]
