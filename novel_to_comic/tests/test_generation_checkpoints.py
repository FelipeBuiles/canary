"""Paid responses survive stage restarts without recharging cached work."""

import asyncio
import json

import pytest

from novel_to_comic.generation_checkpoints import checkpointed_generator
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult


@pytest.mark.parametrize("stage", ["extract", "adapt", "plan"])
def test_checkpoint_resume_and_input_invalidation(tmp_path, stage):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        if kwargs["prompt"] == "fail":
            raise RuntimeError("provider interrupted")
        return ApiResult(value={"pages": [kwargs["prompt"]]})

    def run(model="gpt-5.6-luna", **kwargs):
        generator = checkpointed_generator(
            generate, artifacts=TargetArtifacts(tmp_path), stage=stage, model=model
        )
        return asyncio.run(generator(**kwargs))

    request = dict(prompt="batch-one", system="rules", schema={"type": "object"})
    assert run(**request).value == {"pages": ["batch-one"]}
    with pytest.raises(RuntimeError):
        run(**{**request, "prompt": "fail"})
    assert run(**request).usage is None
    assert len(calls) == 2  # A new wrapper/process resumes the completed batch.
    run(**{**request, "system": "new rules"})
    run(**{**request, "schema": {"type": "array"}})
    run(model="gpt-5.6-terra", **request)
    assert len(calls) == 5


def test_corrupt_checkpoint_is_regenerated(tmp_path):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value={"ok": True})

    generator = checkpointed_generator(
        generate, artifacts=TargetArtifacts(tmp_path), stage="plan", model="gpt-5.6-luna"
    )
    asyncio.run(generator(prompt="page"))
    next((tmp_path / ".checkpoints").rglob("*.json")).write_text("broken")
    assert asyncio.run(generator(prompt="page")).value == {"ok": True}
    assert len(calls) == 2


def test_rejected_response_can_be_replaced_without_discarding_other_batches(tmp_path):
    from novel_to_comic.generation_checkpoints import discard_checkpointed_response
    artifacts = TargetArtifacts(tmp_path)
    calls = []

    async def generate(**request):
        calls.append(request)
        return ApiResult(value={"attempt": len(calls)})

    generator = checkpointed_generator(generate, artifacts=artifacts, stage="plan", model="test")
    good = asyncio.run(generator(prompt="good"))
    bad = asyncio.run(generator(prompt="bad"))
    discard_checkpointed_response(artifacts=artifacts, stage="plan", model="test", request={"prompt": "bad"})
    assert asyncio.run(generator(prompt="good")).value == good.value
    assert asyncio.run(generator(prompt="bad")).value != bad.value
    assert len(calls) == 3
    rejected = list((tmp_path / ".checkpoints/plan/rejected").glob("*.json"))
    assert len(rejected) == 1
    assert json.loads(rejected[0].read_text())["value"] == bad.value
