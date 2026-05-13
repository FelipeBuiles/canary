"""Smoke-test Seedream V4.5 Edit through the local LiteLLM proxy.

Example:
    uv run python novel_to_comic/scripts/test_seedream_litellm.py \
      --ref char_anya.png --ref char_rurik.png --ref loc_tavern.png \
      --output /tmp/seedream.png
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
from typing import Any

import httpx


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _decode_image(data: dict[str, Any]) -> bytes:
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"LiteLLM returned no image data: {data}")
    first = items[0]
    if first.get("b64_json"):
        return base64.b64decode(first["b64_json"])
    if first.get("url"):
        response = httpx.get(first["url"], timeout=60.0)
        response.raise_for_status()
        return response.content
    raise RuntimeError(f"LiteLLM image entry has no b64_json or url: {first}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"))
    parser.add_argument("--api-key", default=os.environ.get("LITELLM_API_KEY", "sk-local-canary"))
    parser.add_argument("--model", default="image-balanced-seedream-test")
    parser.add_argument("--prompt", default="A painterly comic panel with the referenced characters grounded in the referenced setting.")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--output", type=Path, default=Path("/tmp/seedream-litellm.png"))
    parser.add_argument("--ref", dest="refs", action="append", type=Path, required=True)
    args = parser.parse_args()

    files = []
    handles = []
    try:
        for ref in args.refs:
            handle = ref.open("rb")
            handles.append(handle)
            files.append(("image", (ref.name, handle, _mime_type(ref))))
        response = httpx.post(
            f"{args.base_url.rstrip('/')}/v1/images/edits",
            headers={"Authorization": f"Bearer {args.api_key}"},
            data={
                "model": args.model,
                "prompt": args.prompt,
                "size": args.size,
                "n": "1",
            },
            files=files,
            timeout=300.0,
        )
        response.raise_for_status()
        data = response.json()
        image_bytes = _decode_image(data)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(image_bytes)
        print(f"wrote {args.output} ({len(image_bytes)} bytes)")
        print(f"x-litellm-response-cost={response.headers.get('x-litellm-response-cost')}")
        print(f"model={data.get('model')}")
    finally:
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
