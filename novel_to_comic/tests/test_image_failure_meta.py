import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import Character, Location, Prop, StoryBible
from novel_to_comic.models.prompt import ImagePrompt, PromptAnchor, PromptSubject
from novel_to_comic.prompting import IMAGE_PROMPT_VERSION
from novel_to_comic.server.routers.stages import list_images
from novel_to_comic import panel_generation
from novel_to_comic.state import create_initial_state
from novel_to_comic.stages import s3_cast
from novel_to_comic.stages import s7_draw
from novel_to_comic.usage import ApiResult


def test_generate_panel_writes_failure_metadata(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_001.json"
    prompt = ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A panel with difficult content.",
        width=768,
        height=1024,
        steps=28,
    )
    prompt_path.write_text(prompt.model_dump_json(indent=2))

    async def fail_generate_image(**kwargs):
        raise ValueError("No image part in Gemini response. Gemini details: IMAGE_PROHIBITED_CONTENT")

    monkeypatch.setattr(panel_generation, "execute_frozen_request", fail_generate_image)

    with pytest.raises(ValueError, match="No image part"):
        asyncio.run(
            s7_draw._generate_panel(
                Config(),
                tmp_path,
                prompt_path,
                asyncio.Semaphore(1),
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
    assert "A panel with difficult content." in payload["prompt"]
    assert "Output dimensions: 768x1024" in payload["prompt"]
    assert payload["error"]["type"] == "ValueError"
    assert "IMAGE_PROHIBITED_CONTENT" in payload["error"]["message"]


def test_generate_panel_classifies_rate_limit(tmp_path, monkeypatch):
    """A Vertex 429 (quota) is classified rate_limited, not a prompt problem."""
    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_002.json"
    prompt = ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
        planned_panel_id="scene_001:panel_002",
        scene_id="scene_001",
        panel_number=2,
        full_prompt="A perfectly fine panel.",
        width=768,
        height=1024,
        steps=28,
    )
    prompt_path.write_text(prompt.model_dump_json(indent=2))

    async def rate_limited(**kwargs):
        raise RuntimeError(
            "500 from /v1/images/edits: litellm.RateLimitError: Vertex image generation "
            "failed (RESOURCE_EXHAUSTED): 429 Resource has been exhausted (check quota)."
        )

    monkeypatch.setattr(panel_generation, "execute_frozen_request", rate_limited)

    with pytest.raises(RuntimeError):
        asyncio.run(
            s7_draw._generate_panel(
                Config(), tmp_path, prompt_path, asyncio.Semaphore(1), None, {}, None, None,
            )
        )

    payload = json.loads(
        (tmp_path / "draw" / "scene_001" / "panel_002.png.failure.json").read_text()
    )
    assert payload["classification"] == "rate_limited"
    assert payload["recoverable"] is True
    assert "wait for quota" in payload["user_message"].lower()
    assert "edit the prompt" not in payload["user_message"].lower()


def test_generate_panel_regenerates_stale_existing_image(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "direct" / "scene_004"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_004.json"
    prompt = ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
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

    async def fake_generate_image(**kwargs):
        calls.append(kwargs)
        kwargs["output_path"].write_bytes(b"new image")
        return ApiResult(value=kwargs["output_path"])

    monkeypatch.setattr(panel_generation, "execute_frozen_request", fake_generate_image)

    result = asyncio.run(
        s7_draw._generate_panel(
            Config(
                image_model="openai/gpt-image-2",
                style_template="Matte gouache, broad opaque shapes.",
            ),
            tmp_path,
            prompt_path,
            asyncio.Semaphore(1),
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
    assert "Matte gouache, broad opaque shapes." in meta["prompt"]
    assert '"quality":"medium"' in meta["prompt"]
    assert meta["prompt_sha256"] != "old"


def test_generate_panel_submits_compiled_prompt(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_001.json"
    prompt_path.write_text(ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        composition="medium shot with glowing text saying DANGER",
        full_prompt="legacy prompt with glowing text saying DANGER",
        width=768,
        height=1024,
        steps=8,
    ).model_dump_json())
    calls: list[dict] = []

    async def fake_generate_image(**kwargs):
        calls.append(kwargs)
        kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"].write_bytes(b"panel")
        return ApiResult(value=kwargs["output_path"])

    monkeypatch.setattr(panel_generation, "execute_frozen_request", fake_generate_image)
    asyncio.run(s7_draw._generate_panel(
        Config(image_model="image-balanced", layout_prompts_enabled=False),
        tmp_path,
        prompt_path,
        asyncio.Semaphore(1),
        None,
        {},
        None,
        None,
    ))

    meta = artifacts.read_asset_meta(tmp_path / "draw" / "scene_001" / "panel_001.png")
    submitted = meta["prompt"]
    assert "DANGER" not in submitted
    assert submitted == meta["prompt"]
    assert "Generation geometry" not in submitted  # section bodies, not titles, are canonical
    assert meta["parameters"]["output_sha256"] == hashlib.sha256(b"panel").hexdigest()


def test_panel_cache_rejects_metadata_for_different_png_bytes(tmp_path):
    image_path = tmp_path / "panel_001.png"
    image_path.write_bytes(b"previous panel")
    fingerprint = "f" * 64
    artifacts.write_asset_meta(image_path, {
        "parameters": {
            "execution_fingerprint": fingerprint,
            "output_sha256": hashlib.sha256(b"new panel").hexdigest(),
        },
    })

    assert not s7_draw._asset_matches_generation_meta(
        image_path,
        {"parameters": {"execution_fingerprint": fingerprint}},
    )


def test_panel_cache_accepts_committed_png_bytes(tmp_path):
    image_path = tmp_path / "panel_001.png"
    image_path.write_bytes(b"new panel")
    fingerprint = "f" * 64
    artifacts.write_asset_meta(image_path, {
        "parameters": {
            "execution_fingerprint": fingerprint,
            "output_sha256": hashlib.sha256(b"new panel").hexdigest(),
        },
    })

    assert s7_draw._asset_matches_generation_meta(
        image_path,
        {"parameters": {"execution_fingerprint": fingerprint}},
    )


def test_selected_reference_byte_change_invalidates_panel_cache(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_001.json"
    prompt_path.write_text(ImagePrompt(
        prompt_version=IMAGE_PROMPT_VERSION,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A portrait.",
        subjects=[PromptSubject(
            character_id="char_001",
            name="Hero",
            identity="a hero",
        )],
        width=768,
        height=1024,
        steps=8,
    ).model_dump_json())
    ref = tmp_path / "refs" / "char_001" / "front.png"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"reference-v1")

    calls: list[dict] = []

    async def fake_generate_image(**kwargs):
        calls.append(kwargs)
        kwargs["output_path"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["output_path"].write_bytes(b"panel")
        return ApiResult(value=kwargs["output_path"])

    monkeypatch.setattr(panel_generation, "execute_frozen_request", fake_generate_image)
    config = Config(
        image_model="image-balanced",
        visual_brief_enabled=False,
        layout_prompts_enabled=False,
    )

    args = (
        config, tmp_path, prompt_path, asyncio.Semaphore(1), None, {}, None, None,
    )
    asyncio.run(s7_draw._generate_panel(*args))
    meta = artifacts.read_asset_meta(
        tmp_path / "draw" / "scene_001" / "panel_001.png"
    )
    assert len(meta["parameters"]["reference_selection_fingerprint"]) == 64
    assert meta["parameters"]["refs"][0]["content_sha256"]
    assert "reference_diagnostics" in meta["parameters"]
    asyncio.run(s7_draw._generate_panel(*args))
    assert len(calls) == 1

    ref.write_bytes(b"reference-v2")
    asyncio.run(s7_draw._generate_panel(*args))
    assert len(calls) == 2


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
        subjects=[PromptSubject(name="Hero", character_id="hero", identity="hero")],
        location_id="loc_001",
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

    # image-fast -> vertex_ai/gemini-3.1-flash-lite-image: 0.0336 output +
    # 3 uploaded refs (hero subject + style + plate) x 0.00028 input each.
    # The missing `refs/missing/sheet.png` must be ignored, not counted.
    assert cost == pytest.approx(0.03444)


def test_panel_estimate_prices_compiled_prompt(tmp_path, monkeypatch):
    prompt_dir = tmp_path / "direct" / "scene_001"
    prompt_dir.mkdir(parents=True)
    prompt_path = prompt_dir / "panel_001.json"
    prompt_path.write_text(ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        composition="wide shot with a caption saying DANGER",
        full_prompt="legacy caption saying DANGER",
        width=1024,
        height=768,
        steps=8,
    ).model_dump_json())
    captured: dict[str, object] = {}

    def fake_estimate(*args, **kwargs):
        captured.update(kwargs)
        return 1.0

    monkeypatch.setattr(s7_draw, "estimate_image_cost", fake_estimate)
    cost = s7_draw.estimate_panel_image_cost_usd(
        Config(image_model="image-balanced"),
        tmp_path,
        prompt_path,
        scene_to_location={},
    )

    assert cost == 1.0
    assert "DANGER" not in captured["prompt_text"]
    assert "Output dimensions: 1024x768" in captured["prompt_text"]


def test_run_estimate_uses_only_selected_prompt_files(tmp_path, monkeypatch):
    selected = tmp_path / "direct" / "scene_001" / "panel_001.json"
    unrelated = tmp_path / "direct" / "scene_002" / "panel_001.json"

    def fake_panel_estimate(_config, _project_dir, prompt_path, **_kwargs):
        return 1.25 if prompt_path == selected else 99.0

    monkeypatch.setattr(s7_draw, "estimate_panel_image_cost_usd", fake_panel_estimate)
    total = s7_draw._estimate_prompt_files_cost(
        Config(), tmp_path, [selected], style_sample=None, scene_to_location={}
    )
    assert total == 1.25
    assert unrelated not in [selected]


def test_output_aspect_meta_flags_shape_mismatch(tmp_path):
    image_path = tmp_path / "panel.png"
    PILImage.new("RGB", (1408, 768), color="white").save(image_path)
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A panel.",
        generation_aspect_ratio=0.75,
        generation_shape="portrait",
        width=768,
        height=1024,
        steps=28,
    )

    meta = s7_draw._meta_with_output_aspect(image_path, {"parameters": {}}, prompt)

    assert meta["parameters"]["actual_width"] == 1408
    assert meta["parameters"]["actual_height"] == 768
    assert meta["parameters"]["requested_aspect_ratio"] == 0.75
    assert meta["parameters"]["aspect_validation_status"] == "shape_mismatch"
    with pytest.raises(s7_draw.AspectMismatchError):
        s7_draw._raise_if_aspect_mismatch(meta)


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
        Config(image_model="openai/gpt-image-2"),
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
        location_labels={"loc_001": "The White Parlour"},
    )

    assert gpt_refs == []
    assert [(ref.path, ref.role) for ref in gemini_refs] == [
        (style_path, "style"),
        (plate_path, "location_plate"),
    ]
    assert [(ref.role, ref.label) for ref in gemini_refs] == [
        ("style", "selected style"),
        ("location_plate", "The White Parlour"),
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
        subjects=[
            PromptSubject(
                character_id="char_001",
                name="Mr. White",
                identity="elderly man in a waistcoat",
            )
        ],
        anchors=[
            PromptAnchor(
                kind="prop",
                entity_id="prop_001",
                name="The Paw",
                text="a preserved monkey paw",
            )
        ],
        width=768,
        height=1024,
        steps=28,
    )

    gpt_refs = s7_draw.resolve_panel_references(
        Config(image_model="openai/gpt-image-2"),
        tmp_path,
        prompt,
    )
    gemini_refs = s7_draw.resolve_panel_references(
        Config(image_model="image-balanced"),
        tmp_path,
        prompt,
    )

    assert [ref.path for ref in gpt_refs] == [front]
    assert [ref.path for ref in gemini_refs] == [three_quarter, prop_ref]
    assert [ref.role for ref in gemini_refs] == ["subject", "prop"]
    assert [ref.label for ref in gemini_refs] == ["Mr. White", "prop_001"]


def test_gpt_image_2_cast_assets_skip_style_sample(tmp_path):
    style_path = tmp_path / "samples" / "style_1.png"

    assert s3_cast._cast_asset_style_ref(
        Config(image_model="openai/gpt-image-2"),
        style_path,
    ) is None
    assert s3_cast._cast_asset_style_ref(
        Config(image_model="image-balanced"),
        style_path,
    ) == style_path


def test_cast_asset_prompts_enforce_style_authority():
    config = Config(
        image_model="image-balanced",
        style_template="Painterly amber and cyan lighting, loose wet brushwork.",
    )
    char = Character(
        id="char_001",
        name="Mr. White",
        visual_anchor="1man, senior, thin grey beard, waistcoat",
        age_range="senior",
        gender="male",
        distinguishing_features=["thin grey beard"],
        default_outfit="Dark waistcoat over a white shirt.",
        first_appearance_scene="scene_001",
    )
    story_bible = StoryBible(
        title="The Monkey's Paw",
        author="W. W. Jacobs",
        total_scenes=0,
        characters=[char],
        locations=[],
        scenes=[],
        narrative_arcs=[],
    )
    loc = SimpleNamespace(
        id="loc_001",
        visual_anchor="indoors, small parlour, fireplace, warm shadows",
    )
    prop = Prop(
        id="prop_001",
        name="Monkey's Paw",
        visual_anchor="small mummified paw, dark leathery texture",
    )

    character_prompt = s3_cast._character_ref_prompt(config, story_bible, char)
    location_prompt = s3_cast._location_plate_prompt(config, loc)
    prop_prompt = s3_cast._prop_ref_prompt(config, prop)

    for prompt in (character_prompt, location_prompt, prop_prompt):
        assert "STYLE AUTHORITY:" in prompt
        assert "The selected style above is mandatory" in prompt
        assert "Preserve the style's medium, mark-making, palette, lighting language" in prompt
        assert "generic clean concept art" in prompt

    assert "Pure white background" not in character_prompt
    assert "subtle style-colored studio wash or cast light is allowed" in character_prompt


def test_gpt_image_2_location_plate_prompt_uses_low_texture_plate_language(tmp_path):
    loc = SimpleNamespace(
        id="loc_002",
        visual_anchor=(
            "day, outdoors, dim lighting, damp, dense woods, fallen leaves, "
            "debris, large spreading oak tree, thick underbrush, wild ferns"
        ),
    )
    config = Config(
        image_model="openai/gpt-image-2",
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

    assert "LOCATION DESIGN PLATE" not in prompt
    assert "Wide establishing shot" in prompt
    # Slice 06: location plates use a verified landscape shape that matches
    # the "wide environment design plate" the prompt promises (no longer
    # falling back to square config defaults).
    assert width is not None and height is not None
    assert width > height  # landscape


def test_regenerate_gpt_location_plate_uses_landscape_text_only(tmp_path, monkeypatch):
    config = Config(
        image_model="openai/gpt-image-2",
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

    async def fake_execute_frozen_request(*, project_dir, request_id, config, output_path, feature):
        output_path.write_bytes(b"plate")
        return ApiResult(value=output_path)

    monkeypatch.setattr(
        "novel_to_comic.non_panel_generation.execute_frozen_request",
        fake_execute_frozen_request,
    )

    result = asyncio.run(
        s3_cast.regenerate_location_plate(config, tmp_path, "loc_002")
    )

    meta = json.loads(artifacts.location_plate_meta_path(tmp_path, "loc_002").read_text())
    assert result.value == artifacts.location_plate_path(tmp_path, "loc_002")
    assert meta["provenance"]["effective_dimensions"] == {"width": 1344, "height": 768}
    assert meta["provenance"]["asset_identity"] == "location_plate:loc_002"
    assert "Output dimensions: 1344x768" in meta["prompt"]


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
        Config(image_model="openai/gpt-image-2"),
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
        Config(image_model="openai/gpt-image-2"),
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
    image_stat = image_path.stat()

    assert result == [{
        "scene_id": "scene_001",
        "panel_number": 1,
        "planned_panel_id": None,
        "status": "failed",
        "image_available": True,
        "image_revision": f"{image_stat.st_mtime_ns}-{image_stat.st_size}",
        "accepted": False,
        "flagged": False,
        "version_count": 0,
        "failure_classification": "generation_error",
        "failure_message": "Image generation failed during regeneration.",
        "failure_detail": None,
    }]
