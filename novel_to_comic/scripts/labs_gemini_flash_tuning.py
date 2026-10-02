"""Labs experiment: can prompt placement and process changes fix Gemini 3.8 Flash's weak spots?

Baseline run 20261001-150550-2494ab (Gemini vs GPT-6.1 Sol vs Claude Opus 5.5)
found Gemini 3.8 Flash thin in Extract/Brief, coarse in Adapt (16 beats, ~10
source units each), and monotone in Plan (two panels on every page, up to 54
words in one panel, six emphasis mismatches). Its coarse Adapt also kept Plan
under the two-pass threshold, so Gemini never got the page-map pass or its
review.

Everything here is process-local; no production code or prompt changes. Arms:

  control     stock prompts and process, medium reasoning (noise control)
  tuned       stage-specific checklists appended after the context (Google's
              guidance for long prompts), plus forced two-pass Plan
  tuned_high  tuned, with high reasoning for every stage

The checklists restate production rules as concrete self-checks; they add no
new requirements. Narrative review calls stay stock so reviewers judge every
arm the same way. Variants run one after another because the patches are
process-global; within a variant both phases run concurrently.

Usage (from the repo root; paid Gemini API calls, roughly $0.5 per variant):

  novel_to_comic/.venv/bin/python novel_to_comic/scripts/labs_gemini_flash_tuning.py \\
      --user-root projects/947150d4-7d2f-4726-a018-5539f933ea56 --source the-egg run
  ... report RUN_ID [--baseline 20261001-150550-2494ab] [--include RUN_ID ...]
  ... run-peers   (tuned Sol and Opus through local subscriptions; needs the dev
                   server's CANARY_ENV, CANARY_CODEX_DEV_ENABLED, CANARY_CLAUDE_DEV_ENABLED)
  ... show-addenda

The run appears in Labs; do not use Labs' Retry on these cells, which would
rerun them with stock settings.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import difflib
import glob
import itertools
import json
import re
import statistics
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

MODEL = "gemini-3.8-flash"
VARIANTS = ("control", "tuned", "tuned_high")
PHASES = ("extract_brief", "adapt_plan")
BASELINE_RUN = "20261001-150550-2494ab"
TUNED_RUN = "20261001-161049-f1b950"
# Subscription peers for the fairness run: same checklists and forced two-pass Plan,
# each with its stock Plan schema (the generic detail schema is a Gemini workaround).
PEER_MODELS = ("codex-dev/text/gpt-6.1-sol", "claude-dev/text/claude-opus-5-5")
# Models whose calls get the checklists in tuned variants.
TUNED_MODELS = {MODEL}

_HEADER = "\n\nFINAL CHECKLIST (apply to the material above before you answer):\n"

ADDENDA: dict[str, str] = {
    "extract.story_bible": _HEADER + (
        "- Scenes: start a new scene at every change of place, time, or dramatic situation. "
        "An opening incident counts as its own scene even when it is narrated in a few sentences.\n"
        "- Locations: every setting where an event happens or is narrated as happening is a separate "
        "location, including the setting of an opening incident told in flashback or summary. "
        "Never merge two settings because one is brief.\n"
        "- Appearance states: whenever a character's or location's visible look changes or differs "
        "from its base (injury, death, damage, costume, age, transformation), record an "
        "appearance_states entry and a matching appearance_timeline entry.\n"
        "- Before answering, reread the source from beginning to end and confirm each paragraph is "
        "covered by a scene, and each setting and visible change by a location or state.\n"
    ),
    "brief.infer": _HEADER + (
        "- Essential events: one item per distinct event, reveal, or turn, in story order. "
        "Never fold several reveals into one item.\n"
        "- Keep concrete specifics the story relies on: named people, dates, places, numbers, "
        "and paired examples. Do not abstract them into general statements.\n"
        "- Record each point where a character's understanding or feeling changes as a character turn, "
        "and each open question a reader would notice as an ambiguity.\n"
        "- Protect memorable source lines verbatim when the adaptation should keep their exact wording.\n"
    ),
    "adapt.blueprint": _HEADER + (
        "- A beat is ONE moment a single panel could show. Most beats cite 1-4 source units. "
        "A beat citing more than 5 source units almost always holds several moments: split it, "
        "unless it is one continuous line of narration or speech.\n"
        "- Give each reveal, each reaction to a reveal, each question-and-answer turn that changes "
        "what a character knows, and each transition its own beat.\n"
        "- The page target is not a beat target; do not merge beats to fit pages.\n"
        "- Before answering, count source units per beat and split any beat that fails the rule above.\n"
    ),
    "adapt.lettering": _HEADER + (
        "- One lettering item is one balloon or caption: at most about 25 words. Split longer speeches "
        "into consecutive items with the same speaker, only at sentence boundaries.\n"
        "- Prefer the source's own wording; paraphrase only to fit a balloon, and keep protected "
        "language verbatim.\n"
    ),
    "plan.map": _HEADER + (
        "- Each page's emphasis must equal the narrative_function of at least one beat on that page.\n"
        "- Put a reveal at the top of a page, with its setup closing the previous page, so the page turn "
        "lands it.\n"
        "- Allocate pages so dialogue-heavy stretches are not crammed: a page should not carry more "
        "lettering than about 4-6 panels can hold at 25 words each.\n"
    ),
}
_PANEL_RULES = (
    "- Vary panel counts with the page's job: peaks and reveals 1-3 large panels; establishing and "
    "transition pages 2-4; dialogue-heavy prolongation 4-6. Never use the same panel count on more "
    "than three consecutive pages.\n"
    "- Keep each panel's lettering under about 25 words in total. When a beat carries more, spread "
    "its lettering across several panels of that beat (new angle, reaction, or close-up).\n"
)
ADDENDA["plan.detail"] = _HEADER + _PANEL_RULES
ADDENDA["plan.book"] = ADDENDA["plan.map"] + _PANEL_RULES
# The single-call Adapt path asks for beats and lettering together.
ADDENDA["adapt.book"] = ADDENDA["adapt.blueprint"] + ADDENDA["adapt.lettering"].removeprefix(_HEADER)


@contextlib.contextmanager
def variant_patches(variant: str) -> Iterator[None]:
    from novel_to_comic.ai import client
    from novel_to_comic import page_planning
    from novel_to_comic.labs import stage_models

    originals = {
        "chat": client._chat_completion,
        "two_pass": page_planning._TWO_PASS_PLAN_MIN_BEATS,
        "arm_id": stage_models.arm_id,
    }
    stage_models.arm_id = lambda phase, model: f"{originals['arm_id'](phase, model)}.{variant}"
    if variant != "control":
        stock = originals["chat"]

        async def tuned(**kwargs: Any) -> Any:
            addendum = ADDENDA.get(kwargs.get("feature") or "") if kwargs.get("model") in TUNED_MODELS else None
            if addendum:
                kwargs["user_content"] = kwargs["user_content"] + addendum
            return await stock(**kwargs)

        client._chat_completion = tuned
        # Plan takes the one-shot path when beats < threshold; 0 forces map + detail.
        page_planning._TWO_PASS_PLAN_MIN_BEATS = 0
    try:
        yield
    finally:
        client._chat_completion = originals["chat"]
        page_planning._TWO_PASS_PLAN_MIN_BEATS = originals["two_pass"]
        stage_models.arm_id = originals["arm_id"]


def _gemini_compatible(node: Any, drop_max_items: bool) -> Any:
    """Rewrite integer enums as equal min/max bounds; optionally drop maxItems.

    The rejected detail schema differs from every accepted one only by an integer
    ``enum`` (page_number) and ``maxItems`` (pages).
    """
    if isinstance(node, dict):
        node = {key: _gemini_compatible(value, drop_max_items) for key, value in node.items()
                if not (drop_max_items and key == "maxItems")}
        enum = node.get("enum")
        if node.get("type") == "integer" and isinstance(enum, list) and len(enum) == 1:
            node.pop("enum")
            node["minimum"] = node["maximum"] = enum[0]
        return node
    if isinstance(node, list):
        return [_gemini_compatible(value, drop_max_items) for value in node]
    return node


@contextlib.contextmanager
def detail_schema_patches(batch_pages: int | None, shared_panel: bool = False,
                          drop_max_items: bool = False) -> Iterator[None]:
    """Gemini rejected the Plan detail schema (400 INVALID_ARGUMENT) before generating.

    Rewrite the constructs only that schema uses; optionally also use Claude's
    shared panel definition and smaller batches. Process-local like the other patches.
    """
    from novel_to_comic import page_planning

    original_schema, original_batch = page_planning._plan_response_schema, page_planning.detail_batch_pages

    force_shared = shared_panel

    def compatible(references: Any, target_pages: Any = None, *, shared_panel: bool = False) -> dict:
        schema = original_schema(references, target_pages, shared_panel=shared_panel or force_shared)
        return _gemini_compatible(schema, drop_max_items) if target_pages is not None else schema

    page_planning._plan_response_schema = compatible
    if batch_pages:
        page_planning.detail_batch_pages = lambda model: batch_pages
    try:
        yield
    finally:
        page_planning._plan_response_schema = original_schema
        page_planning.detail_batch_pages = original_batch


async def resume_plan(user_root: Path, run_id: str, batch_pages: int | None,
                      shared_panel: bool = False, drop_max_items: bool = False,
                      only_variant: str | None = None) -> None:
    """Rerun only Plan for failed tuned arms, reusing their paid Adapt and cached page map."""
    from novel_to_comic.ai.context import ai_request_context
    from novel_to_comic.config import load_config
    from novel_to_comic.labs import stage_models, storage
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.stages import REGISTRY
    from novel_to_comic.state import load_state
    from novel_to_comic.text_utils import clean_exception_message
    import time

    run = storage.read_run(user_root, run_id) or {}
    for cell in run.get("cells", []):
        variant = cell.get("variant")
        if cell.get("phase") != "adapt_plan" or variant == "control" or cell.get("status") == "ok" \
                or (only_variant and variant != only_variant):
            continue
        workspace = storage.run_dir(user_root, run_id) / cell["workspace"]
        config, _ = load_config(workspace)
        config = config.model_copy(update={"adapt_model": MODEL, "plan_model": MODEL, "dev_model_selections": {},
                                           "text_reasoning_efforts": cell["reasoning_efforts"]})
        state = load_state(workspace)
        prior = next(stage for stage in cell["stages"] if stage["stage"] == "plan")
        # Every earlier Plan attempt, so totals keep their cost however often this resumes.
        resumed = prior.get("resumed") or {}
        earlier = resumed.get("attempts") or ([resumed["first_attempt"]] if "first_attempt" in resumed else [])
        attempts = earlier + [{k: v for k, v in prior.items() if k != "resumed"}]
        fixes = {"integer_enum": "min/max", "shared_panel": shared_panel,
                 "drop_max_items": drop_max_items, "batch_pages": batch_pages}
        print(f"{cell['cell_id']}: resuming plan {fixes} …", flush=True)
        started, error = time.perf_counter(), None
        with variant_patches(variant), detail_schema_patches(batch_pages, shared_panel, drop_max_items):
            try:
                with ai_request_context(stage="plan", project_name=f"labs/{run_id}/{cell['cell_id']}"):
                    await REGISTRY["plan"].run(config, workspace, StageRuntime("plan", state, workspace))
            except Exception as exc:
                error = clean_exception_message(exc)
        plan = {"stage": "plan", "status": "failed" if error else state.stages["plan"].status.value,
                "error": error, "seconds": round(time.perf_counter() - started, 1),
                "resumed": {**fixes, "attempts": attempts},
                **stage_models._usage_summary(state, "plan"),
                **({} if error else stage_models.summarize_outputs(workspace, "plan"))}
        stages = [stage for stage in cell["stages"] if stage["stage"] != "plan"] + [plan]
        storage.write_cell(user_root, run_id, cell["cell_id"], cell | {
            "stages": stages, "status": "failed" if error else "ok",
            "seconds": round(sum(stage["seconds"] for stage in stages + attempts), 1),
            "cost_usd": round(sum(stage["cost_usd"] for stage in stages + attempts), 6),
        })
        print(f"  {'failed: ' + error[:300] if error else 'ok'}", flush=True)


def _page_key(page_number: int) -> str:
    return f"page_{page_number:03d}"


def keyed_detail_schema(schema: dict) -> dict:
    """Replace the batch's page union with one required, fixed key per page.

    Gemini rejects ``anyOf`` over several page objects. A closed object with a
    property per locked page keeps every page's own constraints (its beats, its
    required lettering placements, its number via the key) without a union.
    """
    variants = schema["$defs"]["_PageDetailDraft"]["anyOf"]
    by_number = {}
    for variant in variants:
        number = variant["properties"]["page_number"]["enum"][0]
        page = {**variant, "properties": {k: v for k, v in variant["properties"].items() if k != "page_number"}}
        page["required"] = [k for k in variant.get("required", []) if k != "page_number"]
        by_number[_page_key(number)] = page
    properties = {k: v for k, v in schema["properties"].items() if k != "pages"}
    properties["pages_by_number"] = {"type": "object", "additionalProperties": False,
                                     "properties": by_number, "required": list(by_number)}
    defs = {k: v for k, v in schema["$defs"].items() if k != "_PageDetailDraft"}
    return {**schema, "$defs": defs, "properties": properties,
            "required": [("pages_by_number" if k == "pages" else k) for k in schema["required"]]}


def unkey_detail_response(value: Any) -> Any:
    """Turn ``pages_by_number`` back into the numbered page list Plan validates."""
    if not isinstance(value, dict) or "pages_by_number" not in value:
        return value
    pages = []
    for key, page in sorted(value["pages_by_number"].items()):
        match = re.fullmatch(r"page_(\d+)", key)
        if not match or not isinstance(page, dict):
            raise ValueError(f"Unexpected detail page key {key!r}")
        pages.append({**page, "page_number": int(match.group(1))})
    return {k: v for k, v in value.items() if k != "pages_by_number"} | {"pages": pages}


def generic_detail_schema(schema: dict, target_pages: Any) -> dict:
    """One page template for the whole batch, so the schema does not grow per page.

    Built from the shared-panel schema: beats are the batch's union, page numbers
    a range, and lettering placements a list whose items name their lettering
    ID, with no page-array bounds. Probes on 2026-10-01 found Gemini rejects
    (400 INVALID_ARGUMENT) both an anyOf over page variants and any page-array
    bound of 2+, independent of prompt and size. Per-page ownership and the page
    count move from the decoder to Plan's own validators
    (_compile_detail_response and _detail_matches_map), which already check it.
    """
    template = deepcopy(schema["$defs"]["_PageDetailDraft"]["anyOf"][0])
    numbers = [page.page_number for page in target_pages]
    template["properties"]["page_number"] = {"type": "integer", "minimum": min(numbers), "maximum": max(numbers)}
    lettering_ids = list(dict.fromkeys(item for page in target_pages for item in page.lettering_ids))
    placement = deepcopy(schema["$defs"]["_LetteringPlacementDraft"])
    placement["properties"] = {"lettering_item_id": {"type": "string", "enum": lettering_ids}
                               if lettering_ids else {"type": "string"}, **placement["properties"]}
    placement["required"] = ["lettering_item_id", *placement.get("required", [])]
    template["properties"]["lettering_placements"] = {"type": "array", "items": placement}
    template["required"] = list(dict.fromkeys([*template.get("required", []), "page_number"]))
    defs = {k: v for k, v in schema["$defs"].items() if k != "_PageDetailDraft"} | {"_PageDetailDraft": template}
    # Gemini rejects page arrays bounded at 2+ items (minItems or maxItems); the
    # count is checked by _compile_detail_response ("Expected N pages").
    pages = {k: v for k, v in schema["properties"]["pages"].items() if k not in ("minItems", "maxItems")}
    return {**schema, "$defs": defs, "properties": {**schema["properties"], "pages": pages}}


def ungeneric_detail_response(value: Any) -> Any:
    """Turn each page's placement list back into the ID-keyed map Plan validates."""
    if not isinstance(value, dict) or not isinstance(value.get("pages"), list):
        return value
    pages = []
    for page in value["pages"]:
        placements = page.get("lettering_placements") if isinstance(page, dict) else None
        if isinstance(placements, list):
            keyed: dict[str, Any] = {}
            for entry in placements:
                item_id = entry.get("lettering_item_id")
                if item_id in keyed:
                    raise ValueError(f"Page {page.get('page_number')} places lettering {item_id!r} twice.")
                keyed[item_id] = {k: v for k, v in entry.items() if k != "lettering_item_id"}
            page = {**page, "lettering_placements": keyed}
        pages.append(page)
    return {**value, "pages": pages}


@contextlib.contextmanager
def generic_detail_patches(batch_pages: int | None = None) -> Iterator[None]:
    from novel_to_comic import page_planning

    original_schema = page_planning._plan_response_schema
    original_compile = page_planning._compile_detail_response
    original_batch = page_planning.detail_batch_pages

    def schema(references: Any, target_pages: Any = None, *, shared_panel: bool = False) -> dict:
        if target_pages is None:
            return original_schema(references, target_pages, shared_panel=shared_panel)
        return generic_detail_schema(original_schema(references, target_pages, shared_panel=True), target_pages)

    def compile_response(value: Any, target_pages: Any, adaptation: Any) -> Any:
        return original_compile(ungeneric_detail_response(value), target_pages, adaptation)

    page_planning._plan_response_schema = schema
    page_planning._compile_detail_response = compile_response
    if batch_pages:
        page_planning.detail_batch_pages = lambda model: batch_pages
    try:
        yield
    finally:
        page_planning._plan_response_schema = original_schema
        page_planning._compile_detail_response = original_compile
        page_planning.detail_batch_pages = original_batch


@contextlib.contextmanager
def keyed_detail_patches(batch_pages: int | None = None) -> Iterator[None]:
    from novel_to_comic import page_planning

    original_schema = page_planning._plan_response_schema
    original_compile = page_planning._compile_detail_response
    original_batch = page_planning.detail_batch_pages

    def schema(references: Any, target_pages: Any = None, *, shared_panel: bool = False) -> dict:
        built = original_schema(references, target_pages, shared_panel=False)
        return keyed_detail_schema(built) if target_pages is not None else built

    def compile_response(value: Any, target_pages: Any, adaptation: Any) -> Any:
        return original_compile(unkey_detail_response(value), target_pages, adaptation)

    page_planning._plan_response_schema = schema
    page_planning._compile_detail_response = compile_response
    if batch_pages:
        page_planning.detail_batch_pages = lambda model: batch_pages
    try:
        yield
    finally:
        page_planning._plan_response_schema = original_schema
        page_planning._compile_detail_response = original_compile
        page_planning.detail_batch_pages = original_batch


async def plan_variant(user_root: Path, run_id: str, base_variant: str, name: str,
                       batch_pages: int | None, mode: str = "keyed") -> None:
    """Rerun Plan on a copy of a variant's workspace with the keyed detail schema.

    Adapt and the cached page map are reused (not re-paid); only Plan is new.
    """
    import shutil
    import time
    from novel_to_comic.ai.context import ai_request_context
    from novel_to_comic.config import load_config
    from novel_to_comic.labs import stage_models, storage
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.stages import REGISTRY, clean_cascade
    from novel_to_comic.state import load_state
    from novel_to_comic.text_utils import clean_exception_message

    base = json.loads(storage.run_file(user_root, run_id, f"cells/{_cell_id('adapt_plan', base_variant)}.json").read_text())
    cell_id = f"{stage_models.arm_id('adapt_plan', MODEL)}.{name}"
    source = storage.run_dir(user_root, run_id) / base["workspace"]
    workspace = storage.run_dir(user_root, run_id) / f"workspaces/{cell_id}"
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(source, workspace, ignore=shutil.ignore_patterns(".locks"))
    for path in clean_cascade(workspace, "plan"):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    config, _ = load_config(workspace)
    config = config.model_copy(update={"adapt_model": MODEL, "plan_model": MODEL, "dev_model_selections": {},
                                       "text_reasoning_efforts": base["reasoning_efforts"]})
    state = load_state(workspace)
    adapt = next(stage for stage in base["stages"] if stage["stage"] == "adapt")
    cell = {**{k: base[k] for k in ("phase", "funding", "reasoning_efforts")},
            "model": f"{MODEL} · {name}", "variant": name, "status": "running",
            "started_at": storage.now(), "workspace": f"workspaces/{cell_id}",
            "adapt_reused_from": base["cell_id"], "stages": [adapt]}
    storage.write_cell(user_root, run_id, cell_id, cell)
    print(f"{cell_id}: {mode} detail schema, batch {batch_pages or 'default'} …", flush=True)
    patches = keyed_detail_patches if mode == "keyed" else generic_detail_patches
    started, error = time.perf_counter(), None
    with variant_patches(base_variant), patches(batch_pages):
        try:
            with ai_request_context(stage="plan", project_name=f"labs/{run_id}/{cell_id}"):
                await REGISTRY["plan"].run(config, workspace, StageRuntime("plan", state, workspace))
        except Exception as exc:
            error = clean_exception_message(exc)
    plan = {"stage": "plan", "status": "failed" if error else state.stages["plan"].status.value,
            "error": error, "seconds": round(time.perf_counter() - started, 1),
            "detail_schema": mode, "batch_pages": batch_pages,
            **stage_models._usage_summary(state, "plan"),
            **({} if error else stage_models.summarize_outputs(workspace, "plan"))}
    stages = [adapt, plan]
    storage.write_cell(user_root, run_id, cell_id, cell | {
        "stages": stages, "status": "failed" if error else "ok", "finished_at": storage.now(),
        "seconds": round(sum(stage["seconds"] for stage in stages), 1),
        "cost_usd": round(sum(stage["cost_usd"] for stage in stages), 6),
    })
    print(f"  {'failed: ' + error[:300] if error else 'ok'}", flush=True)


def _cell_id(phase: str, variant: str) -> str:
    from novel_to_comic.labs.stage_models import arm_id
    return f"{arm_id(phase, MODEL)}.{variant}"


async def run_experiment(user_root: Path, source: str) -> str:
    from novel_to_comic.labs import stage_models, storage

    # validate_spec compares 2-6 distinct models; this run varies one model's settings.
    catalog = {entry["id"]: entry for entry in stage_models.selectable_models()}
    if not catalog.get(MODEL, {}).get("available"):
        raise SystemExit(f"{MODEL} is not selectable here; check GEMINI_API_KEY and the gateway route")
    state = stage_models.load_state(user_root / source)
    if missing := [stage for stage in ("brief", "style", "cast")
                   if state.stages[stage].status.value not in {"complete", "awaiting_review"}]:
        raise SystemExit(f"Adapt and Plan need the source project's {', '.join(missing)} first")
    efforts = {variant: {stage: ("high" if variant == "tuned_high" else "medium")
                         for phase in PHASES for stage in stage_models.PHASES[phase]}
               for variant in VARIANTS}
    run = storage.create_run(user_root, kind="stage_models", label=(
        f"{source} · Gemini 3.8 Flash tuning ({' vs '.join(VARIANTS)})"), spec={
        "project": source, "phases": list(PHASES), "models": [MODEL],
        "experiment": "labs_gemini_flash_tuning", "variants": list(VARIANTS),
        "baseline_run": BASELINE_RUN, "reasoning_efforts_by_variant": efforts,
        "estimated_cost_usd": {MODEL: None},
    })
    run_id = run["run_id"]
    storage.write_json(storage.run_file(user_root, run_id, "experiment/addenda.json"), ADDENDA)
    print(f"run {run_id}", flush=True)
    try:
        for variant in VARIANTS:
            print(f"variant {variant} …", flush=True)
            with variant_patches(variant):
                await asyncio.gather(*(
                    stage_models.run_arm(user_root, run_id, source, phase, MODEL,
                                         {stage: efforts[variant][stage] for stage in stage_models.PHASES[phase]})
                    for phase in PHASES
                ))
            for phase in PHASES:
                path = storage.run_file(user_root, run_id, f"cells/{_cell_id(phase, variant)}.json")
                cell = json.loads(path.read_text())
                storage.write_cell(user_root, run_id, cell["cell_id"],
                                   cell | {"model": f"{MODEL} · {variant}", "variant": variant})
                print(f"  {phase}: {cell['status']} ${cell.get('cost_usd')} {cell.get('seconds')}s", flush=True)
        storage.update_run(user_root, run_id, status="complete", finished_at=storage.now())
    except BaseException as exc:
        storage.update_run(user_root, run_id, status="failed", error=str(exc)[:500], finished_at=storage.now())
        raise
    return run_id


async def run_peers(user_root: Path, source: str) -> str:
    """Tuned arms for the subscription peers, for a like-for-like comparison."""
    from novel_to_comic.labs import stage_models, storage

    catalog = {entry["id"]: entry for entry in stage_models.selectable_models()}
    if missing := [model for model in PEER_MODELS if not catalog.get(model, {}).get("available")]:
        raise SystemExit(f"Not selectable here: {', '.join(missing)}; export the dev server's subscription settings")
    efforts = {model: {stage: "medium" for phase in PHASES for stage in stage_models.PHASES[phase]}
               for model in PEER_MODELS}
    run = storage.create_run(user_root, kind="stage_models", label=(
        f"{source} · tuned checklists on GPT-6.1 Sol and Claude Opus 5.5"), spec={
        "project": source, "phases": list(PHASES), "models": list(PEER_MODELS),
        "experiment": "labs_gemini_flash_tuning", "variants": ["tuned"],
        "baseline_run": BASELINE_RUN, "tuned_gemini_run": TUNED_RUN,
        "reasoning_efforts": efforts, "estimated_cost_usd": {model: 0.0 for model in PEER_MODELS},
    })
    run_id = run["run_id"]
    storage.write_json(storage.run_file(user_root, run_id, "experiment/addenda.json"), ADDENDA)
    print(f"run {run_id}", flush=True)
    TUNED_MODELS.update(PEER_MODELS)
    try:
        with variant_patches("tuned"):
            await stage_models.run(user_root, run_id, source, list(PHASES), list(PEER_MODELS), efforts)
        for model in PEER_MODELS:
            for phase in PHASES:
                path = storage.run_file(user_root, run_id, f"cells/{stage_models.arm_id(phase, model)}.tuned.json")
                cell = json.loads(path.read_text())
                storage.write_cell(user_root, run_id, cell["cell_id"],
                                   cell | {"model": f"{model} · tuned", "variant": "tuned"})
                print(f"  {model} {phase}: {cell['status']} ~${cell.get('api_equivalent_usd')} "
                      f"{cell.get('seconds')}s", flush=True)
        storage.update_run(user_root, run_id, status="complete", finished_at=storage.now())
    except BaseException as exc:
        storage.update_run(user_root, run_id, status="failed", error=str(exc)[:500], finished_at=storage.now())
        raise
    finally:
        TUNED_MODELS.difference_update(PEER_MODELS)
    return run_id


# ── Report ─────────────────────────────────────────────────────────────────


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("—", " ").replace("-", " "))


def _source_units(workspace: Path) -> dict[str, str]:
    units: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if str(node.get("id", "")).startswith("source_") and "text" in node:
                units[node["id"]] = node["text"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads((workspace / "source/source.json").read_text()))
    return units


def extract_brief_metrics(workspace: Path) -> dict[str, Any]:
    bible = json.loads((workspace / "story_bible.json").read_text())
    brief = json.loads((workspace / "brief/adaptation_brief.json").read_text())
    states = sum(len(c.get("appearance_states") or []) for c in bible.get("characters", []))
    return {
        "scenes": len(bible.get("scenes", [])), "locations": len(bible.get("locations", [])),
        "character_states": states,
        "essential_events": len(brief.get("essential_events") or []),
        "character_turns": len(brief.get("character_turns") or []),
        "ambiguities": len(brief.get("ambiguities") or []),
        "protected_language": len(brief.get("protected_language") or []),
    }


def adapt_plan_metrics(workspace: Path) -> dict[str, Any]:
    adaptation = json.loads((workspace / "adapt/book.json").read_text())
    plan = json.loads((workspace / "plan/book.json").read_text())
    validation = json.loads((workspace / "plan/validation.json").read_text())
    units = _source_units(workspace)
    items = [item for beat in adaptation["beats"] for item in beat["lettering"]]
    words = {item["id"]: len(item["text"].split()) for item in items}
    pages = [json.loads(Path(path).read_text()) for path in sorted(glob.glob(str(workspace / "plan/pages/page_*.json")))]
    panels = [panel for page in pages for panel in page["content"]]
    panel_words = [sum(words.get(item["id"], 0) for item in panel["lettering"]) for panel in panels]
    counts = [len(page["content"]) for page in pages]
    longest_run = max(len(list(group)) for _, group in itertools.groupby(counts)) if counts else 0
    fidelity = []
    for item in items:
        source = _norm(" ".join(units.get(unit, "") for unit in item["source_unit_ids"]))
        text = _norm(item["text"])
        match = difflib.SequenceMatcher(None, text, source).find_longest_match(0, len(text), 0, len(source))
        fidelity.append(match.size / max(1, len(text)))
    return {
        "beats": len(adaptation["beats"]),
        "units_per_beat": round(statistics.mean(len(b["source_unit_ids"]) for b in adaptation["beats"]), 1),
        "lettering_items": len(items), "lettering_words": sum(words.values()),
        "near_verbatim_items": f"{sum(r >= 0.9 for r in fidelity)}/{len(fidelity)}",
        "pages": len(pages), "target": f"{plan.get('target_page_min')}-{plan.get('target_page_max')}",
        "panels": len(panels), "panels_per_page": dict(sorted(Counter(counts).items())),
        "longest_same_count_run": longest_run,
        "words_per_panel_mean": round(statistics.mean(panel_words), 1) if panel_words else 0,
        "words_per_panel_max": max(panel_words, default=0),
        "panels_over_35_words": sum(w > 35 for w in panel_words),
        "plan_attempts": validation.get("attempts"),
        "plan_warnings": dict(Counter(issue["code"] for issue in validation.get("editorial_issues", []))),
        "two_pass_plan": (workspace / "plan/plan_map_review.json").exists(),
    }


def _arms(user_root: Path, run_id: str) -> list[tuple[str, str, Path, dict[str, Any]]]:
    from novel_to_comic.labs import storage

    run = storage.read_run(user_root, run_id) or {}
    arms = []
    for cell in run.get("cells", []):
        if cell.get("status") != "ok":
            continue
        label = f"{run_id[-6:]} {cell['model']}"
        arms.append((cell["phase"], label, storage.run_dir(user_root, run_id) / cell["workspace"], cell))
    return arms


def report(user_root: Path, run_id: str, baseline: str | None, include: tuple[str, ...] = ()) -> str:
    arms = _arms(user_root, run_id) + [arm for other in include for arm in _arms(user_root, other)]
    arms += _arms(user_root, baseline) if baseline else []
    lines = [f"# Gemini 3.8 Flash tuning — run {run_id}", ""]
    if baseline:
        lines += [f"Baseline arms from {baseline} are included for reference (separate run; expect noise).", ""]
    for phase, measure in (("extract_brief", extract_brief_metrics), ("adapt_plan", adapt_plan_metrics)):
        rows = [(label, measure(workspace), cell) for p, label, workspace, cell in arms if p == phase]
        if not rows:
            continue
        keys = list(rows[0][1])
        lines += [f"## {phase}", "", "| metric | " + " | ".join(label for label, _, _ in rows) + " |",
                  "|---|" + "---|" * len(rows)]
        lines.append("| cost (USD, API or API-equivalent) | " + " | ".join(
            f"{cell.get('cost_usd') or cell.get('api_equivalent_usd') or 0:.3f}" for _, _, cell in rows) + " |")
        lines.append("| seconds | " + " | ".join(f"{cell.get('seconds')}" for _, _, cell in rows) + " |")
        for key in keys:
            lines.append(f"| {key} | " + " | ".join(str(metrics.get(key)) for _, metrics, _ in rows) + " |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--user-root", type=Path, default=Path("projects/947150d4-7d2f-4726-a018-5539f933ea56"))
    parser.add_argument("--source", default="the-egg")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    reporting = commands.add_parser("report")
    reporting.add_argument("run_id")
    reporting.add_argument("--baseline", default=BASELINE_RUN)
    reporting.add_argument("--include", nargs="*", default=[])
    commands.add_parser("run-peers")
    resuming = commands.add_parser("resume-plan")
    resuming.add_argument("run_id")
    resuming.add_argument("--batch-pages", type=int, default=None)
    resuming.add_argument("--shared-panel", action="store_true")
    resuming.add_argument("--drop-max-items", action="store_true")
    resuming.add_argument("--variant", choices=VARIANTS[1:])
    keyed = commands.add_parser("plan-variant")
    keyed.add_argument("run_id")
    keyed.add_argument("--from", dest="base_variant", default="tuned", choices=VARIANTS[1:])
    keyed.add_argument("--name", default="tuned_keyed")
    keyed.add_argument("--batch-pages", type=int, default=None)
    keyed.add_argument("--schema", choices=("keyed", "generic"), default="keyed")
    commands.add_parser("show-addenda")
    args = parser.parse_args()
    user_root = args.user_root.resolve()
    if args.command == "show-addenda":
        print(json.dumps(ADDENDA, indent=2))
    elif args.command == "run":
        run_id = asyncio.run(run_experiment(user_root, args.source))
        text = report(user_root, run_id, BASELINE_RUN)
        out = user_root / "_labs" / "runs" / run_id / "experiment" / "report.md"
        out.write_text(text)
        print(text)
    elif args.command == "plan-variant":
        asyncio.run(plan_variant(user_root, args.run_id, args.base_variant, args.name, args.batch_pages, args.schema))
        text = report(user_root, args.run_id, BASELINE_RUN)
        (user_root / "_labs" / "runs" / args.run_id / "experiment" / "report.md").write_text(text)
        print(text)
    elif args.command == "resume-plan":
        asyncio.run(resume_plan(user_root, args.run_id, args.batch_pages, args.shared_panel, args.drop_max_items, args.variant))
        text = report(user_root, args.run_id, BASELINE_RUN)
        (user_root / "_labs" / "runs" / args.run_id / "experiment" / "report.md").write_text(text)
        print(text)
    elif args.command == "run-peers":
        run_id = asyncio.run(run_peers(user_root, args.source))
        text = report(user_root, run_id, BASELINE_RUN, (TUNED_RUN,))
        (user_root / "_labs" / "runs" / run_id / "experiment" / "report.md").write_text(text)
        print(text)
    else:
        text = report(user_root, args.run_id, args.baseline or None, tuple(args.include))
        print(text)


if __name__ == "__main__":
    sys.exit(main())
