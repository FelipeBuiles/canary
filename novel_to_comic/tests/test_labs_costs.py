import asyncio
from pathlib import Path

from PIL import Image
from pytest import approx

from novel_to_comic.labs.costs import estimate_labs_image_cost
from novel_to_comic.labs.providers.base import LabsImageInput
from novel_to_comic.labs.providers.litellm import LitellmProvider, _canonical_temp_path
from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.asset_generation import AssetGenerationInput, compile_non_panel_request
from novel_to_comic.labs.registry import LabsModelEntry
from novel_to_comic.usage import ApiResult, UsageRecord


def _write_png(path: Path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, color=(255, 255, 255)).save(path)


def test_labs_cost_uses_endpoint_pricing_before_registry_approximation(tmp_path):
    ref = tmp_path / "ref.png"
    _write_png(ref, (512, 512))
    entry = LabsModelEntry(
        id="nano-banana-2-edit",
        label="Nano Banana 2",
        provider="fal",
        endpoint="fal-ai/nano-banana-2/edit",
        approx_cost=0.01,
    )

    breakdown = estimate_labs_image_cost(
        entry,
        LabsImageInput(
            prompt="Make a comic panel",
            width=1024,
            height=1024,
            reference_image_paths=[ref],
        ),
    )

    assert breakdown.cost_usd == approx(0.08)
    assert breakdown.source == "canary_pricing_override"
    assert breakdown.provider_model == "fal-ai/nano-banana-2/edit"


def test_labs_cost_scales_flux_2_edit_by_output_and_reference_megapixels(tmp_path):
    ref_a = tmp_path / "ref_a.png"
    ref_b = tmp_path / "ref_b.png"
    _write_png(ref_a, (512, 512))
    _write_png(ref_b, (1600, 900))
    entry = LabsModelEntry(
        id="flux-2-pro-edit",
        label="FLUX.2 Pro Edit",
        provider="fal",
        endpoint="fal-ai/flux-2-pro/edit",
    )

    breakdown = estimate_labs_image_cost(
        entry,
        LabsImageInput(
            prompt="Make a comic panel",
            width=1920,
            height=1080,
            reference_image_paths=[ref_a, ref_b],
        ),
    )

    assert breakdown.cost_usd == approx(0.09)


def test_litellm_provider_returns_calculated_usage_cost(monkeypatch):
    async def fake_generate_wire_image(**kwargs):
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"image")
        return ApiResult(
            value=output_path,
            usage=UsageRecord(
                provider="openai",
                model="openai/gpt-image-2",
                operation="image",
                image_count=1,
            ),
        )

    monkeypatch.setattr(
        "novel_to_comic.labs.providers.litellm.generate_wire_image",
        fake_generate_wire_image,
    )

    config = Config(image_model="openai/gpt-image-2")
    compiled = compile_non_panel_request(
        config,
        AssetGenerationInput(
            asset_kind="panel",
            asset_identity="labs:test:panel:1",
            prompt=GenerationPromptInput(width=1024, height=1024),
        ),
    )
    inp = LabsImageInput(prompt="Make a comic panel", extra={"provider_wire_json": compiled.wire.to_json()})

    result = asyncio.run(
        LitellmProvider().generate(
            endpoint="openai/gpt-image-2",
            inp=inp,
        )
    )

    assert result.cost_usd == approx(0.03168)
    assert result.cost_source == "litellm_cost_map+canary_pricing_override"
    assert result.provider_model == "openai/gpt-image-2"


def test_litellm_temp_output_canonicalizes_symlinked_ancestor(tmp_path):
    real = tmp_path / "private" / "var"
    real.mkdir(parents=True)
    alias = tmp_path / "var"
    alias.symlink_to(real, target_is_directory=True)
    output = alias / "result.png"

    assert _canonical_temp_path(output) == real / "result.png"
