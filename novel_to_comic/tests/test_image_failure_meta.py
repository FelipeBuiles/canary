import asyncio
import json
from types import SimpleNamespace

import pytest

from novel_to_comic.config import Config
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.server.routers.stages import list_images
from novel_to_comic.state import create_initial_state
from novel_to_comic.stages import s7_draw


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
    assert payload["prompt"].endswith("A panel with difficult content.")
    assert payload["error"]["type"] == "ValueError"
    assert "IMAGE_PROHIBITED_CONTENT" in payload["error"]["message"]


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

    _, primary_style_refs = s7_draw.resolve_panel_reference_paths(
        Config(),
        tmp_path,
        prompt,
        style_sample=style_path,
        scene_to_location={"scene_001": "loc_001"},
    )
    _, fast_style_refs = s7_draw.resolve_panel_reference_paths(
        Config(image_model="image-fast"),
        tmp_path,
        prompt,
        style_sample=style_path,
        scene_to_location={"scene_001": "loc_001"},
    )

    assert primary_style_refs == [style_path]
    assert fast_style_refs == [style_path, plate_path]


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
    }]
