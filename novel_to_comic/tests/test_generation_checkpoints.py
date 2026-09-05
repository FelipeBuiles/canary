"""Paid responses survive stage restarts without recharging cached work."""

import asyncio

import pytest

from novel_to_comic.generation_checkpoints import checkpointed_generator
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult


def test_checkpoint_resume_and_input_invalidation(tmp_path):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        if kwargs["prompt"] == "fail":
            raise RuntimeError("provider interrupted")
        return ApiResult(value={"pages": [kwargs["prompt"]]})

    def run(model="plan-fast", **kwargs):
        generator = checkpointed_generator(
            generate, artifacts=TargetArtifacts(tmp_path), stage="plan", model=model
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
    run(model="plan-quality", **request)
    assert len(calls) == 5


def test_corrupt_checkpoint_is_regenerated(tmp_path):
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value={"ok": True})

    generator = checkpointed_generator(
        generate, artifacts=TargetArtifacts(tmp_path), stage="plan", model="plan-fast"
    )
    asyncio.run(generator(prompt="page"))
    next((tmp_path / ".checkpoints").rglob("*.json")).write_text("broken")
    assert asyncio.run(generator(prompt="page")).value == {"ok": True}
    assert len(calls) == 2
