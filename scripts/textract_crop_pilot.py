#!/usr/bin/env python3
"""Bounded live Textract pilot using isolated, labeled saved-image fixtures.

Expected/actual/primary text is used only for local selection and scoring. Only
crop pixels reach the gateway. Existing receipts are reused, never retried.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "novel_to_comic/src"))

from novel_to_comic.config import Config
from novel_to_comic.page_review import _unmatched_observations
from novel_to_comic.text_utils import normalize_display_text
from ocr_crop_experiment import prepare_case

from novel_to_comic import textract_ocr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--max-requests", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.max_requests <= 100:
        parser.error("max-requests must be between 1 and 100")
    entries = json.loads(args.manifest.read_text())
    if not isinstance(entries, list) or not entries or len(entries) > 100:
        parser.error("manifest must contain 1–100 fixtures")
    ids = [entry["id"] for entry in entries]
    import re
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", item) for item in ids):
        parser.error("fixture IDs must be unique simple directory names")
    args.output.mkdir(parents=True, exist_ok=True)
    cases, count = [], 0
    for entry in entries:
        page, render, extraction, artifacts = prepare_case(entry, args.output)
        disputed = _unmatched_observations(page, extraction)
        plan = textract_ocr.prepare_plan(render=render, extraction=extraction, disputed=disputed,
            artifacts=artifacts, deadline=time.monotonic()+30) if disputed else None
        identities = {textract_ocr.recognition_identity(render, crop.sha256)
                      for crop in plan.crops if crop.status == "ready"} if plan else set()
        count += sum(not artifacts.textract_attempts(1, 1, identity) for identity in identities)
        cases.append((entry, page, render, extraction, artifacts, disputed))
    preview = {"fixtures": len(entries), "new_requests_upper_bound": count,
               "max_requests": args.max_requests}
    print(json.dumps(preview), flush=True)
    if count > args.max_requests:
        parser.error("request budget exceeded; nothing submitted")
    if not args.allow_paid:
        print("Prepared only. Use --allow-paid to submit the bounded pilot.")
        return
    os.environ["CANARY_TEXTRACT_ENABLED"] = "true"
    config = Config(litellm_base_url=os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
                    litellm_api_key=os.environ.get("LITELLM_API_KEY", "sk-local-canary"))
    async def check(case):
        entry, page, render, extraction, artifacts, disputed = case
        started = time.monotonic()
        await textract_ocr.run_checks(config=config, page=page, render=render, extraction=extraction,
                                     disputed=disputed, artifacts=artifacts)
        report = textract_ocr.cached_report(page=page, render=render, extraction=extraction,
                                           disputed=disputed, artifacts=artifacts) if disputed else None
        reads = report.readings if report else ()
        actual = normalize_display_text(entry.get("actual", entry["expected"]))
        rows = [{"text": read.text, "status": read.status, "verdict": read.verdict,
                 "minimum_confidence": min((line.confidence for line in read.lines), default=None),
                 "matches_labeled_pixels": normalize_display_text(read.text) == actual} for read in reads]
        return {"id": entry["id"], "seconds": round(time.monotonic()-started, 3),
                "complete": report.complete if report else True,
                "status": report.status if report else "matching_copy_skipped", "reads": rows}
    async def run():
        return await asyncio.gather(*(check(case) for case in cases))
    results = asyncio.run(run())
    (args.output / "results.json").write_text(json.dumps({**preview, "results": results}, indent=2)+"\n")
    print(json.dumps(results, indent=2))
    if any(not row["complete"] for row in results):
        raise SystemExit("Pilot has unfinished/unknown results; no automatic retry performed")


if __name__ == "__main__":
    main()
