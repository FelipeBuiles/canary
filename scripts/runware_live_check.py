#!/usr/bin/env python3
"""Runware Phase 0 paid probe (~$0.25 Runware + ~$0.05 OpenAI).

Replays one real Draw page (prompt + five Cast references) at production
settings and records what the provider-free probes could not:

1. Sunburst via Runware, sync, references by media-storage UUID: latency,
   reported ``cost``, response fields, PNG integrity.
2. ``getTaskDetails`` for that completed sync task (recovery path).
3. Sunburst via Runware, async, recovered only through ``getTaskDetails``
   polling (``getResponse`` answers "processing" for unknown UUIDs).
4. The same page direct on OpenAI with our streamed fields, for the baseline
   latency, time to first preview, and returned usage tokens.
5. Nano Banana 2.1 via Runware at 2K 2:3 (Vertex "medium").

Each paid request is submitted exactly once; nothing retries. Keys come from
the repository .env. Outputs land in --output-dir for visual review:

    litellm/.venv/bin/python scripts/runware_live_check.py --output-dir ~/runware-check
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.runware.ai/v1"
PROJECT = ROOT / "projects/947150d4-7d2f-4726-a018-5539f933ea56/elm-and-keep"
PAGE_REQUEST = PROJECT / "parts/part_0001/draw/pages/page_021/request_001.json"
REFERENCES = ("refs/char_001/sheet.png", "refs/char_002/sheet.png", "refs/props/prop_002/ref.png",
              "plates/loc_004.png", "samples/style_1.png")
SUNBURST = "openai:gpt-image@2.5-sunburst"
NANO_BANANA = "google:nano-banana@2.1"
# Sunburst token rates per litellm_pricing_overrides.yaml.
RATES = {"text": 5e-6, "image": 8e-6, "output": 3e-5}


def _env(name: str) -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit(f"{name} missing from .env")


def _png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("output is not a PNG")
    return struct.unpack(">II", data[16:24])


class Runware:
    def __init__(self, key: str) -> None:
        self._client = httpx.Client(headers={"Authorization": f"Bearer {key}"},
                                    timeout=httpx.Timeout(300, connect=10))

    def call(self, task: dict) -> tuple[int, dict, float]:
        started = time.monotonic()
        response = self._client.post(API, json=[task])
        return response.status_code, response.json(), time.monotonic() - started


def _redacted(body: dict) -> str:
    """Response JSON with base64 image payloads shortened."""
    def shrink(value):
        if isinstance(value, dict):
            return {k: (f"<{len(v)} chars>" if k in {"imageBase64Data", "imageDataURI"} else shrink(v))
                    for k, v in value.items()}
        if isinstance(value, list):
            return [shrink(v) for v in value]
        return value
    return json.dumps(shrink(body))[:1200]


def _save(result: dict, path: Path) -> None:
    data = base64.b64decode(result["imageBase64Data"])
    path.write_bytes(data)
    print(f"    saved {path.name} {_png_size(data)} {len(data) / 1e6:.2f} MB")


def _upload_references(rw: Runware) -> list[str]:
    ids = []
    for name in REFERENCES:
        uri = "data:image/png;base64," + base64.b64encode((PROJECT / name).read_bytes()).decode()
        status, body, elapsed = rw.call({"taskType": "mediaStorage", "taskUUID": str(uuid.uuid4()),
                                         "operation": "upload", "media": uri})
        if status != 200:
            raise SystemExit(f"upload {name} failed: {status} {_redacted(body)}")
        ids.append(body["data"][0]["mediaUUID"])
        print(f"  upload {name}: {elapsed:.1f}s")
    return ids


def _sunburst_task(prompt: str, refs: list[str], delivery: str) -> dict:
    return {"taskType": "imageInference", "taskUUID": str(uuid.uuid4()), "model": SUNBURST,
            "positivePrompt": prompt, "width": 1024, "height": 1536,
            "inputs": {"referenceImages": refs},
            "settings": {"quality": "medium", "moderation": "low"},
            "outputType": "base64Data", "outputFormat": "PNG", "includeCost": True,
            "deliveryMethod": delivery}


def _details(rw: Runware, task_uuid: str) -> tuple[str, dict]:
    status, body, _ = rw.call({"taskType": "getTaskDetails", "taskUUID": task_uuid})
    if status != 200:
        codes = [e.get("code") for e in body.get("errors", [])]
        return ("not_found" if "taskNotFound" in codes else f"lookup_error {codes}"), body
    response = body["data"][0].get("response") or {}
    if response.get("errors"):
        return "failed", response
    return ("completed" if response.get("data") else "pending"), response


def run_sync(rw: Runware, prompt: str, refs: list[str], out: Path) -> None:
    print("\n[1] Sunburst via Runware, sync, references by UUID")
    task = _sunburst_task(prompt, refs, "sync")
    status, body, elapsed = rw.call(task)
    print(f"  status={status} latency={elapsed:.1f}s")
    print(f"  response={_redacted(body)}")
    if status == 200:
        _save(body["data"][0], out / "runware_sunburst_sync.png")
    print("\n[2] getTaskDetails for the completed sync task")
    for delay in (0, 10):
        time.sleep(delay)
        state, response = _details(rw, task["taskUUID"])
        print(f"  after {delay}s: {state} {_redacted(response)[:500]}")


def run_async(rw: Runware, prompt: str, refs: list[str], out: Path) -> None:
    print("\n[3] Sunburst via Runware, async, recovered through getTaskDetails")
    task = _sunburst_task(prompt, refs, "async")
    started = time.monotonic()
    status, body, elapsed = rw.call(task)
    print(f"  ack status={status} in {elapsed:.1f}s {_redacted(body)[:300]}")
    if status >= 400:
        return
    delay = 2.0
    while time.monotonic() - started < 300:
        time.sleep(delay)
        state, response = _details(rw, task["taskUUID"])
        if state in {"completed", "failed"}:
            print(f"  {state} after {time.monotonic() - started:.1f}s {_redacted(response)[:500]}")
            if state == "completed":
                # getTaskDetails returns a placeholder instead of the base64 payload; the
                # image is served at a public URL keyed by imageUUID.
                image_uuid = response["data"][0]["imageUUID"]
                data = httpx.get(f"https://im.runware.ai/image/ii/{image_uuid}.png", timeout=60).content
                (out / "runware_sunburst_async.png").write_bytes(data)
                print(f"    saved runware_sunburst_async.png {_png_size(data)} {len(data) / 1e6:.2f} MB")
            return
        delay = min(delay * 1.5, 5.0)
    print("  no terminal state within 300s")


def run_openai(prompt: str, out: Path) -> None:
    print("\n[4] Sunburst direct on OpenAI (production streamed fields, partial_images=3)")
    data = {"model": "gpt-image-2.5-sunburst", "prompt": prompt, "size": "1024x1536", "stream": "true",
            "partial_images": "3", "moderation": "low", "quality": "medium", "output_format": "png", "n": "1"}
    files = [("image[]", (Path(n).name, (PROJECT / n).read_bytes(), "image/png")) for n in REFERENCES]
    started, first = time.monotonic(), None
    with httpx.Client(timeout=httpx.Timeout(300, connect=10)) as client, client.stream(
            "POST", "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {_env('OPENAI_API_KEY')}"}, data=data, files=files) as response:
        if response.status_code >= 400:
            print(f"  status={response.status_code} {response.read()[:300]!r}")
            return
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event, elapsed = json.loads(line[5:].strip()), time.monotonic() - started
            if "partial" in event.get("type", ""):
                first = first or elapsed
                print(f"  preview {event.get('partial_image_index')} at {elapsed:.1f}s")
            elif "completed" in event.get("type", ""):
                usage = event.get("usage") or {}
                details = usage.get("input_tokens_details") or {}
                cost = (details.get("text_tokens", 0) * RATES["text"] + details.get("image_tokens", 0) * RATES["image"]
                        + usage.get("output_tokens", 0) * RATES["output"])
                print(f"  completed at {elapsed:.1f}s usage={json.dumps(usage)} priced=${cost:.4f}")
                data_png = base64.b64decode(event["b64_json"])
                (out / "openai_sunburst_direct.png").write_bytes(data_png)
                print(f"    saved openai_sunburst_direct.png {_png_size(data_png)}")
    print(f"  first preview {first and round(first, 1)}s")


def run_nano_banana(rw: Runware, prompt: str, refs: list[str], out: Path) -> None:
    print("\n[5] Nano Banana 2.1 via Runware, 2K 2:3")
    task = {"taskType": "imageInference", "taskUUID": str(uuid.uuid4()), "model": NANO_BANANA,
            "positivePrompt": prompt, "width": 1696, "height": 2528,
            "inputs": {"referenceImages": refs}, "settings": {"safetyTolerance": "none"},
            "outputType": "base64Data", "outputFormat": "PNG", "includeCost": True, "deliveryMethod": "sync"}
    status, body, elapsed = rw.call(task)
    print(f"  status={status} latency={elapsed:.1f}s response={_redacted(body)}")
    if status == 200:
        _save(body["data"][0], out / "runware_nano_banana.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="Runware Phase 0 paid probe")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skip", nargs="*", default=[], choices=["sync", "async", "openai", "nano"])
    args = parser.parse_args()
    args.output_dir.expanduser().mkdir(parents=True, exist_ok=True)
    out = args.output_dir.expanduser()
    prompt = json.loads(PAGE_REQUEST.read_text())["prompt"]
    rw = Runware(_env("RUNWARE_API_KEY"))
    status, body, _ = rw.call({"taskType": "accountManagement", "taskUUID": str(uuid.uuid4()), "operation": "getDetails"})
    print("balance", body["data"][0]["balance"] if status == 200 else _redacted(body))
    print("uploading references")
    refs = _upload_references(rw)
    if "sync" not in args.skip:
        run_sync(rw, prompt, refs, out)
    if "async" not in args.skip:
        run_async(rw, prompt, refs, out)
    if "openai" not in args.skip:
        run_openai(prompt, out)
    if "nano" not in args.skip:
        run_nano_banana(rw, prompt, refs, out)


if __name__ == "__main__":
    sys.exit(main())
