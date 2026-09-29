#!/usr/bin/env python3
"""Certify the streamed OpenAI Sunburst route with two paid requests (~$0.10).

Makes one generation through the gateway handler and one two-reference edit
through LiteLLM's Router with the fields Draw sends, both medium 1024x1536.
Prints acceptance timing, SSE event types, usage, and priced cost, and saves
the images for visual review. Never writes pipeline artifacts. Run with the
gateway environment; the key comes from OPENAI_API_KEY or the repository .env:

    litellm/.venv/bin/python scripts/openai_sunburst_live_check.py --output-dir ~/sunburst-check

``--asset-sizes`` instead certifies the Style/Cast sizes (~$0.05): a one-reference
1024x1280 style proof, a 768x1024 portrait, and a 1344x768 location plate, each
with the controls Style/Cast wires carry (quality only).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import struct
import sys
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MANIFEST = json.dumps({"width": 1024, "height": 1536,
                       "controls": [["quality", "medium"], ["output_format", "png"], ["n", 1]]})
# Sunburst token rates per litellm_pricing_overrides.yaml.
RATES = {"text": 5e-6, "image": 8e-6, "output": 3e-5}


def _load_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    env = ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else ():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")


def _png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("output is not a PNG")
    return struct.unpack(">II", data[16:24])


def _solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _priced(usage: dict) -> float:
    details = usage.get("input_tokens_details") or {}
    return (details.get("text_tokens", 0) * RATES["text"] + details.get("image_tokens", 0) * RATES["image"]
            + usage.get("output_tokens", 0) * RATES["output"])


async def _run(output_dir: Path) -> None:
    import litellm
    import yaml
    from litellm.utils import custom_llm_setup
    from litellm_handlers import openai_image_stream as handler

    events: list[tuple[float, str | None]] = []
    started = [0.0]
    original = handler.iter_sse_events

    class Accepted(logging.Handler):
        """Time from submission to the event stream opening (acceptance)."""
        def emit(self, record: logging.LogRecord) -> None:
            if "accepted" in record.getMessage():
                events.append((round(time.monotonic() - started[0], 2), "stream_opened"))

    handler.logger.addHandler(Accepted())
    handler.logger.setLevel(logging.INFO)

    async def recorded(lines):
        async for event in original(lines):
            events.append((round(time.monotonic() - started[0], 2), event.get("type")))
            yield event

    handler.iter_sse_events = recorded

    def report(name: str, image_b64: str, usage: dict, request_id: str | None) -> None:
        data = base64.b64decode(image_b64)
        (output_dir / f"{name}.png").write_bytes(data)
        print(json.dumps({"call": name, "request_id": request_id, "size": _png_size(data),
                          "seconds": round(time.monotonic() - started[0], 1), "events": events,
                          "usage": usage, "priced_usd": round(_priced(usage), 5)}, default=str))

    started[0] = time.monotonic()
    events.clear()
    generated = await handler.openai_image_stream_llm._generate_async(
        model="openai-stream/gpt-image-2.5-sunburst", image=[], prompt=(
            "A single comic book page, three panels: a lighthouse keeper climbs a spiral stair, "
            "trims a lamp, and watches a ship pass in fog. Ink and flat colour, no text or balloons."),
        model_response=SimpleNamespace(_hidden_params={}), api_key=None,
        optional_params={"canary_wire_request": MANIFEST}, timeout=None)
    usage = generated.usage
    report("generation", generated.data[0].b64_json,
           {**vars(usage), "input_tokens_details": vars(usage.input_tokens_details)} if usage else {},
           generated.provider_request_id)

    litellm.drop_params = False
    litellm.custom_provider_map = [{"provider": "openai-stream", "custom_handler": handler.openai_image_stream_llm}]
    custom_llm_setup()
    route = next(item for item in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
                 if item["model_name"] == "image-sunburst-openai")
    router = litellm.Router(model_list=[route])
    first = io.BytesIO(base64.b64decode(generated.data[0].b64_json))
    first.name = "reference-1.png"
    swatch = io.BytesIO(_solid_png(512, 512, (40, 90, 160)))
    swatch.name = "reference-2.png"
    started[0] = time.monotonic()
    events.clear()
    edited = await router.aimage_edit(
        model="image-sunburst-openai", image=[first, swatch],
        prompt=("Redraw Reference 1 as the same comic page, keeping the lighthouse keeper's appearance, "
                "but colour the ship's hull using the blue of Reference 2. No text or balloons."),
        size="1024x1536", n=1, quality="medium", output_format="png", canary_wire_request=MANIFEST)
    body = json.loads(edited.model_dump_json())
    report("edit", body["data"][0]["b64_json"], body.get("usage") or {}, body.get("provider_request_id"))
    # The proxy's x-litellm-response-cost comes from here; it must stay unset.
    print(json.dumps({"gateway_response_cost": edited._hidden_params.get("response_cost")}))


# Style/Cast wires carry only the quality control; the handler adds size and streaming.
ASSET_CASES = (
    ("style_proof_1024x1280", 1024, 1280, True,
     "A comic style sample: a lighthouse keeper on a rocky coast, ink and flat colour, using the palette "
     "of Reference 1. No text or balloons."),
    ("portrait_768x1024", 768, 1024, False,
     "A full-body character reference of a lighthouse keeper in an oilskin coat, plain background, "
     "ink and flat colour. No text."),
    ("location_1344x768", 1344, 768, False,
     "A wide establishing shot of a lighthouse on a rocky coast at dusk, ink and flat colour. No text."),
)


async def _run_assets(output_dir: Path) -> None:
    import litellm
    import yaml
    from litellm.utils import custom_llm_setup
    from litellm_handlers import openai_image_stream as handler

    litellm.drop_params = False
    litellm.custom_provider_map = [{"provider": "openai-stream", "custom_handler": handler.openai_image_stream_llm}]
    custom_llm_setup()
    route = next(item for item in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
                 if item["model_name"] == "image-sunburst-openai")
    router = litellm.Router(model_list=[route])
    total = 0.0
    for name, width, height, with_reference, prompt in ASSET_CASES:
        manifest = json.dumps({"width": width, "height": height, "controls": [["quality", "medium"]]})
        started = time.monotonic()
        if with_reference:
            swatch = io.BytesIO(_solid_png(512, 512, (40, 90, 160)))
            swatch.name = "reference-0.png"
            response = await router.aimage_edit(
                model="image-sunburst-openai", image=[swatch], prompt=prompt,
                canary_wire_request=manifest, response_format="b64_json")
        else:
            response = await router.aimage_generation(
                model="image-sunburst-openai", prompt=prompt,
                canary_wire_request=manifest, response_format="b64_json")
        body = json.loads(response.model_dump_json())
        data = base64.b64decode(body["data"][0]["b64_json"])
        (output_dir / f"{name}.png").write_bytes(data)
        usage = body.get("usage") or {}
        priced = _priced(usage)
        total += priced
        print(json.dumps({"call": name, "requested": [width, height], "size": _png_size(data),
                          "seconds": round(time.monotonic() - started, 1), "usage": usage,
                          "priced_usd": round(priced, 5),
                          "gateway_response_cost": response._hidden_params.get("response_cost")}, default=str))
    print(json.dumps({"total_priced_usd": round(total, 5)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--asset-sizes", action="store_true", help="certify the Style/Cast sizes instead")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _load_key()
    asyncio.run(_run_assets(args.output_dir) if args.asset_sizes else _run(args.output_dir))


if __name__ == "__main__":
    main()
