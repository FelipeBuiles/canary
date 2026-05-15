"""Run the Phase 3 Labs comparison on the built-in fixture.

This bypasses the FastAPI router and calls the Labs providers directly so the
same experiment can run from a shell.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from novel_to_comic.labs.fixtures import reference_image_paths
from novel_to_comic.labs.providers.base import LabsImageInput
from novel_to_comic.labs.providers.fal import FalProvider
from novel_to_comic.labs.providers.litellm import LitellmProvider
from novel_to_comic.labs.registry import get_entry, load_registry


DEFAULT_MODELS = ["gemini-3-flash-vertex-native-proxy", "gemini-3-pro-vertex-native-proxy", "nano-banana-2-edit"]
DEFAULT_PROMPT = (
    "Painterly comic panel. A young woman and a wary man stand inside the "
    "referenced tavern. Preserve the two referenced character identities, use "
    "the tavern as the setting, cinematic warm lamplight, no text or captions."
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _provider(name: str) -> Any:
    if name == "fal":
        return FalProvider()
    if name == "litellm":
        return LitellmProvider()
    raise ValueError(f"Unsupported Labs provider in this script: {name}")


async def _run_one(model_id: str, prompt: str, output_dir: Path) -> dict[str, Any]:
    entry = get_entry(model_id)
    inp = LabsImageInput(
        prompt=prompt,
        width=1024,
        height=1024,
        reference_image_paths=reference_image_paths(),
    )
    started = time.perf_counter()
    result = await _provider(entry.provider).generate(endpoint=entry.endpoint, inp=inp, params=entry.params)
    latency_ms = int((time.perf_counter() - started) * 1000)
    suffix = ".png" if result.mime == "image/png" else ".jpg"
    image_path = output_dir / f"{model_id}{suffix}"
    image_path.write_bytes(result.image_bytes)
    return {
        "model_id": model_id,
        "label": entry.label,
        "provider": entry.provider,
        "endpoint": entry.endpoint,
        "output": str(image_path),
        "bytes": len(result.image_bytes),
        "mime": result.mime,
        "latency_ms": latency_ms,
        "provider_model": result.provider_model,
        "provider_request_id": result.provider_request_id,
        "cost_usd": result.cost_usd,
        "cost_source": result.cost_source,
    }


async def _main_async(args: argparse.Namespace) -> None:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for model_id in args.model:
        rows.append(await _run_one(model_id, args.prompt, output_dir))
    manifest = {
        "prompt": args.prompt,
        "reference_images": [str(p) for p in reference_image_paths()],
        "results": rows,
    }
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def main() -> None:
    load_dotenv(_repo_root() / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--output-dir", type=Path, default=Path("/private/tmp/canary-phase3/labs"))
    parser.add_argument("--manifest", type=Path, default=Path("/private/tmp/canary-phase3/labs/manifest.json"))
    parser.add_argument("--model", action="append", choices=[entry.id for entry in load_registry()], default=None)
    args = parser.parse_args()
    if args.model is None:
        args.model = DEFAULT_MODELS
    os.environ.setdefault("LITELLM_BASE_URL", "http://localhost:4000")
    os.environ.setdefault("LITELLM_API_KEY", "sk-local-canary")
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
