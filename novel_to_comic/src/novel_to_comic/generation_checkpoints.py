"""Resume paid structured generation by its complete input, outside stage cleanup."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult


def _checkpoint_location(artifacts, stage, model, request):
    if stage not in {"extract", "adapt", "plan"}:
        raise ValueError("unsupported structured generation stage")
    encoded = json.dumps(
        {"version": 1, "model": model, "request": request},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    key = hashlib.sha256(encoded.encode()).hexdigest()
    return artifacts.project_dir / ".checkpoints" / stage / "responses" / f"{key}.json", encoded


def read_checkpointed_response(*, artifacts, stage, model, request) -> ApiResult[Any] | None:
    """Read exact saved output without submitting work on a cache miss."""
    path, encoded = _checkpoint_location(artifacts, stage, model, request)
    try:
        saved = json.loads(path.read_text())
        if saved["input"] == encoded:
            return ApiResult(value=saved["value"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def discard_checkpointed_response(*, artifacts, stage, model, request) -> None:
    """Do not replay a response already rejected by the owning validator.

    Only completed structured responses are removed. Transport errors never
    reach this path and therefore never authorize an ambiguous resubmission.
    """
    path, _ = _checkpoint_location(artifacts, stage, model, request)
    path.unlink(missing_ok=True)


def checkpointed_generator(
    generate: Callable[..., Awaitable[ApiResult[Any]]],
    *,
    artifacts: TargetArtifacts,
    stage: str,
    model: str,
) -> Callable[..., Awaitable[ApiResult[Any]]]:
    """Reuse a completed response; callers still run all current validators.

    Keys include the schema, instructions, model, and all supplied context. A
    repair is a different input and therefore a different checkpoint. Cached
    calls return no usage: their original provider event was already charged.
    """
    if stage not in {"extract", "adapt", "plan"}:
        raise ValueError("unsupported structured generation stage")

    async def run(**kwargs: Any) -> ApiResult[Any]:
        path, encoded = _checkpoint_location(artifacts, stage, model, kwargs)
        saved = read_checkpointed_response(artifacts=artifacts, stage=stage, model=model, request=kwargs)
        if saved is not None:
            return saved
        result = await generate(**kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps({"input": encoded, "value": result.value}, ensure_ascii=False)
        )
        temporary.replace(path)
        return result

    return run
