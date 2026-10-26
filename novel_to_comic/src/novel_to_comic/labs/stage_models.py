"""Text-stage model comparison: the same stages, on the same inputs, per model.

Phases:
  extract_brief  Extract, then Brief, from the source project's novel text.
  adapt_plan     Adapt, then Plan, from the source project's approved Brief,
                 Style and Cast.
  full           Extract, Brief, Adapt and Plan end to end, each stage reading
                 the arm's own earlier outputs, with the source project's
                 approved Style and Cast. Plan validates against the arm's own
                 Story Bible; Cast images are only used by Draw, which Labs
                 never runs, so their entity IDs need not match.

The first two phases hold every other stage's inputs fixed, so they compare
one stage at a time; ``full`` shows how a stage mix compounds. Within an arm a
stage runs on the same model in every phase that includes it.

Every (phase, comparison arm) runs in its own copy of the source project, so arms
never share state and the source project is only read. Stages run exactly as
the server runs them, through ``StageRuntime`` and the stage's own ``run()``,
with each stage's model field pinned to the model the arm chose for that
stage. An arm names a default model and may override it per stage, so a
mixed arm can, say, Adapt with one model and Plan with another. Calls are
made without a user in the AI request context: API models are operator-funded
and priced from provider usage; Claude and Codex subscription models use the
local subscription allowance and cost no credits or USD.

A failed arm can be retried by hand. The retry rebuilds the arm's workspace
from the source project and reruns every stage of its phase; it refuses to run
if the prepared inputs no longer match the fingerprint the arm recorded, so
the retried arm compares against the same inputs as the rest of the run. The
failed attempt's workspace and spend stay on the cell, never hidden.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
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
from novel_to_comic.text_models import default_reasoning, reasoning_options
from novel_to_comic.stages import REGISTRY, clean_cascade
from novel_to_comic.state import STAGE_NAMES, PipelineState, StageState, load_state, save_state
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import current_part_workspace, is_part_workspace, part_workspace, part_workspaces, series_root, workspace_part_id

from . import storage

KIND = "stage_models"
PHASES: dict[str, tuple[str, ...]] = {
    "extract_brief": ("extract", "brief"),
    "adapt_plan": ("adapt", "plan"),
    "full": ("extract", "brief", "adapt", "plan"),
}
# The source project's usage groups an estimate prices; see estimate_stages_usd.
_USAGE_GROUPS = (("extract", "brief"), ("adapt", "plan"))
# Approved stages a phase reads from the source project instead of running.
_NEEDS = {"adapt_plan": ("brief", "style", "cast"), "full": ("style", "cast")}
STAGE_MODEL_FIELDS = {
    "extract": "extraction_model", "brief": "brief_model",
    "adapt": "adapt_model", "plan": "plan_model",
}
DEFAULT_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
# Arms run concurrently per funding source; each arm's stages run in order.
_CONCURRENCY = {"api": 16, "codex_subscription": 1, "claude_subscription": 2}
# Run-local or regenerated state never copied into an arm's workspace.
_NEVER_COPY = {"requests", "draw", "finish", "exports", "cover", ".jobs", ".locks", ".canary", ".checkpoints", ".thumbnails"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def selectable_models() -> list[dict[str, Any]]:
    """Every text model the catalog offers here, API and local subscription."""
    from novel_to_comic.model_catalog import models

    return [
        {"id": model["id"], "label": model["label"], "provider": model["provider"],
         "funding": model["funding"], "available": model.get("available", True),
         "reasoning_options": list(reasoning_options(model["id"])),
         "default_reasoning": default_reasoning(model["id"])}
        for model in models() if model["kind"] == "text"
    ]


def _funding(model: str) -> str:
    for entry in selectable_models():
        if entry["id"] == model:
            return entry["funding"]
    return "api"


def _fundings(models: list[str]) -> list[str]:
    return sorted({_funding(model) for model in models})


def _cell_funding(models: list[str]) -> str:
    """How a cell's spend is reported: API if any stage spends USD."""
    fundings = _fundings(models)
    return "api" if "api" in fundings else fundings[0]


def source_workspace(root: Path, part_id: str | None = None) -> Path:
    """Resolve a Labs source without migrating or changing the project."""
    if part_id is None:
        return current_part_workspace(root)
    if not isinstance(part_id, str):
        raise ValueError("Invalid source part")
    try:
        TargetArtifacts(root).read_part_manifest().get(part_id)
        source = part_workspace(root, part_id)
        if not is_part_workspace(source) or not (source / "state.json").is_file():
            raise ValueError("Source part not found")
    except (KeyError, FileNotFoundError, ArtifactMissing, ArtifactInvalid) as exc:
        raise ValueError("Source part not found") from exc
    return source


def _validate_phases(phases: Any) -> None:
    if (not isinstance(phases, list) or not phases
            or any(not isinstance(phase, str) or phase not in PHASES for phase in phases)
            or len(set(phases)) != len(phases)):
        raise ValueError(f"Choose phases from: {', '.join(PHASES)}")


def validate_spec(source_dir: Path, phases: list[str], models: list[str]) -> None:
    """Check the source and every model the arms use; ``resolve_arms`` checks the arms."""
    source_dir = source_workspace(source_dir)
    catalog = {model["id"]: model for model in selectable_models()}
    _validate_phases(phases)
    if unknown := [model for model in models if model not in catalog]:
        raise ValueError(f"Unknown text model: {', '.join(unknown)}")
    if unavailable := [model for model in models if not catalog[model]["available"]]:
        raise ValueError(f"Not enabled in this server process: {', '.join(unavailable)}")
    if not (source_dir / "state.json").exists():
        raise ValueError("Source project not found")
    state = load_state(source_dir)
    for phase in phases:
        missing = [stage for stage in _NEEDS.get(phase, ())
                   if state.stages.get(stage, StageState()).status.value not in {"complete", "awaiting_review"}]
        if missing:
            label = "Adapt and Plan" if phase == "adapt_plan" else "The end-to-end phase"
            raise ValueError(f"{label} needs the source project's {', '.join(missing)} first")


def resolve_stage_models(phases: list[str], model: str, overrides: Any = None) -> dict[str, str]:
    """Every selected stage's model: the arm's default unless the stage overrides it."""
    stages = list(dict.fromkeys(stage for phase in phases for stage in PHASES[phase]))
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError("stage_models must be a stage-to-model mapping")
    for stage, chosen in overrides.items():
        if stage not in stages or not isinstance(chosen, str) or not chosen:
            raise ValueError(f"Invalid stage model for {stage}")
    return {stage: overrides.get(stage, model) for stage in stages}


def resolve_stage_reasoning(stage_models: dict[str, str], choices: Any = None) -> dict[str, str]:
    """Validate each stage's reasoning against the model that stage runs on."""
    if choices is None:
        choices = {}
    if not isinstance(choices, dict):
        raise ValueError("reasoning_efforts must be a stage-to-effort mapping")
    result = {stage: default_reasoning(model) for stage, model in stage_models.items()}
    for stage, effort in choices.items():
        if stage not in stage_models or effort not in reasoning_options(stage_models[stage]):
            raise ValueError(f"Unsupported reasoning for {stage_models.get(stage, '?')} / {stage}: {effort}")
        result[stage] = effort
    return result


def resolve_arms(phases: list[str], arms: Any) -> list[dict[str, Any]]:
    """Each selection has an independent identity, model and stage reasoning."""
    _validate_phases(phases)
    if not isinstance(arms, list) or not 2 <= len(arms) <= 6:
        raise ValueError("Choose between two and six comparison arms")
    result = []
    used = set()
    for arm in arms:
        if not isinstance(arm, dict):
            raise ValueError("Each comparison arm must be an object")
        identity, model = arm.get("id"), arm.get("model")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity) or identity in used:
            raise ValueError("Comparison arm IDs must be unique letters, numbers, underscores or hyphens")
        if not isinstance(model, str) or not model:
            raise ValueError("Each comparison arm needs a text model")
        used.add(identity)
        chosen = resolve_stage_models(phases, model, arm.get("stage_models"))
        reasoning = resolve_stage_reasoning(chosen, arm.get("reasoning_efforts", {}))
        result.append({"id": identity, "model": model, "stage_models": chosen, "reasoning_efforts": reasoning})
    return result


def arm_models(arms: list[dict[str, Any]]) -> list[str]:
    """Every distinct model the arms run, for validation."""
    return list(dict.fromkeys(model for arm in arms for model in arm["stage_models"].values()))


def estimate_arms_usd(source_dir: Path, phases: list[str], arms: list[dict[str, Any]]) -> dict[str, float | None]:
    """Each arm's phases priced separately, so a stage run in two phases counts twice."""
    return {arm["id"]: _sum_known([
        estimate_stages_usd(source_dir, {stage: arm["stage_models"][stage] for stage in PHASES[phase]})
        for phase in phases
    ]) for arm in arms}


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


def prepare_workspace(source_dir: Path, workspace: Path, phase: str) -> Path:
    """Snapshot series authorities and run the selected part in isolation."""
    source_dir = source_workspace(source_dir)
    root = series_root(source_dir)
    identifier = workspace_part_id(source_dir)
    if identifier is not None:
        # Preserve the complete series context, including prior adapted parts.
        # Exclude generated art and runtime history from every workspace.
        scope_dirs = {root, *[child for child in (root / "parts").iterdir() if child.is_dir()]}
        def series_inputs(directory: str, names: list[str]) -> list[str]:
            return [name for name in names if name in _NEVER_COPY] if Path(directory) in scope_dirs else []
        shutil.copytree(root, workspace, ignore=series_inputs, copy_function=_link_images)
        bundle = workspace
        # Every copied part must read its copied manuscript, including prior
        # parts consulted for continuity, rather than reaching back to the source.
        for copied_scope in [bundle, *part_workspaces(bundle)]:
            copied_state = load_state(copied_scope)
            copied_novel = Path(copied_state.novel_path)
            if copied_novel.is_relative_to(root):
                copied_state.novel_path = str(bundle / copied_novel.relative_to(root))
                save_state(copied_state, copied_scope)
        workspace = part_workspace(bundle, identifier)
        _clear(_regenerated(workspace, phase))
    elif phase == "extract_brief":
        workspace.mkdir(parents=True)
        shutil.copy2(source_dir / "config.yaml", workspace / "config.yaml")
        shutil.copytree(source_dir / "input", workspace / "input")
    else:
        def top_level_only(directory: str, names: list[str]) -> list[str]:
            return [name for name in names if name in _NEVER_COPY] if Path(directory) == source_dir else []
        shutil.copytree(source_dir, workspace, ignore=top_level_only, copy_function=_link_images)
        _clear(_regenerated(workspace, phase))
    state = load_state(source_dir)
    for stage in STAGE_NAMES[STAGE_NAMES.index(PHASES[phase][0]):]:
        if stage not in _NEEDS.get(phase, ()):
            state.stages[stage] = StageState()
    novel = Path(state.novel_path)
    if identifier is not None:
        if not novel.is_relative_to(root):
            raise ValueError("The source part's manuscript must belong to its series")
        state.novel_path = str(bundle / novel.relative_to(root))
    else:
        state.novel_path = str(workspace / "input" / novel.name)
    save_state(state, workspace)
    return workspace


def _regenerated(workspace: Path, phase: str) -> list[Path]:
    """The artifacts a phase rebuilds; the end-to-end phase keeps Style and Cast."""
    if phase == "extract_brief":
        return clean_cascade(workspace, "source")
    if phase == "full":
        return [workspace / "source", workspace / "brief", *clean_cascade(workspace, "adapt")]
    return clean_cascade(workspace, "adapt")


def _clear(paths: list[Path]) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def input_fingerprint(workspace: Path, *, only: tuple[str, ...] | None = None) -> str:
    """Hash the files a freshly prepared workspace starts from.

    ``state.json`` carries the workspace's own absolute paths and ``.canary``
    holds run diagnostics, so neither describes the arm's inputs. ``only``
    limits the hash to these top-level entries.
    """
    workspace = series_root(workspace)
    digest = hashlib.sha256()
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace)
        if not path.is_file() or path.name == "state.json" or ".canary" in relative.parts:
            continue
        if only is not None and relative.parts[0] not in only:
            continue
        digest.update(relative.as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class ChangedInputError(ValueError):
    """A retry would no longer start from the inputs the run recorded."""


# Arms recorded before fingerprints existed: their workspaces still hold the
# untouched config and novel, though later stage outputs share the directory.
_LEGACY_INPUTS = ("config.yaml", "input")


def _require_same_inputs(previous: dict[str, Any], previous_workspace: Path, workspace: Path) -> str:
    fingerprint = input_fingerprint(workspace)
    recorded = previous.get("input_sha256")
    if recorded:
        same = recorded == fingerprint
    else:
        same = previous_workspace.exists() and (
            input_fingerprint(previous_workspace, only=_LEGACY_INPUTS)
            == input_fingerprint(workspace, only=_LEGACY_INPUTS)
        )
    if not same:
        raise ChangedInputError(
            "The source project's inputs for this arm changed since the run; start a new run to compare them"
        )
    return fingerprint


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
    def words(items: list[dict[str, Any]]) -> int:
        # Reader-facing copy density: SFX is drawn display type, not reading load.
        return sum(len(str(item.get("text") or "").split()) for item in items if item.get("kind") != "sfx")

    if stage == "adapt":
        book = read(target.adaptation_path) or {}
        lettering = [item for beat in book.get("beats") or [] for item in beat.get("lettering") or []]
        summary |= {"counts": list_counts(book) | list_counts(book.get("treatment")) | {
                        "lettering_words": words(lettering),
                        "captions": sum(1 for item in lettering if item.get("kind") == "caption"),
                        "depicted_units": sum(1 for entry in book.get("ledger") or []
                                              if entry.get("disposition") == "depicted"),
                    },
                    "artifact": str(target.adaptation_path.relative_to(workspace))}
    else:
        book = read(target.plan_path) or {}
        pages = [read(target.page_path(page["page_number"])) or {} for page in book.get("pages") or []]
        panels = [panel for page in pages for panel in page.get("content") or []]
        page_words = [words([item for panel in page.get("content") or [] for item in panel.get("lettering") or []])
                      for page in pages]
        summary |= {
            "counts": {"pages": len(pages), "panels": len(panels),
                       "lettering_words": sum(page_words), "max_page_words": max(page_words, default=0),
                       "silent_panels": sum(1 for panel in panels if not panel.get("lettering"))},
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
    agent-harness overhead and reasoning at the experiment's configured effort.
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
        if input_tokens > 100_000 and "input_cost_per_token_above_100k_tokens" in pricing:
            suffix = "_above_100k_tokens"
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


async def run_arm(user_root: Path, run_id: str, source: str, phase: str, model: str,
                  reasoning_efforts: dict[str, str] | None = None, variant: str | None = None,
                  *, stage_models: dict[str, str] | None = None,
                  retry_of: dict[str, Any] | None = None, part_id: str | None = None) -> None:
    """Run one arm. ``model`` is the arm's default and ``stage_models``
    overrides it per stage. ``variant`` names an arm of a model already in the
    run, such as another reasoning effort, a stage mix or a repeat, with its own
    cell and workspace. ``retry_of`` is the failed cell being retried, if any."""
    from novel_to_comic.server.telemetry import ai_span
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.text_utils import clean_exception_message

    stage_models = resolve_stage_models([phase], model, stage_models)
    reasoning_efforts = resolve_stage_reasoning(stage_models, reasoning_efforts)
    cell_id = arm_id(phase, model) + (f".{re.sub(r'[^A-Za-z0-9._-]', '-', variant)}" if variant else "")
    bundle = storage.run_file(user_root, run_id, f"workspaces/{cell_id}")
    workspace = bundle
    attempts: list[dict[str, Any]] = []
    previous_workspace = workspace
    if retry_of is not None:
        attempts = list(retry_of.get("attempts", []))
        kept = f"workspaces/{cell_id}.attempt{len(attempts) + 1}"
        previous_workspace = storage.run_file(user_root, run_id, kept)
        if bundle.exists():
            bundle.rename(previous_workspace)
        if part_id is not None:
            previous_workspace = part_workspace(previous_workspace, part_id)
        stage_error = next((stage["error"] for stage in retry_of.get("stages", []) if stage.get("error")), None)
        attempts.append({key: retry_of.get(key) for key in (
            "started_at", "finished_at", "seconds", "cost_usd", "api_equivalent_usd", "input_sha256", "stages",
        )} | {"error": retry_of.get("error") or stage_error, "workspace": str(previous_workspace.relative_to(storage.run_dir(user_root, run_id)))})
    cell: dict[str, Any] = {"phase": phase, "model": model, "stage_models": stage_models,
                            "funding": _cell_funding(list(stage_models.values())), "status": "running",
                            "reasoning_efforts": reasoning_efforts, **({"variant": variant} if variant else {}),
                            "started_at": storage.now(), "workspace": f"workspaces/{cell_id}", "stages": [],
                            "attempts": attempts, **({"part_id": part_id} if part_id is not None else {})}
    storage.write_cell(user_root, run_id, cell_id, cell)
    try:
        source_dir = source_workspace(user_root / source, part_id)
        workspace = prepare_workspace(source_dir, bundle, phase)
        cell["workspace"] = str(workspace.relative_to(storage.run_dir(user_root, run_id)))
        if (identifier := workspace_part_id(source_dir)) is not None:
            cell["part_id"] = identifier
        if retry_of is not None:
            cell["input_sha256"] = _require_same_inputs(retry_of, previous_workspace, workspace)
        else:
            cell["input_sha256"] = input_fingerprint(workspace)
        config, _ = load_config(workspace)
        config = config.model_copy(update={
            STAGE_MODEL_FIELDS[stage]: stage_models[stage] for stage in PHASES[phase]
        } | {"dev_model_selections": {}, "text_reasoning_efforts": reasoning_efforts})
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
            # Each arm is one variant of the run's experiment on an opaque fixture ID.
            with ai_span(f"labs.{stage}", experiment_id=run_id, variant=cell_id, fixture_id=storage.fixture_id(source)), \
                    ai_request_context(stage=stage, project_name=f"labs/{run_id}/{cell_id}"):
                await REGISTRY[stage].run(config, workspace, StageRuntime(stage, state, workspace))
        except Exception as exc:
            error = clean_exception_message(exc)
        approved = False
        if error is None and stage != PHASES[phase][-1] and state.stages[stage].status.value == "awaiting_review":
            try:
                _approve_checkpoint(workspace, state, stage)
                approved = True
            except Exception as exc:
                error = f"Could not approve {stage} for the next stage: {clean_exception_message(exc)}"
        cell["stages"].append({
            "stage": stage,
            "status": "failed" if error else state.stages[stage].status.value,
            **({"auto_approved": True} if approved else {}),
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


def _approve_checkpoint(workspace: Path, state: PipelineState, stage: str) -> None:
    """Approve a checkpoint as the author's approve action does, so the phase can continue.

    Labs compares models, not author review: the end-to-end phase takes each
    arm's Brief as drafted. The cell records ``auto_approved`` on that stage.
    """
    from novel_to_comic.briefing import approve_brief
    from novel_to_comic.state import approve_stage

    if stage == "brief":
        target = TargetArtifacts(workspace)
        brief = target.read_brief()
        target.write_brief(approve_brief(brief, expected_revision=brief.revision))
    approve_stage(state, stage)
    save_state(state, workspace)


@contextlib.asynccontextmanager
async def _acquire(semaphores: dict[str, asyncio.Semaphore], models: list[str]):
    """Hold one slot of every funding source the arm's stages use, in a fixed order."""
    async with contextlib.AsyncExitStack() as stack:
        for funding in _fundings(models):
            await stack.enter_async_context(semaphores[funding])
        yield


def _sum_known(values: list[float | None]) -> float | None:
    return None if any(value is None for value in values) else round(sum(values), 6)


async def run(user_root: Path, run_id: str, source: str, phases: list[str], arms: list[dict[str, Any]], part_id: str | None = None) -> None:
    arms = resolve_arms(phases, arms)
    part_id = workspace_part_id(source_workspace(user_root / source, part_id))
    semaphores = {funding: asyncio.Semaphore(limit) for funding, limit in _CONCURRENCY.items()}

    async def bounded(phase: str, arm: dict[str, Any]) -> None:
        stages = PHASES[phase]
        async with _acquire(semaphores, [arm["stage_models"][stage] for stage in stages]):
            await run_arm(user_root, run_id, source, phase, arm["model"],
                          reasoning_efforts={stage: arm["reasoning_efforts"][stage] for stage in stages},
                          variant=arm["id"], stage_models={stage: arm["stage_models"][stage] for stage in stages},
                          **({"part_id": part_id} if part_id else {}))

    await asyncio.gather(*(bounded(phase, arm) for phase in phases for arm in arms))


def failed_cells(user_root: Path, run_id: str, cell_ids: list[str] | None) -> list[dict[str, Any]]:
    """The failed arms to retry: the named ones, or every failed arm."""
    run = storage.read_run(user_root, run_id)
    if run is None or run.get("kind") != KIND:
        raise ValueError("Run not found")
    failed = [cell for cell in run["cells"] if cell.get("status") == "failed"]
    if cell_ids is None:
        return failed
    selected = [cell for cell in failed if cell["cell_id"] in set(cell_ids)]
    if len(selected) != len(set(cell_ids)):
        raise ValueError("Only failed cells can be retried")
    return selected


async def retry(user_root: Path, run_id: str, cells: list[dict[str, Any]]) -> None:
    """Rerun failed arms with the model, reasoning and variant each one recorded."""
    run = storage.read_run(user_root, run_id) or {}
    source = (run.get("spec") or {})["project"]
    semaphores = {funding: asyncio.Semaphore(limit) for funding, limit in _CONCURRENCY.items()}

    async def bounded(cell: dict[str, Any]) -> None:
        async with _acquire(semaphores, list((cell.get("stage_models") or {"_": cell["model"]}).values())):
            await run_arm(user_root, run_id, source, cell["phase"], cell["model"],
                          cell.get("reasoning_efforts"), cell.get("variant"), stage_models=cell.get("stage_models"),
                          retry_of=cell, part_id=cell.get("part_id"))

    await asyncio.gather(*(bounded(cell) for cell in cells))


def estimate_stages_usd(source_dir: Path, stage_models: dict[str, str]) -> float | None:
    """Price the source project's own recorded token usage per stage, at each stage's model rates.

    A rough guide, not a quote: models differ in output length and repair
    attempts. None when the source recorded no usage for a whole phase;
    subscription stages add nothing, since they use the local allowance instead of USD.
    """
    from novel_to_comic.model_costs import get_pricing_resolver

    state = load_state(source_workspace(source_dir))
    resolver = get_pricing_resolver()
    if any(not any(state.stages[stage].usage_log for stage in stages)
           for stages in _USAGE_GROUPS if set(stages) & set(stage_models)):
        return None
    total = 0.0
    for stage, model in stage_models.items():
        log = state.stages[stage].usage_log
        if not log or _funding(model) != "api":
            continue
        breakdown = resolver.calculate(
            model_alias=model, provider_model=resolver.resolve_model(model), operation="text",
            input_tokens=sum(entry.get("input_tokens") or 0 for entry in log),
            output_tokens=sum(entry.get("output_tokens") or 0 for entry in log),
        )
        total += breakdown.cost_usd or 0.0
    return round(total, 4)
