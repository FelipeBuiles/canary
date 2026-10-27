#!/usr/bin/env python3
"""Replay the Cold Open plan against saved projects. Provider-free; no artifacts written.

For each series it rebuilds the opening Story Bible that Extract's first source
section would have produced (later sections cannot rewrite its anchors), plans
the Cold Open on it, and reports the scene, looks, ~N credits, a latency
projection and whether the proofs could be adopted by the Style picker later.

    novel_to_comic/.venv/bin/python scripts/prototype_cold_open.py projects/<user>/*/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "novel_to_comic" / "src"))

from novel_to_comic.cold_open import plan_cold_open
from novel_to_comic.config import load_config
from novel_to_comic.extraction_sections import split_source
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.server.account_models import account_config
from novel_to_comic.server.credits import credit_estimate_for_provider_cost
from novel_to_comic.stages.s2_style import _style_sample_brief_source
from novel_to_comic.style_briefing import style_sample_selection
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import part_workspaces

from novel_to_comic import artifacts

# Production $ai_generation latency, last 45 days to 2026-10-26 (PostHog, seconds).
# Sunburst proof images only: the codex-dev adapter queues for minutes and is excluded.
LATENCY = {
    "p50": {"extract_section": 42.0, "brief_and_copy": 3.7, "proof_image": 22.0},
    "p90": {"extract_section": 98.5, "brief_and_copy": 9.3, "proof_image": 25.3},
}


def opening_snapshot(bible: StoryBible, part: Path, chunk_chars: int) -> tuple[StoryBible, bool]:
    """The Story Bible after Extract's first section, and whether Extract is sectioned."""
    source = TargetArtifacts(part).read_source()
    sections = split_source(source.text, chunk_chars)
    if len(sections) == 1:
        # One whole-source call: the Cold Open starts when Extract finishes.
        return bible, False
    opening_end = len(sections[0])
    starts = {unit.id: unit.start_offset for unit in source.units}
    opening_ids = {
        scene.id for scene in source.scenes if starts.get(scene.first_unit_id, opening_end) < opening_end
    }
    scenes = [scene for scene in bible.scenes if scene.id in opening_ids]
    character_ids = {character_id for scene in scenes for character_id in scene.character_ids}
    location_ids = {scene.location_id for scene in scenes}
    snapshot = bible.model_copy(update={
        "scenes": scenes,
        "total_scenes": len(scenes),
        "characters": [c for c in bible.characters if c.id in character_ids],
        "locations": [loc for loc in bible.locations if loc.id in location_ids],
        "sequences": [],
    })
    return snapshot, True


def replay(series: Path) -> dict | None:
    parts = part_workspaces(series)
    if not parts or not artifacts.story_bible_path(series).exists():
        return None
    part = parts[0]
    config, _ = load_config(part)
    user_dir = series.parent
    config = account_config(config, user_dir.parent, user_dir.name)
    try:
        bible = artifacts.read_story_bible(series)
        snapshot, sectioned = opening_snapshot(bible, part, config.extraction_chunk_chars)
    except Exception as error:  # noqa: BLE001 - report and continue the replay
        return {"series": series.name, "error": f"{type(error).__name__}: {error}"}
    if not snapshot.scenes:
        return {"series": series.name, "error": "no scene starts in the opening section"}
    plan = plan_cold_open(config, series, snapshot)
    estimate = credit_estimate_for_provider_cost(plan.cost_usd, "style", reserve=True)
    style_scene = style_sample_selection(bible).scene
    return {
        "series": series.name,
        "image_model": config.effective_image_model(),
        "sectioned_extract": sectioned,
        "opening_scenes": f"{len(snapshot.scenes)}/{len(bible.scenes)}",
        "scene": f"{plan.scene_id}: {plan.scene_title}",
        "summary": plan.scene_summary,
        "subjects": plan.subjects,
        "location": plan.location,
        "looks": [proof.label for proof in plan.proofs],
        "cost_usd": round(plan.cost_usd, 4),
        "estimate_credits": estimate["estimate_credits"],
        "reserved_credits": estimate["reserved_credits"],
        # Style's own proof would be the same request when its brief source matches.
        "same_scene_as_style": style_scene is not None and style_scene.id == plan.scene_id,
        "adoptable_by_style": _style_sample_brief_source(snapshot) == _style_sample_brief_source(bible),
        # The proofs run in parallel, so one image is on the critical path.
        "seconds_after_upload": {
            level: round(values["extract_section"] + values["brief_and_copy"] + values["proof_image"])
            for level, values in LATENCY.items()
        } if sectioned else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the Cold Open plan against saved projects.")
    parser.add_argument("series", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="print JSON lines")
    args = parser.parse_args()
    rows = [row for series in args.series if (row := replay(series.resolve()))]
    for row in rows:
        if args.json:
            print(json.dumps(row, ensure_ascii=False))
            continue
        if "error" in row:
            print(f"{row['series']}: skipped ({row['error']})\n")
            continue
        timing = row["seconds_after_upload"]
        wait = (
            f"~{timing['p50']}s p50 / ~{timing['p90']}s p90 after upload"
            if row["sectioned_extract"] else "when the single-pass Extract finishes, then ~26s"
        )
        print(
            f"{row['series']}  [{row['image_model']}]\n"
            f"  scene     {row['scene']} ({row['opening_scenes']} scenes in the opening)\n"
            f"            {row['summary']}\n"
            f"  subjects  {', '.join(row['subjects'])} @ {row['location']}\n"
            f"  looks     {' · '.join(row['looks'])}\n"
            f"  cost      ${row['cost_usd']} provider → ~{row['estimate_credits']} credits"
            f" (hold {row['reserved_credits']})\n"
            f"  ready     {wait}\n"
            f"  style     same scene: {row['same_scene_as_style']}, adoptable: {row['adoptable_by_style']}\n"
        )
    ok = [row for row in rows if "error" not in row]
    if ok and not args.json:
        adoptable = sum(row["adoptable_by_style"] for row in ok)
        credits = sorted(row["estimate_credits"] for row in ok)
        print(
            f"{len(ok)} series · credits {credits[0]}–{credits[-1]} (median {credits[len(credits) // 2]})"
            f" · adoptable by Style {adoptable}/{len(ok)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
