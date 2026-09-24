#!/usr/bin/env python3
"""Measure first-draft lettering placement against an author's saved placement.

Offline and provider-free: reads a project's Plan pages, current Draw renders
and saved lettering, reseeds each page with the *current* ``seed_lettering``
and lays both out with the local lettering engine (headless Chromium).

Ground truth is every element on a page the author edited (moved a balloon or
tail). Untouched pages only contribute structural checks (panel containment,
tail panel, reading order). Panels come from ``lettering.panels`` gutter
detection on the base art.

    novel_to_comic/.venv/bin/python scripts/measure_lettering_placement.py \
        projects/<account>/the-egg [--legacy] [--json out.json] [--verbose]
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import math
import statistics
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "novel_to_comic" / "src"))

from novel_to_comic.lettering.panels import detect_panels
from novel_to_comic.lettering.renderer import resolve_lettering
from novel_to_comic.lettering.service import (
    active_render,
    seed_lettering,
    seed_page,
)
from novel_to_comic.target_artifacts import (
    ArtifactMissing,
    TargetArtifacts,
)

TOLERANCE = 0.004  # A border line's width; gutters are wider.


def visible_rect(element) -> tuple[float, float, float, float]:
    """engine.mjs elementRect, scaled about its centre (rotation ignored)."""
    p = element.placement
    width = element.resolved.width if element.tight_box and element.resolved else p.width
    height = element.resolved.height if element.tight_box and element.resolved else p.height
    cx, cy = p.x + width / 2, p.y + height / 2
    width, height = width * element.scale, height * element.scale
    return cx - width / 2, cy - height / 2, width, height


def centre(rect):
    return rect[0] + rect[2] / 2, rect[1] + rect[3] / 2


def panel_of(point, panels) -> int:
    x, y = point
    for index, panel in enumerate(panels):
        if panel.x <= x <= panel.x + panel.width and panel.y <= y <= panel.y + panel.height:
            return index
    return min(  # In a gutter: nearest panel.
        range(len(panels)),
        key=lambda i: math.hypot(
            max(panels[i].x - x, 0, x - panels[i].x - panels[i].width),
            max(panels[i].y - y, 0, y - panels[i].y - panels[i].height),
        ),
    )


def contained(rect, panels) -> bool:
    x, y, w, h = rect
    return any(
        x >= p.x - TOLERANCE and y >= p.y - TOLERANCE
        and x + w <= p.x + p.width + TOLERANCE and y + h <= p.y + p.height + TOLERANCE
        for p in panels
    )


def distance(a, b, aspect: float) -> float:
    """Page-height units: x is scaled by the page's width/height."""
    return math.hypot((a[0] - b[0]) * aspect, a[1] - b[1])


def side(rect, target) -> tuple[str, str]:
    cx, cy = centre(rect)
    return ("left" if cx < target.x else "right"), ("above" if cy < target.y else "below")


def reading_order_kept(rects, panels) -> bool:
    """Panels in order; within one, a later balloon is never higher, and one
    that is not entirely to the right of its predecessor sits clearly lower."""
    tolerance = 0.01
    for a, b in itertools.pairwise(rects):
        pa, pb = panel_of(centre(a), panels), panel_of(centre(b), panels)
        if pb < pa:
            return False
        if pb == pa:
            right_of = b[0] >= a[0] + a[2] - tolerance
            if b[1] < a[1] - tolerance or (not right_of and b[1] < a[1] + a[3] / 2 - tolerance):
                return False
    return True


def measure(project: Path, legacy: bool = False) -> dict:
    artifacts = TargetArtifacts(project)
    style = artifacts.read_lettering_style()
    rows, pages = [], []
    for summary in artifacts.read_plan().pages:
        n = summary.page_number
        try:
            author = artifacts.read_lettering(n)
        except ArtifactMissing:
            continue
        page = artifacts.read_page(n)
        if author.comic_page_sha256 != page.content_sha256:
            continue
        render = active_render(artifacts, n)
        image = Image.open(io.BytesIO(artifacts.read_render(n, render.revision)))
        panels = detect_panels(image)
        aspect = render.width / render.height
        if legacy:  # Plan's reservation bounds only, as seeded before panel detection.
            seeded = resolve_lettering(seed_lettering(page, render, style, locale=author.locale), style)
        else:
            seeded = seed_page(artifacts, page, render, style, locale=author.locale)
        edited = any(
            e.placement != e.suggested_placement or e.tail_target != e.suggested_tail_target
            for e in author.elements
        )
        planned = {item.id: part.order for part in page.content for item in part.lettering}
        seed_rects = [visible_rect(e) for e in seeded.elements]
        pages.append({
            "page": n, "edited": edited, "panels": len(panels),
            "planned_panels": len(page.content),
            "reading_order_kept": reading_order_kept(seed_rects, panels),
        })
        by_id = {e.id: e for e in author.elements}
        for element, rect in zip(seeded.elements, seed_rects):
            mine = by_id[element.id]
            truth = visible_rect(mine)
            seed_panel = panel_of(centre(rect), panels)
            row = {
                "page": n, "id": element.id, "role": element.role, "edited_page": edited,
                "planned_panel": planned[element.id],
                "seed_panel": seed_panel + 1,
                "contained": contained(rect, panels),
                "tail_same_panel": (
                    None if element.tail_target is None
                    else panel_of((element.tail_target.x, element.tail_target.y), panels) == seed_panel
                ),
            }
            if edited:
                author_panel = panel_of(centre(truth), panels)
                row |= {
                    "author_panel": author_panel + 1,
                    "right_panel": author_panel == seed_panel,
                    "distance": distance(centre(rect), centre(truth), aspect),
                }
                if mine.tail_target is not None:
                    row["side_match"] = side(rect, mine.tail_target)[0] == side(truth, mine.tail_target)[0]
                    row["above_match"] = side(rect, mine.tail_target)[1] == side(truth, mine.tail_target)[1]
                    if element.tail_target is not None:
                        row["tail_distance"] = distance(
                            (element.tail_target.x, element.tail_target.y),
                            (mine.tail_target.x, mine.tail_target.y), aspect,
                        )
            rows.append(row)
    return {"pages": pages, "rows": rows, "summary": summarize(rows, pages)}


def _share(values) -> str:
    values = [v for v in values if v is not None]
    return f"{sum(values)}/{len(values)} ({100 * sum(values) / len(values):.0f}%)" if values else "n/a"


def summarize(rows, pages) -> dict:
    truth = [r for r in rows if r["edited_page"]]
    distances = [r["distance"] for r in truth]
    tails = [r["tail_distance"] for r in truth if "tail_distance" in r]
    return {
        "ground_truth_elements": len(truth),
        "ground_truth_pages": sorted({r["page"] for r in truth}),
        "centre_distance_mean": round(statistics.mean(distances), 3) if distances else None,
        "centre_distance_median": round(statistics.median(distances), 3) if distances else None,
        "within_0.10": _share([d <= 0.10 for d in distances]),
        "within_0.05": _share([d <= 0.05 for d in distances]),
        "right_panel": _share([r["right_panel"] for r in truth]),
        "speaker_side_match": _share([r.get("side_match") for r in truth]),
        "above_below_match": _share([r.get("above_match") for r in truth]),
        "tail_distance_median": round(statistics.median(tails), 3) if tails else None,
        "all_contained_in_one_panel": _share([r["contained"] for r in rows]),
        "all_tail_in_own_panel": _share([r["tail_same_panel"] for r in rows]),
        "author_panel_equals_planned_panel": _share(
            [r["author_panel"] == r["planned_panel"] for r in truth]
        ),
        "pages_reading_order_kept": _share([p["reading_order_kept"] for p in pages]),
        "pages_panel_count_matches_plan": _share([p["panels"] == p["planned_panels"] for p in pages]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--legacy", action="store_true", help="measure the pre-panel seed (baseline)")
    args = parser.parse_args()
    result = measure(args.project, args.legacy)
    if args.verbose:
        for row in result["rows"]:
            print(json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()}))
    for key, value in result["summary"].items():
        print(f"{key:36} {value}")
    if args.json:
        args.json.write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
