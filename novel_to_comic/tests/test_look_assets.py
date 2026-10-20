"""Look production tests cross the operation at the frozen transport seam."""
import asyncio
import json

import pytest

from novel_to_comic import artifacts
from novel_to_comic.asset_generation import AssetGenerationInput, compile_non_panel_request
from novel_to_comic.asset_versions import asset_versions_dir
from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.look_assets import produce_look_asset
from novel_to_comic.usage import ApiResult


@pytest.mark.parametrize("kind,identity,path", [
    ("style_sample", "style_sample:1", "samples/style_1.png"),
    ("location_plate", "location_plate:loc", "plates/loc.png"),
    ("prop_ref", "prop_ref:prop", "refs/props/prop/ref.png"),
])
def test_produce_archives_image_and_sidecar_then_reuses(tmp_path, monkeypatch, kind, identity, path):
    config = Config(image_model="image-gemini-pro")
    request = compile_non_panel_request(config, AssetGenerationInput(
        asset_identity=identity, asset_kind=kind,
        prompt=GenerationPromptInput(visual_brief="An ink proof", width=819, height=1024),
    ))
    output = tmp_path / path
    output.parent.mkdir(parents=True)
    output.write_bytes(b"old image")
    artifacts.write_asset_meta(output, {"old": "provenance"})
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)
        assert (asset_versions_dir(output) / "v001.png").read_bytes() == b"old image"
        output.write_bytes(b"new image")
        return ApiResult(output)

    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", execute)
    async def run():
        generated = await produce_look_asset(config=config, project_dir=tmp_path, request=request,
                                            output_path=output, feature="look.test")
        reused = await produce_look_asset(config=config, project_dir=tmp_path, request=request,
                                         output_path=output, feature="look.test")
        return generated, reused
    generated, reused = asyncio.run(run())
    assert (generated.status, reused.status) == ("generated", "reused")
    assert len(calls) == 1
    assert json.loads((asset_versions_dir(output) / "v001.meta.json").read_text()) == {"old": "provenance"}


def test_held_request_is_not_sent_until_explicit_regeneration(tmp_path, monkeypatch):
    config = Config(image_model="image-gemini-pro")
    request = compile_non_panel_request(config, AssetGenerationInput(
        asset_identity="style_sample:1", prompt=GenerationPromptInput(visual_brief="Proof", width=819, height=1024),
    ))
    output = tmp_path / "samples/style_1.png"
    artifacts.write_asset_failure(output, {"classification": "provider_blocked", "provenance": {
        "execution_fingerprint": request.execution_fingerprint,
    }})
    calls = []
    async def execute(**kwargs):
        calls.append(kwargs)
        output.write_bytes(b"new image")
        return ApiResult(output)
    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", execute)
    async def run():
        held = await produce_look_asset(config=config, project_dir=tmp_path, request=request,
                                       output_path=output, feature="look.test")
        assert not calls
        generated = await produce_look_asset(config=config, project_dir=tmp_path, request=request,
                                            output_path=output, feature="look.test", force=True)
        return held, generated
    held, generated = asyncio.run(run())
    assert (held.status, generated.status) == ("held", "generated")
    assert len(calls) == 1


@pytest.mark.parametrize("failure_phase", ["submission", "cropping"])
def test_batch_failure_retains_paid_usage_and_failed_item(tmp_path, monkeypatch, failure_phase):
    from novel_to_comic.ai.errors import AIStructuredResponseError
    from novel_to_comic.look_assets import produce_stage_look_asset
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import create_initial_state, load_state
    from novel_to_comic.usage import UsageRecord

    config = Config(image_model="image-gemini-pro")
    request = compile_non_panel_request(config, AssetGenerationInput(
        asset_identity="style_sample:1", asset_kind="style_sample",
        prompt=GenerationPromptInput(visual_brief="Proof", width=819, height=1024),
    ))
    usage = UsageRecord(provider="test", model="test", operation="image", image_count=1)

    async def execute(**kwargs):
        if failure_phase == "submission":
            raise AIStructuredResponseError("rejected response", usage_records=(usage,))
        kwargs["output_path"].write_bytes(b"new image")
        return ApiResult(kwargs["output_path"], usage=usage)

    async def crop(result):
        raise RuntimeError("cropping failed")

    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", execute)
    ctx = StageRuntime("style", create_initial_state("book", "novel.txt"), tmp_path)
    ctx.begin(total=1)
    outcome = asyncio.run(produce_stage_look_asset(
        ctx=ctx, item_id="proof", label="proof", config=config, project_dir=tmp_path,
        request=request, output_path=tmp_path / "samples/style_1.png", feature="look.test",
        on_generated=crop,
    ))
    assert outcome is None
    stage = load_state(tmp_path).stages["style"]
    assert stage.items_done == 0
    assert stage.items_failed == ["proof"]
    assert stage.usage_log == [usage.model_dump()]


def test_regenerating_prop_marks_descendant_state_stale(tmp_path, monkeypatch):
    config = Config(image_model="image-gemini-pro")
    request = compile_non_panel_request(config, AssetGenerationInput(
        asset_identity="prop:lantern", asset_kind="prop_ref",
        prompt=GenerationPromptInput(visual_brief="Lantern", width=819, height=1024),
    ))
    output = artifacts.prop_ref_path(tmp_path, "lantern")
    descendant = output.parent / "states" / "broken" / "ref.png"
    artifacts.write_asset_meta(descendant, {
        "entity_id": "lantern", "state_id": "broken", "canonical_parent_sha256": "old",
        "lineage_status": "current",
    })

    async def execute(**kwargs):
        kwargs["output_path"].write_bytes(b"new parent")
        return ApiResult(kwargs["output_path"])

    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", execute)
    asyncio.run(produce_look_asset(config=config, project_dir=tmp_path, request=request,
                                   output_path=output, feature="look.test"))
    assert artifacts.read_asset_meta(descendant)["lineage_status"] == "stale"


def test_character_check_failure_preserves_review_usage(tmp_path, monkeypatch):
    from novel_to_comic.usage import UsageRecord

    config = Config(image_model="image-gemini-pro")
    request = compile_non_panel_request(config, AssetGenerationInput(
        asset_identity="character:ann", asset_kind="character_ref",
        prompt=GenerationPromptInput(visual_brief="Ann", width=819, height=1024),
    ))
    image_usage = UsageRecord(provider="test", model="test", operation="image", image_count=1)
    review_usage = UsageRecord(provider="test", model="test", operation="text", input_tokens=20)
    observed = []

    async def execute(**kwargs):
        kwargs["output_path"].write_bytes(b"new parent")
        return ApiResult(kwargs["output_path"], usage=image_usage)

    async def review(*args, usage_sink, **kwargs):
        usage_sink(review_usage)
        raise RuntimeError("invalid review response")

    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", execute)
    monkeypatch.setattr("novel_to_comic.cast_roster.read_cast_story_bible", lambda _: object())
    monkeypatch.setattr("novel_to_comic.cast_design.review_ready", lambda *args: True)
    monkeypatch.setattr("novel_to_comic.cast_design.run_cast_review", review)
    outcome = asyncio.run(produce_look_asset(
        config=config, project_dir=tmp_path, request=request, output_path=tmp_path / "refs/ann/ref.png",
        feature="look.test", refresh_review=True, usage_sink=observed.append,
    ))
    assert outcome.status == "generated"
    assert outcome.result.additional_usage == (review_usage,)
    assert observed == [image_usage, review_usage]


def test_concurrent_resume_rechecks_reuse_inside_the_shared_semaphore(tmp_path, monkeypatch):
    config = Config(image_model="image-gemini-pro")
    request = compile_non_panel_request(config, AssetGenerationInput(
        asset_identity="style_sample:1", asset_kind="style_sample",
        prompt=GenerationPromptInput(visual_brief="Proof", width=819, height=1024),
    ))
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0)
        kwargs["output_path"].write_bytes(b"proof")
        return ApiResult(kwargs["output_path"])

    async def resume():
        semaphore = asyncio.Semaphore(1)
        return await asyncio.gather(*(produce_look_asset(
            config=config, project_dir=tmp_path, request=request,
            output_path=tmp_path / "samples/style_1.png", feature="look.test", semaphore=semaphore,
        ) for _ in range(2)))

    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", execute)
    outcomes = asyncio.run(resume())
    assert [outcome.status for outcome in outcomes] == ["generated", "reused"]
    assert len(calls) == 1
