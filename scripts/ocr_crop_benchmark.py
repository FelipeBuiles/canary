"""Provider-free CPU/RAM and contention benchmark of the actual crop reader.

Use a manifest from ocr_crop_experiment.py and a fresh --output. Repeated crops
are a synthetic load envelope, not additional accuracy-labelled artwork.
Provision dependencies/models before running; inference needs no network.
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "novel_to_comic" / "src"))

from novel_to_comic.crop_ocr import PaddleCropReader, verify_mismatches
from novel_to_comic.models.page import ComicPage
from novel_to_comic.page_ocr import _PageOCRDraft, build_extraction
from novel_to_comic.page_review import _unmatched_observations
from novel_to_comic.text_utils import normalize_display_text
from ocr_crop_experiment import prepare_case

from novel_to_comic import crop_ocr


def cgroup_snapshot() -> dict:
    result = {}
    root = Path("/sys/fs/cgroup")
    for name in (
        "memory.current",
        "memory.peak",
        "memory.events",
        "cpu.stat",
        "cpu.max",
    ):
        try:
            result[name] = (root / name).read_text().strip()
        except OSError:
            pass
    return result


def process_snapshot(pid: int) -> dict:
    result = {}
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            key, _, value = line.partition(":")
            if key in {"VmRSS", "VmHWM", "Threads"}:
                result[key] = int(value.split()[0])
    except OSError:
        pass
    return result


def repeat_observations(page, render, extraction, count: int):
    """Repeat the same known region to measure the six-crop work budget."""
    if count == 1:
        return page, render, extraction
    data = page.model_dump(mode="json")
    original = data["content"][0]["lettering"][0]
    data["content"][0]["lettering"] = [
        {**original, "id": f"caption-{index}"} for index in range(count)
    ]
    data["reading_order"] = ["panel", *[f"caption-{index}" for index in range(count)]]
    data["content_sha256"] = ""
    page = ComicPage.model_validate(data)
    region = extraction.observed_regions[0]
    xs, ys = zip(*region.polygon, strict=True)
    box = {
        "x": min(xs),
        "y": min(ys),
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
    }
    extraction = build_extraction(
        _PageOCRDraft.model_validate(
            {
                "lettering": [
                    {"text": extraction.lettering[0].text, "box": box}
                    for _ in range(count)
                ],
            }
        )
    )
    render = render.model_copy(update={"comic_page_sha256": page.content_sha256})
    return page, render, extraction


def run_case(entry: dict, reader, output: Path, *, crops: int = 1) -> dict:
    started = time.perf_counter()
    page, render, extraction, artifacts = prepare_case(entry, output)
    page, render, extraction = repeat_observations(page, render, extraction, crops)
    report = verify_mismatches(
        page=page,
        render=render,
        extraction=extraction,
        artifacts=artifacts,
        reader=reader,
        disputed=_unmatched_observations(page, extraction),
    )
    actual = normalize_display_text(entry.get("actual", entry["expected"]))
    return {
        "id": entry["id"],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "status": report.status,
        "complete": report.complete,
        "crops": len(report.readings),
        "read_statuses": dict(Counter(read.status for read in report.readings)),
        "correct_reads": sum(
            normalize_display_text(read.text) == actual for read in report.readings
        ),
        "scores": [line.confidence for read in report.readings for line in read.lines],
        "worker_pid": reader._process.pid if reader._process is not None else None,
    }


def summarize(name: str, rows: list[dict], seconds: float) -> dict:
    elapsed = sorted(row["elapsed_ms"] for row in rows)
    return {
        "phase": name,
        "wall_seconds": round(seconds, 3),
        "pages": len(rows),
        "complete_pages": sum(row["complete"] for row in rows),
        "statuses": dict(Counter(row["status"] for row in rows)),
        "read_statuses": dict(
            sum((Counter(row["read_statuses"]) for row in rows), Counter())
        ),
        "correct_reads": sum(row["correct_reads"] for row in rows),
        "latency_ms": {
            "min": min(elapsed),
            "median": statistics.median(elapsed),
            "max": max(elapsed),
        },
        "worker_pids": sorted(
            {row["worker_pid"] for row in rows if row["worker_pid"] is not None}
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument(
        "--worker",
        type=Path,
        help="Optional shadow worker; its bytes enter the reader fingerprint",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="unspecified-host")
    parser.add_argument("--sustained-seconds", type=float, default=90)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 16])
    parser.add_argument("--crops", type=int, nargs="+", default=[1, 6])
    args = parser.parse_args()
    if args.output.exists():
        parser.error(
            "Use a fresh output directory; cached reports would invalidate timings"
        )
    if not 0 <= args.sustained_seconds <= 600 or any(
        not 1 <= n <= 16 for n in args.concurrency
    ):
        parser.error("Use 0–600 seconds and 1–16 concurrent pages")
    if any(not 1 <= n <= 6 for n in args.crops):
        parser.error("Use 1–6 crops per page")
    entries = json.loads(args.manifest.read_text())
    sample = next(
        (entry for entry in entries if entry["primary"] != entry["expected"]), None
    )
    if sample is None:
        parser.error("Manifest needs at least one disputed first read")
    args.output.mkdir(parents=True)
    if args.worker is not None:
        crop_ocr.WORKER_PATH = args.worker.resolve()
    reader = PaddleCropReader(args.python, args.models)
    stopped = threading.Event()
    samples = []
    phases, results = [], []
    before = cgroup_snapshot()

    def monitor():
        import os

        while not stopped.is_set():
            worker = reader._process
            samples.append(
                {
                    "time": time.monotonic(),
                    "parent": process_snapshot(os.getpid()),
                    "worker": process_snapshot(worker.pid)
                    if worker is not None
                    else {},
                    "cgroup": cgroup_snapshot(),
                }
            )
            stopped.wait(0.25)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()

    def phase(name: str, action):
        start = time.perf_counter()
        rows = action()
        summary = summarize(name, rows, time.perf_counter() - start)
        results.extend({"phase": name, **row} for row in rows)
        phases.append(summary)
        (args.output / "phases.json").write_text(json.dumps(phases, indent=2) + "\n")
        print(json.dumps(summary), flush=True)

    try:
        matching = {**sample, "id": "matching-cold", "primary": sample["expected"]}
        phase(
            "matching-cold",
            lambda: [run_case(matching, reader, args.output / "matching")],
        )
        if reader._process is not None:
            raise RuntimeError("Matching copy unexpectedly started the native worker")
        phase(
            "pilot",
            lambda: [
                run_case(entry, reader, args.output / "pilot") for entry in entries
            ],
        )
        if not any(row["complete"] and row["crops"] for row in results):
            raise RuntimeError(
                "Native OCR failed the initial pilot; inspect its runtime before load testing"
            )
        phase(
            "cached-pilot",
            lambda: [
                run_case(entry, reader, args.output / "pilot") for entry in entries
            ],
        )
        phase(
            "warm-serial",
            lambda: [
                run_case(sample, reader, args.output / f"warm-{i}") for i in range(10)
            ],
        )
        for crops in args.crops:
            for concurrency in args.concurrency:
                name = f"concurrent-{concurrency}-crops-{crops}"
                barrier = threading.Barrier(concurrency)

                def concurrent(
                    *,
                    page_count=concurrency,
                    crop_count=crops,
                    phase_name=name,
                    gate=barrier,
                ):
                    def run(index):
                        gate.wait(timeout=10)
                        return run_case(
                            sample,
                            reader,
                            args.output / phase_name / str(index),
                            crops=crop_count,
                        )

                    with ThreadPoolExecutor(max_workers=page_count) as pool:
                        return list(pool.map(run, range(page_count)))

                phase(name, concurrent)

        def sustained():
            rows = []
            deadline = time.monotonic() + args.sustained_seconds
            while time.monotonic() < deadline:
                rows.append(
                    run_case(sample, reader, args.output / "sustained" / str(len(rows)))
                )
            return rows

        if args.sustained_seconds:
            phase("sustained", sustained)
    finally:
        reader.close()
        stopped.set()
        monitor_thread.join(timeout=2)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        metrics = {
            "label": args.label,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "reader_fingerprint": reader.fingerprint,
            "peak_child_rss_mb": round(
                usage.ru_maxrss
                / (1024 * 1024 if platform.system() == "Darwin" else 1024),
                1,
            ),
            "child_cpu_seconds": round(usage.ru_utime + usage.ru_stime, 3),
            "peak_sampled_parent_rss_mb": round(
                max((s["parent"].get("VmRSS", 0) for s in samples), default=0) / 1024, 1
            ),
            "peak_sampled_worker_rss_mb": round(
                max((s["worker"].get("VmRSS", 0) for s in samples), default=0) / 1024, 1
            ),
            "cgroup_before": before,
            "cgroup_after": cgroup_snapshot(),
            "load_note": "Multi-crop phases repeat one known region; they are synthetic contention tests.",
        }
        for name, value in [
            ("results", results),
            ("samples", samples),
            ("metrics", metrics),
        ]:
            (args.output / f"{name}.json").write_text(
                json.dumps(value, indent=2) + "\n"
            )
        print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    main()
