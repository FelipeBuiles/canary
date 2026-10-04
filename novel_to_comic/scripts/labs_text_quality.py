"""Labs experiment: Extract and Brief quality, time and cost across text arms.

An arm is a model at one reasoning effort for both stages, written
``model:effort`` (``gemini-3.8-flash:low``). Every source runs every arm
``--repeats`` times as variants of one Labs ``stage_models`` run, so cells,
workspaces and outputs appear in Labs for side-by-side reading.

``judge`` compares two arms pairwise on each source and repeat. The judge model
reads the source text and both arms' Story Bible and Brief, in a random A/B
order it does not see, and scores a fixed rubric. Pick a judge that is not one
of the compared models; the default is Opus through the local Claude subscription. Judgments are evidence, not ground truth: read the
cited omissions and errors before trusting a win rate.

Usage (from the repo root; paid calls):

  novel_to_comic/.venv/bin/python novel_to_comic/scripts/labs_text_quality.py \\
      --user-root projects/<user> run --sources the-egg the-lady-or-the-tiger \\
      --arms gemini-3.8-flash:low gemini-3.8-flash:medium --repeats 3
  set -a; source <(grep -E '^CANARY_(ENV|CLAUDE_DEV_ENABLED)=' .env); set +a   # subscription judge
  ... judge RUN_ID [RUN_ID ...] --pair gemini-3.8-flash:low gemini-3.8-flash:medium
  ... report RUN_ID [RUN_ID ...] --pair gemini-3.8-flash:low gemini-3.8-flash:medium
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
from pathlib import Path
from typing import Any

PHASE = "extract_brief"
# Local Claude Code subscription: no credits or USD. Needs the dev server's CANARY_ENV and
# CANARY_CLAUDE_DEV_ENABLED=1 in this process; pass an API model to --judge-model otherwise.
JUDGE_MODEL = "claude-dev/text/claude-opus-5-5"
CRITERIA = {
    "scene_coverage": "Every event and turn of the source is represented by a scene, in order, at a useful granularity.",
    "entity_completeness": "Characters, locations and props that a comic artist must draw are present and distinct.",
    "visual_continuity": "Appearance changes (costume, injury, transformation, damage) are captured as states when they happen.",
    "accuracy": "Nothing is invented, misattributed or contradicted by the source.",
    "brief_fidelity": "Essential events, character turns, ambiguities and protected lines are faithful, specific and complete.",
}


def _arm(spec: str) -> tuple[str, str]:
    model, _, effort = spec.partition(":")
    if not effort:
        raise SystemExit(f"Arms are model:effort, got {spec!r}")
    return model, effort


def _variant(spec: str, repeat: int) -> str:
    return f"{_arm(spec)[1]}.r{repeat}"


def _cell_id(spec: str, repeat: int) -> str:
    from novel_to_comic.labs import stage_models
    return f"{stage_models.arm_id(PHASE, _arm(spec)[0])}.{_variant(spec, repeat)}"


async def run(user_root: Path, sources: list[str], arms: list[str], repeats: int,
              run_ids: list[str] | None = None) -> list[str]:
    """Run arms on new runs, or add them to existing runs (``run_ids``) to compare side by side."""
    from novel_to_comic.labs import stage_models, storage

    catalog = {entry["id"]: entry for entry in stage_models.selectable_models()}
    for spec in arms:
        model, effort = _arm(spec)
        if not catalog.get(model, {}).get("available"):
            raise SystemExit(f"{model} is not selectable here")
        stage_models.resolve_reasoning([PHASE], [model], {model: {"extract": effort, "brief": effort}})
    # Labs' own per-funding limits; subscriptions run on the local allowance.
    limits = {funding: asyncio.Semaphore(limit) for funding, limit in stage_models._CONCURRENCY.items()}
    if run_ids:
        sources = []
        for run_id in run_ids:
            existing = _read_run(user_root, run_id)
            spec = existing["spec"]
            if spec.get("experiment") != "labs_text_quality" or spec["repeats"] != repeats:
                raise SystemExit(f"{run_id} is not a text-quality run with {repeats} repeats")
            added = [arm for arm in arms if arm not in spec["arms"]]
            storage.update_run(user_root, run_id, status="running", spec=spec | {
                "arms": spec["arms"] + added,
                "models": sorted(set(spec["models"]) | {_arm(arm)[0] for arm in added})})
            sources.append(spec["project"])
        run_ids = list(run_ids)
    else:
        run_ids = []
        for source in sources:
            created = storage.create_run(user_root, kind="stage_models", label=(
                f"{source} · text quality ({' vs '.join(arms)}, ×{repeats})"), spec={
                "project": source, "phases": [PHASE], "models": sorted({_arm(spec)[0] for spec in arms}),
                "experiment": "labs_text_quality", "arms": arms, "repeats": repeats,
                "estimated_cost_usd": {},
            })
            run_ids.append(created["run_id"])
            print(f"{source}: run {created['run_id']}", flush=True)

    async def arm(run_id: str, source: str, spec: str, repeat: int) -> None:
        model, effort = _arm(spec)
        if storage.run_file(user_root, run_id, f"cells/{_cell_id(spec, repeat)}.json").exists():
            return
        async with limits[catalog[model]["funding"]]:
            await stage_models.run_arm(user_root, run_id, source, PHASE, model,
                                       {"extract": effort, "brief": effort}, variant=_variant(spec, repeat))
        cell = json.loads(storage.run_file(user_root, run_id, f"cells/{_cell_id(spec, repeat)}.json").read_text())
        print(f"  {source} {spec} r{repeat}: {cell['status']} {cell.get('seconds')}s ${cell.get('cost_usd')}"
              + (f" — {next((s['error'] for s in cell['stages'] if s.get('error')), '')[:160]}"
                 if cell["status"] == "failed" else ""), flush=True)

    await asyncio.gather(*(arm(run_id, source, spec, repeat)
                           for run_id, source in zip(run_ids, sources)
                           for repeat in range(1, repeats + 1) for spec in arms))
    for run_id in run_ids:
        storage.update_run(user_root, run_id, status="complete", finished_at=storage.now())
    return run_ids


def _read_run(user_root: Path, run_id: str) -> dict[str, Any]:
    from novel_to_comic.labs import storage

    run = storage.read_run(user_root, run_id)
    if run is None:
        raise SystemExit(f"No Labs run {run_id}")
    return run


def _outputs(user_root: Path, run_id: str, cell_id: str) -> dict[str, Any] | None:
    from novel_to_comic.labs import storage

    workspace = storage.run_file(user_root, run_id, f"workspaces/{cell_id}")
    try:
        bible = json.loads((workspace / "story_bible.json").read_text())
        brief = json.loads((workspace / "brief/adaptation_brief.json").read_text())
    except FileNotFoundError:
        return None
    brief = {key: value for key, value in brief.items() if key not in {"revision", "content_sha256", "status"}}
    return {"story_bible": bible, "adaptation_brief": brief}


def _judgment_path(user_root: Path, run_id: str, pair: list[str], repeat: int, judge_model: str) -> Path:
    from novel_to_comic.labs import storage

    name = "_vs_".join(pair).replace(":", "-").replace("/", "-")
    return storage.run_file(user_root, run_id, f"experiment/judge/{judge_model.rsplit('/', 1)[-1]}/{name}.r{repeat}.json")


def _judge_schema() -> dict[str, Any]:
    scores = {"type": "object", "additionalProperties": False, "required": list(CRITERIA),
              "properties": {name: {"type": "integer", "minimum": 1, "maximum": 5} for name in CRITERIA}}
    findings = {"type": "array", "items": {"type": "string"}}
    return {"type": "object", "additionalProperties": False,
            "required": ["scores_a", "scores_b", "omissions_a", "omissions_b", "errors_a", "errors_b",
                         "winner", "reason"],
            "properties": {"scores_a": scores, "scores_b": scores, "omissions_a": findings,
                           "omissions_b": findings, "errors_a": findings, "errors_b": findings,
                           "winner": {"type": "string", "enum": ["A", "B", "tie"]},
                           "reason": {"type": "string"}}}


async def judge(user_root: Path, run_ids: list[str], pair: list[str], judge_model: str) -> None:
    from novel_to_comic.ai.client import generate_structured_object
    from novel_to_comic.config import load_config
    from novel_to_comic.labs import storage

    config, _ = load_config(Path.cwd())
    rubric = "\n".join(f"- {name}: {text}" for name, text in CRITERIA.items())
    system = (
        "You evaluate two candidate extractions of the same source for a novel-to-comic pipeline. "
        "Each candidate is a Story Bible (scenes, characters, locations, props, appearance states) and an "
        "adaptation brief. Judge them only against the source text. Score each criterion 1-5:\n"
        f"{rubric}\n"
        "List concrete omissions and errors for each candidate, citing the source. Prefer specific, faithful, "
        "complete output over length; more items are not better unless the source supports them. "
        "Return the winner, or tie when neither is clearly better."
    )
    jobs = []
    for run_id in run_ids:
        run = _read_run(user_root, run_id)
        source_text = next((user_root / run["spec"]["project"] / "input").iterdir()).read_text(errors="replace")
        for repeat in range(1, run["spec"]["repeats"] + 1):
            outputs = [_outputs(user_root, run_id, _cell_id(spec, repeat)) for spec in pair]
            path = _judgment_path(user_root, run_id, pair, repeat, judge_model)
            if path.exists() or None in outputs:
                continue
            jobs.append((run_id, run["spec"]["project"], repeat, source_text, outputs, path))

    from novel_to_comic.labs import stage_models
    funding = next((entry["funding"] for entry in stage_models.selectable_models() if entry["id"] == judge_model), "api")
    limit = asyncio.Semaphore(stage_models._CONCURRENCY.get(funding, 4))

    async def one(run_id, source, repeat, source_text, outputs, path):
        order = [0, 1]
        random.Random(f"{run_id}{repeat}").shuffle(order)
        content = json.dumps({"source_text": source_text,
                              "candidate_A": outputs[order[0]], "candidate_B": outputs[order[1]]},
                             ensure_ascii=False)
        async with limit:
            result = await generate_structured_object(
                config=config, model=judge_model, system_prompt=system, user_content=content,
                json_schema=_judge_schema(), feature="labs.text_quality_judge", max_output_tokens=8000)
        verdict = result.value
        unblind = {"A": pair[order[0]], "B": pair[order[1]]}
        record = {"judge": judge_model, "pair": pair, "order": unblind, "verdict": verdict,
                  "winner": unblind.get(verdict["winner"], "tie"),
                  "scores": {unblind["A"]: verdict["scores_a"], unblind["B"]: verdict["scores_b"]},
                  "cost_usd": result.usage.cost_usd if result.usage else None}
        storage.write_json(path, record)
        print(f"  {source} r{repeat}: winner {record['winner']} (${record['cost_usd']})", flush=True)

    await asyncio.gather(*(one(*job) for job in jobs))


def report(user_root: Path, run_ids: list[str], pair: list[str], judge_model: str = JUDGE_MODEL) -> str:
    from novel_to_comic.labs import storage

    lines, wins, scores, totals = [], {spec: 0 for spec in pair + ["tie"]}, {spec: {c: [] for c in CRITERIA} for spec in pair}, {spec: {"seconds": [], "cost": [], "failed": 0} for spec in pair}
    for run_id in run_ids:
        run = _read_run(user_root, run_id)
        for repeat in range(1, run["spec"]["repeats"] + 1):
            for spec in pair:
                path = storage.run_file(user_root, run_id, f"cells/{_cell_id(spec, repeat)}.json")
                cell = json.loads(path.read_text()) if path.exists() else {"status": "missing"}
                if cell["status"] != "ok":
                    totals[spec]["failed"] += 1
                    continue
                totals[spec]["seconds"].append(cell["seconds"])
                totals[spec]["cost"].append(cell["cost_usd"])
            path = _judgment_path(user_root, run_id, pair, repeat, judge_model)
            if path.exists():
                record = json.loads(path.read_text())
                wins[record["winner"]] += 1
                for spec in pair:
                    for criterion, value in record["scores"][spec].items():
                        scores[spec][criterion].append(value)
    judged = sum(wins.values())
    lines.append(f"Judge {judge_model}. Pairwise judgments: {judged}  " + "  ".join(f"{k}: {v}" for k, v in wins.items()))
    lines.append(f"{'criterion':22}" + "".join(f"{spec:>28}" for spec in pair))
    for criterion in CRITERIA:
        lines.append(f"{criterion:22}" + "".join(
            f"{statistics.mean(scores[spec][criterion]) if scores[spec][criterion] else float('nan'):>28.2f}" for spec in pair))
    for label, key in (("median seconds", "seconds"), ("median cost USD", "cost")):
        lines.append(f"{label:22}" + "".join(
            f"{statistics.median(totals[spec][key]) if totals[spec][key] else float('nan'):>28.3f}" for spec in pair))
    lines.append(f"{'failed cells':22}" + "".join(f"{totals[spec]['failed']:>28}" for spec in pair))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--sources", nargs="+", default=[])
    run_parser.add_argument("--arms", nargs="+", required=True)
    run_parser.add_argument("--repeats", type=int, default=3)
    run_parser.add_argument("--run-ids", nargs="+", help="add the arms to these existing runs instead")
    for name in ("judge", "report"):
        sub = commands.add_parser(name)
        sub.add_argument("run_ids", nargs="+")
        sub.add_argument("--pair", nargs=2, required=True)
        sub.add_argument("--judge-model", default=JUDGE_MODEL)
    args = parser.parse_args()
    user_root = args.user_root.resolve()
    if args.command == "run":
        if not args.sources and not args.run_ids:
            raise SystemExit("Give --sources for new runs or --run-ids to extend runs")
        print(" ".join(asyncio.run(run(user_root, args.sources, args.arms, args.repeats, args.run_ids))))
    elif args.command == "judge":
        if args.judge_model.rsplit("/", 1)[-1] in {_arm(spec)[0].rsplit("/", 1)[-1] for spec in args.pair}:
            raise SystemExit("Choose a judge that is not one of the compared models")
        asyncio.run(judge(user_root, args.run_ids, args.pair, args.judge_model))
        print(report(user_root, args.run_ids, args.pair, args.judge_model))
    else:
        print(report(user_root, args.run_ids, args.pair, args.judge_model))


if __name__ == "__main__":
    main()
