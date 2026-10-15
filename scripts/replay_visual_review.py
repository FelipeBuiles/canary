#!/usr/bin/env python3
"""Replay the current visual review against saved, author-labelled reviews.

Rebuilds each page's review inputs from workspace artifacts (traces carry no
images), compares the current prompt's findings with the saved findings, and
scores them against labels: an explicit labels file first, then the author's
issue decisions (dismissed = noise; accepted, resolved or revised = valid;
open = unlabelled).

Dry run by default: compiles every prompt, writes it to --out and estimates
spend, with no network calls. --live sends one paid review per page through the
configured gateway, always on a scratch copy of the series, so the real
workspace never gains reviews or issues. Pages whose Cast references changed
since the render are skipped: their saved review judged different authority.

Run with the dev server's environment so account model selections (and a
Codex edition, if the part uses one) resolve as they do in the app:

    CANARY_ENV=development CANARY_CODEX_DEV_ENABLED=1 \\
    novel_to_comic/.venv/bin/python scripts/replay_visual_review.py \\
        projects/<user>/<series>/parts/part_0001 --labels scripts/visual_review_labels.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "novel_to_comic" / "src"))

from novel_to_comic.config import (
    PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD,
    load_config,
)
from novel_to_comic.page_visual_review import (
    _prior_visual_issues,
    compile_visual_review,
    review_page_visuals,
    visual_review_prompt,
)
from novel_to_comic.server.account_models import account_config
from novel_to_comic.target_artifacts import (
    ArtifactMissing,
    TargetArtifacts,
)
from novel_to_comic.workspace import series_root

VALID_STATUSES = {"accepted", "resolved", "revised"}
# Categories that describe the same defect under the old and new taxonomy.
COMPATIBLE = [{"composition", "speaker"}, {"identity", "appearance"}]


def compatible(old: str, new: str) -> bool:
    return old == new or any({old, new} <= group for group in COMPATIBLE)


def label_for(issue_id: str, issues: dict, labels: dict[str, str]) -> str:
    if issue_id in labels:
        return labels[issue_id]
    status = issues.get(issue_id)
    if status == "dismissed":
        return "noise"
    if status in VALID_STATUSES:
        return "valid"
    return "unlabelled"


def baseline(artifacts: TargetArtifacts, page_number: int, render) -> tuple[list[dict], Decimal | None]:
    """Saved findings for this exact render, with their issue ids and paid cost."""
    reports = [report for report in artifacts.read_visual_reviews(page_number, render.revision)
               if report.render_image_sha256 == render.image_sha256]
    if not reports:
        return [], None
    report = reports[-1]
    findings = [
        {**finding.model_dump(mode="json"),
         "issue_id": finding.issue_id or f"visual-review-{report.input_sha256}-{index}"}
        for index, finding in enumerate(report.findings, 1)
    ]
    cost = report.usage.cost_usd if report.usage and report.usage.cost_usd is not None else None
    return findings, (Decimal(str(cost)) if cost is not None else None)


def pages_to_replay(part: Path):
    artifacts = TargetArtifacts(part)
    pages_dir = part / "draw" / "pages"
    for page_dir in sorted(pages_dir.glob("page_*")):
        page_number = int(page_dir.name.removeprefix("page_"))
        revision = artifacts.active_render_revision(page_number)
        if revision is None:
            continue
        yield artifacts, page_number, artifacts.read_provenance(page_number, revision).render


def scratch_part(part: Path, scratch: Path) -> Path:
    """Copy the series root with only this part, so writes stay disposable."""
    root = series_root(part)
    target = scratch / root.name
    if not target.exists():
        def ignore(directory: str, names: list[str]) -> set[str]:
            if Path(directory) == root / "parts":
                return {name for name in names if name != part.name}
            return set()
        shutil.copytree(root, target, ignore=ignore, symlinks=True)
    return target / part.relative_to(root)


def score(old: list[dict], new: list[dict], issues: dict, labels: dict[str, str]) -> list[dict]:
    rows = []
    for finding in old:
        matches = [index for index, candidate in enumerate(new, 1)
                   if candidate["panel_number"] == finding["panel_number"]
                   and compatible(finding["category"], candidate["category"])]
        rows.append({"issue_id": finding["issue_id"], "panel": finding["panel_number"],
                     "category": finding["category"], "observation": finding["observation"],
                     "label": label_for(finding["issue_id"], issues, labels), "kept_by": matches})
    return rows


def summarize(results: list[dict]) -> dict:
    rows = [row for result in results for row in result["old"]]
    valid = [row for row in rows if row["label"] == "valid"]
    noise = [row for row in rows if row["label"] == "noise"]
    matched = {(result["page"], index) for result in results for row in result["old"] for index in row["kept_by"]}
    new_total = sum(len(result["new"]) for result in results)
    return {
        "pages": len(results),
        "old_findings": len(rows),
        "new_findings": new_total,
        "valid_kept": f"{sum(bool(row['kept_by']) for row in valid)}/{len(valid)}",
        "noise_kept": f"{sum(bool(row['kept_by']) for row in noise)}/{len(noise)}",
        "new_unmatched_for_human_review": new_total - len(matched),
    }


def markdown(results: list[dict], summary: dict, model: str) -> str:
    lines = [f"# Visual review replay ({model})", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {key.replace('_', ' ')} | {value} |" for key, value in summary.items()]
    lines += ["", "Matching is panel + compatible category only: verify every row by eye."]
    for result in results:
        lines += ["", f"## {result['part']} page {result['page']} (render {result['render']})", "",
                  "| Label | Panel | Saved finding | Kept by new # |", "|---|---|---|---|"]
        for row in result["old"]:
            kept = ", ".join(map(str, row["kept_by"])) or "—"
            lines.append(f"| {row['label']} | {row['panel']} | {row['category']}: {row['observation']} | {kept} |")
        if result["new"]:
            lines += ["", "| New # | Panel | Impact | Finding | Reader impact |", "|---|---|---|---|---|"]
            for index, finding in enumerate(result["new"], 1):
                lines.append(f"| {index} | {finding['panel_number']} | {finding.get('impact')} | "
                             f"{finding['category']}: {finding['observation']} | {finding.get('reader_impact')} |")
        else:
            lines.append("\nNew review: no findings.")
    return "\n".join(lines) + "\n"


async def replay(args) -> int:
    labels = json.loads(Path(args.labels).read_text()) if args.labels else {}
    labels = {key: value for key, value in labels.items() if not key.startswith("_")}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="visual-review-replay-"))
    results, skipped, estimate = [], [], Decimal(0)
    try:
        for part_arg in args.parts:
            part = Path(part_arg).resolve()
            config, _ = load_config(part)
            # The server's view: projects/<user_id>/<series> with account model selections.
            user_dir = series_root(part).parent
            config = account_config(config, user_dir.parent, user_dir.name)
            if args.model:
                config = config.model_copy(update={"visual_review_model": args.model})
            model = config.effective_visual_review_model()
            for artifacts, page_number, render in pages_to_replay(part):
                if args.max_pages and len(results) >= args.max_pages:
                    break
                old, old_cost = baseline(artifacts, page_number, render)
                if not old and not args.include_unreviewed:
                    continue
                page = artifacts.read_page(page_number)
                producing = artifacts.producing_request(render)
                try:
                    compiled = compile_visual_review(part, config, artifacts, page)
                except (ValueError, ArtifactMissing) as exc:
                    skipped.append(f"{part.name} page {page_number}: {exc}")
                    continue
                if [ref.content_sha256 for ref in compiled.request.references] != [
                    ref.content_sha256 for ref in producing.references
                ]:
                    skipped.append(f"{part.name} page {page_number}: references changed since the render")
                    continue
                prompt = visual_review_prompt(
                    page=page, compiled=compiled, producing_request=producing,
                    prior_issues=_prior_visual_issues(artifacts, page, render, compiled),
                )
                (out / f"{part.name}_page_{page_number:03d}_prompt.txt").write_text(prompt)
                estimate += old_cost if old_cost is not None else Decimal(PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD)
                try:
                    statuses = {issue.id: issue.status for issue in artifacts.read_issues(page_number)}
                except ArtifactMissing:
                    statuses = {}
                new: list[dict] = []
                if args.live:
                    copy = TargetArtifacts(scratch_part(part, scratch))
                    report = (await review_page_visuals(
                        config=config, page=page, render=render,
                        image=copy.read_render(page_number, render.revision),
                        compiled=compile_visual_review(copy.project_dir, config, copy, page),
                        artifacts=copy, producing_request=copy.producing_request(render),
                    )).value
                    new = [finding.model_dump(mode="json") for finding in report.findings]
                results.append({"part": part.name, "page": page_number, "render": render.revision,
                                "model": model, "old": score(old, new, statuses, labels), "new": new})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for line in skipped:
        print(f"skipped {line}")
    if not args.live:
        print(f"Dry run: {len(results)} page prompts in {out}; a live replay costs about ${estimate:.2f} "
              f"(saved review costs where known, else the configured estimate).")
        return 0
    summary = summarize(results)
    (out / "replay.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False))
    (out / "replay.md").write_text(markdown(results, summary, results[0]["model"] if results else "-"))
    print(json.dumps(summary, indent=2))
    print(f"Report: {out / 'replay.md'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("parts", nargs="+", help="Part workspace directories (…/parts/part_NNNN)")
    parser.add_argument("--labels", help="JSON mapping issue_id to 'valid' or 'noise'; overrides author statuses")
    parser.add_argument("--model", help="Visual review model alias (defaults to the project's configured model)")
    parser.add_argument("--out", default="tmp/visual-review-replay", help="Output directory (default: %(default)s)")
    parser.add_argument("--max-pages", type=int, default=0, help="Stop after this many pages (0 = all)")
    parser.add_argument("--include-unreviewed", action="store_true", help="Also replay renders with no saved review")
    parser.add_argument("--live", action="store_true", help="Send paid review calls (on a scratch copy)")
    return asyncio.run(replay(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
