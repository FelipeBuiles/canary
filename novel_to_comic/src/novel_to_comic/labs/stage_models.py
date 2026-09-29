"""Text-stage model comparison: the same stages, on the same inputs, per model.

Phases:
  extract_brief  Extract, then Brief, from the source project's novel text.
  adapt_plan     Adapt, then Plan, from the source project's approved Brief,
                 Style and Cast.

Every (phase, model) arm runs in its own copy of the source project, so arms
never share state and the source project is only read. Stages run exactly as
the server runs them, through ``StageRuntime`` and the stage's own ``run()``,
with the phase's model fields pinned to the arm's model. Calls are
made without a user in the AI request context: API models are operator-funded
and priced from provider usage; Claude and Codex subscription models use the
local subscription allowance and cost no credits or USD.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.artifacts import story_bible_path
from novel_to_comic.config import load_config
from novel_to_comic.stages import REGISTRY, clean_cascade
from novel_to_comic.state import STAGE_NAMES, PipelineState, StageState, load_state, save_state
from novel_to_comic.target_artifacts import TargetArtifacts

from . import storage

KIND = "stage_models"
PHASES: dict[str, tuple[str, ...]] = {
    "extract_brief": ("extract", "brief"),
    "adapt_plan": ("adapt", "plan"),
}
STAGE_MODEL_FIELDS = {
    "extract": "extraction_model", "brief": "brief_model",
    "adapt": "adapt_model", "plan": "plan_model",
}
DEFAULT_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
# Arms run concurrently per funding source; each arm's stages run in order.
_CONCURRENCY = {"api": 4, "codex_subscription": 1, "claude_subscription": 2}
# Run-local or regenerated state never copied into an arm's workspace.
_NEVER_COPY = {"requests", "draw", "finish", "exports", "cover", ".jobs", ".locks", ".canary", ".checkpoints"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def selectable_models() -> list[dict[str, Any]]:
    """Every text model the catalog offers here, API and local subscription."""
    from novel_to_comic.model_catalog import models

    return [
        {"id": model["id"], "label": model["label"], "provider": model["provider"],
         "funding": model["funding"], "available": model.get("available", True)}
        for model in models() if model["kind"] == "text"
    ]


def _funding(model: str) -> str:
    for entry in selectable_models():
        if entry["id"] == model:
            return entry["funding"]
    return "api"


def validate_spec(source_dir: Path, phases: list[str], models: list[str]) -> None:
    catalog = {model["id"]: model for model in selectable_models()}
    if not phases or any(phase not in PHASES for phase in phases):
        raise ValueError(f"Choose phases from: {', '.join(PHASES)}")
    if not 2 <= len(models) <= 4 or len(set(models)) != len(models):
        raise ValueError("Choose between two and four different models")
    if unknown := [model for model in models if model not in catalog]:
        raise ValueError(f"Unknown text model: {', '.join(unknown)}")
    if unavailable := [model for model in models if not catalog[model]["available"]]:
        raise ValueError(f"Not enabled in this server process: {', '.join(unavailable)}")
    if not (source_dir / "state.json").exists():
        raise ValueError("Source project not found")
    state = load_state(source_dir)
    if "adapt_plan" in phases:
        missing = [stage for stage in ("brief", "style", "cast")
                   if state.stages.get(stage, StageState()).status.value not in {"complete", "awaiting_review"}]
        if missing:
            raise ValueError(f"Adapt and Plan need the source project's {', '.join(missing)} first")


def arm_id(phase: str, model: str) -> str:
    return f"{phase}.{re.sub(r'[^A-Za-z0-9._-]', '-', model)}"


def _link_images(source: str, destination: str) -> None:
    """Hard-link read-only image inputs; copy everything a stage may rewrite.

    Canary replaces files atomically, so a write in the workspace breaks the
    link instead of changing the source project.
    """
    if Path(source).suffix.lower() in _IMAGE_SUFFIXES:
        try:
            os.link(source, destination)
            return
        except OSError:
            pass
    shutil.copy2(source, destination)


def prepare_workspace(source_dir: Path, workspace: Path, phase: str) -> None:
    """Copy the source project so this arm starts from exactly its inputs."""
    if phase == "extract_brief":
        workspace.mkdir(parents=True)
        shutil.copy2(source_dir / "config.yaml", workspace / "config.yaml")
        shutil.copytree(source_dir / "input", workspace / "input")
    else:
        def top_level_only(directory: str, names: list[str]) -> list[str]:
            return [name for name in names if name in _NEVER_COPY] if Path(directory) == source_dir else []

        shutil.copytree(source_dir, workspace, ignore=top_level_only, copy_function=_link_images)
        for path in clean_cascade(workspace, "adapt"):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
    state = load_state(source_dir)
    for stage in STAGE_NAMES[STAGE_NAMES.index(PHASES[phase][0]):]:
        state.stages[stage] = StageState()
    novel = Path(state.novel_path)
    state.novel_path = str(workspace / "input" / novel.name)
    save_state(state, workspace)


def summarize_outputs(workspace: Path, stage: str) -> dict[str, Any]:
    """Counts and validator results a reader can compare across arms."""
    target = TargetArtifacts(workspace)

    def read(path: Path) -> Any:
        return json.loads(path.read_text()) if path.exists() else None

    def list_counts(value: Any) -> dict[str, int]:
        return {key: len(item) for key, item in (value or {}).items() if isinstance(item, list)}

    if stage == "extract":
        return {"counts": list_counts(read(story_bible_path(workspace))), "artifact": "story_bible.json"}
    if stage == "brief":
        return {"counts": list_counts(read(target.brief_path)),
                "artifact": str(target.brief_path.relative_to(workspace))}
    validation = read(target.validation_path(stage)) or {}
    summary: dict[str, Any] = {
        "validation": {
            "attempts": validation.get("attempts"),
            "invariant_failures": len(validation.get("invariant_failures") or []),
            "editorial_issues": len(validation.get("editorial_issues") or []),
            "blocking_issues": sum(1 for issue in validation.get("editorial_issues") or []
                                   if issue.get("blocking")),
        },
    }
    if stage == "adapt":
        book = read(target.adaptation_path) or {}
        summary |= {"counts": list_counts(book) | list_counts(book.get("treatment")),
                    "artifact": str(target.adaptation_path.relative_to(workspace))}
    else:
        book = read(target.plan_path) or {}
        pages = [read(target.page_path(page["page_number"])) or {} for page in book.get("pages") or []]
        summary |= {
            "counts": {"pages": len(pages), "panels": sum(len(page.get("content") or []) for page in pages)},
            "artifact": str(target.plan_path.relative_to(workspace)),
        }
    return summary


def api_equivalent_usd(log: list[dict[str, Any]]) -> float | None:
    """What these calls would cost on Canary's API route for the same model, from recorded tokens.

    Subscription calls report real token counts, so this is exact per-token
    pricing, not an estimate of consumption. Canary's Anthropic requests set no
    ``cache_control``, so Claude input is priced uncached even when a Claude
    subscription session cached it; OpenAI caches prompts automatically, so its
    cached input is priced at the cache-read rate. Codex counts may include
    agent-harness overhead and reasoning at Codex's own effort, not Canary's.
    None if any call's model has no configured price.
    """
    from novel_to_comic.model_costs import get_pricing_resolver

    resolver = get_pricing_resolver()
    total = 0.0
    for entry in log:
        model = str(entry.get("provider_model") or entry.get("model") or "").rsplit("/", 1)[-1]
        pricing, _ = resolver._pricing_for(resolver.resolve_model(model))
        if not pricing or not pricing.get("input_cost_per_token"):
            return None
        input_tokens, output_tokens = entry.get("input_tokens") or 0, entry.get("output_tokens") or 0
        cached = 0 if model.startswith("claude") else min(entry.get("cached_text_tokens") or 0, input_tokens)
        suffix = "_above_272k_tokens" if input_tokens > 272_000 else ""
        input_rate = pricing.get(f"input_cost_per_token{suffix}", pricing["input_cost_per_token"])
        cache_rate = pricing.get(f"cache_read_input_token_cost{suffix}",
                                 pricing.get("cache_read_input_token_cost", input_rate))
        output_rate = pricing.get(f"output_cost_per_token{suffix}", pricing["output_cost_per_token"])
        total += (input_tokens - cached) * input_rate + cached * cache_rate + output_tokens * output_rate
    return round(total, 6)


def _usage_summary(state: PipelineState, stage: str) -> dict[str, Any]:
    log = state.stages[stage].usage_log
    total = lambda key: sum(entry.get(key) or 0 for entry in log)  # noqa: E731
    costs = [entry.get("cost_usd") for entry in log]
    return {
        "calls": len(log),
        "input_tokens": total("input_tokens"),
        "cached_input_tokens": total("cached_text_tokens"),
        "output_tokens": total("output_tokens"),
        "cost_usd": round(state.stages[stage].cost_usd, 6),
        "unpriced_calls": sum(1 for cost in costs if cost is None),
        "api_equivalent_usd": api_equivalent_usd(log),
        "models": sorted({str(entry.get("provider_model") or entry.get("model")) for entry in log}),
        "funding": sorted({str(entry.get("funding") or "api") for entry in log}),
    }


async def run_arm(user_root: Path, run_id: str, source: str, phase: str, model: str) -> None:
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.text_utils import clean_exception_message

    cell_id = arm_id(phase, model)
    workspace = storage.run_file(user_root, run_id, f"workspaces/{cell_id}")
    cell: dict[str, Any] = {"phase": phase, "model": model, "funding": _funding(model), "status": "running",
                            "started_at": storage.now(), "workspace": f"workspaces/{cell_id}", "stages": []}
    storage.write_cell(user_root, run_id, cell_id, cell)
    try:
        prepare_workspace(user_root / source, workspace, phase)
        config, _ = load_config(workspace)
        config = config.model_copy(update={
            STAGE_MODEL_FIELDS[stage]: model for stage in PHASES[phase]
        } | {"dev_model_selections": {}})
        state = load_state(workspace)
    except Exception as exc:
        storage.write_cell(user_root, run_id, cell_id, cell | {
            "status": "failed", "error": clean_exception_message(exc),
        })
        return
    for stage in PHASES[phase]:
        started = time.perf_counter()
        error = None
        try:
            with ai_request_context(stage=stage, project_name=f"labs/{run_id}/{cell_id}"):
                await REGISTRY[stage].run(config, workspace, StageRuntime(stage, state, workspace))
        except Exception as exc:
            error = clean_exception_message(exc)
        cell["stages"].append({
            "stage": stage,
            "status": "failed" if error else state.stages[stage].status.value,
            "error": error,
            "seconds": round(time.perf_counter() - started, 1),
            **_usage_summary(state, stage),
            **({} if error else summarize_outputs(workspace, stage)),
        })
        storage.write_cell(user_root, run_id, cell_id, cell)
        if error:
            break
    failed = any(stage["error"] for stage in cell["stages"])
    storage.write_cell(user_root, run_id, cell_id, cell | {
        "status": "failed" if failed else "ok",
        "seconds": round(sum(stage["seconds"] for stage in cell["stages"]), 1),
        "cost_usd": round(sum(stage["cost_usd"] for stage in cell["stages"]), 6),
        "api_equivalent_usd": _sum_known([stage.get("api_equivalent_usd") for stage in cell["stages"]]),
        "finished_at": storage.now(),
    })


def _sum_known(values: list[float | None]) -> float | None:
    return None if any(value is None for value in values) else round(sum(values), 6)


async def run(user_root: Path, run_id: str, source: str, phases: list[str], models: list[str]) -> None:
    semaphores = {funding: asyncio.Semaphore(limit) for funding, limit in _CONCURRENCY.items()}

    async def bounded(phase: str, model: str) -> None:
        async with semaphores[_funding(model)]:
            await run_arm(user_root, run_id, source, phase, model)

    await asyncio.gather(*(bounded(phase, model) for phase in phases for model in models))


def estimate_usd(source_dir: Path, phases: list[str], models: list[str]) -> dict[str, float | None]:
    """Price the source project's own recorded token usage at each model's rates.

    A rough guide, not a quote: models differ in output length and repair
    attempts. None when the source recorded no usage for a phase, and 0.0 for
    subscription models, which use the local allowance instead of USD.
    """
    from novel_to_comic.model_costs import get_pricing_resolver

    state = load_state(source_dir)
    resolver = get_pricing_resolver()
    estimates: dict[str, float | None] = {}
    for model in models:
        if _funding(model) != "api":
            estimates[model] = 0.0
            continue
        total = 0.0
        for phase in phases:
            log = [entry for stage in PHASES[phase] for entry in state.stages[stage].usage_log]
            if not log:
                estimates[model] = None
                break
            breakdown = resolver.calculate(
                model_alias=model, provider_model=resolver.resolve_model(model), operation="text",
                input_tokens=sum(entry.get("input_tokens") or 0 for entry in log),
                output_tokens=sum(entry.get("output_tokens") or 0 for entry in log),
            )
            total += breakdown.cost_usd or 0.0
        else:
            estimates[model] = round(total, 4)
    return estimates
