#!/usr/bin/env python3
"""Replay a local, human-labelled crop manifest without any provider requests.

Manifest entries: id, image, box [x,y,width,height] (page fractions), expected,
primary. Expected text is for offline scoring only; neither text reaches Paddle.
All artifacts are written to --output, never to the source project or image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import resource
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "novel_to_comic" / "src"))

from novel_to_comic.crop_ocr import PaddleCropReader, verify_mismatches
from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.models.draw import PageRenderRevision
from novel_to_comic.models.page import ComicPage, PageContent
from novel_to_comic.page_ocr import _PageOCRDraft, build_extraction
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.text_utils import normalize_display_text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument(
        "--python", required=True, help="Isolated Python with PaddleOCR installed"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    entries = json.loads(args.manifest.read_text())
    ids = [entry["id"] for entry in entries]
    if any(re.fullmatch(r"[a-zA-Z0-9_-]+", name) is None for name in ids) or len(
        set(ids)
    ) != len(ids):
        parser.error("Manifest IDs must be unique directory-safe names")
    reader = PaddleCropReader(args.python, args.models)
    results = []
    try:
        for entry in entries:
            image = Path(entry["image"]).read_bytes()
            with Image.open(entry["image"]) as opened:
                pixel_width, pixel_height = opened.size
            page = ComicPage(
                revision=1,
                page_number=1,
                adaptation_revision=1,
                adaptation_sha256="a" * 64,
                page_turn_role="setup",
                spread_role="right",
                emphasis="establisher",
                density_intent="standard",
                layout_intent="Offline crop verification fixture.",
                content=[
                    PageContent(
                        id="panel",
                        order=1,
                        beat_ids=["beat"],
                        visual_intent="Fixture",
                        lettering=[
                            LetteringItem(
                                id="caption",
                                kind="caption",
                                text=entry["expected"],
                                source_unit_ids=["source"],
                            )
                        ],
                    )
                ],
                reading_order=["panel", "caption"],
            )
            render = PageRenderRevision(
                page_number=1,
                revision=1,
                comic_page_revision=1,
                comic_page_sha256=page.content_sha256,
                request_sha256="b" * 64,
                image_sha256=hashlib.sha256(image).hexdigest(),
                width=pixel_width,
                height=pixel_height,
                provider="offline-fixture",
                model="offline-fixture",
                latency_ms=0,
                cost_usd="0",
            )
            x, y, width, height = entry["box"]
            extraction = build_extraction(
                _PageOCRDraft.model_validate(
                    {
                        "lettering": [
                            {
                                "text": entry["primary"],
                                "box": {
                                    "x": x,
                                    "y": y,
                                    "width": width,
                                    "height": height,
                                },
                            }
                        ]
                    }
                )
            )
            artifacts = TargetArtifacts(args.output / entry["id"])
            artifacts.write_render(page_number=1, render_revision=1, image=image)
            started = time.perf_counter()
            report = verify_mismatches(
                page=page,
                render=render,
                extraction=extraction,
                artifacts=artifacts,
                reader=reader,
            )
            recognized = " ".join(read.text for read in report.readings)
            actual = entry.get("actual", entry["expected"])
            row = {
                "id": entry["id"],
                "expected": entry["expected"],
                "primary": entry["primary"],
                "actual": actual,
                "close_up": recognized,
                "assessment": report.status,
                "crop_count": len(report.readings),
                "primary_correct": normalize_display_text(entry["primary"])
                == normalize_display_text(actual),
                "transcription_correct": normalize_display_text(recognized)
                == normalize_display_text(actual)
                if report.readings
                else None,
                "matches_expected": normalize_display_text(recognized)
                == normalize_display_text(entry["expected"])
                if report.readings
                else None,
                "scores": [
                    line.confidence for read in report.readings for line in read.lines
                ],
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "report_input_sha256": report.input_sha256,
            }
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        reader.close()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    metrics = {
        "reader_fingerprint": reader.fingerprint,
        "peak_child_rss_mb": round(
            usage.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1
        ),
        "child_cpu_seconds": round(usage.ru_utime + usage.ru_stime, 3),
        "note": "Local host measurements include initialization; they are not Lightsail benchmarks.",
    }
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    main()
