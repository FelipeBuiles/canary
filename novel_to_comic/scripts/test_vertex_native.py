"""Smoke-test / bisect Gemini image generation through native Vertex `google-genai`.

Mirrors the request the vertex-multimodal handler builds, one knob at a time,
so an opaque gateway block can be attributed to the prompt, the reference
images, the response modalities, or the native image controls.

Baseline (trivial prompt, exactly what the handler sends today):
    uv run --with google-genai python novel_to_comic/scripts/test_vertex_native.py

Replay the exact frozen request a failing page recorded on disk:
    uv run --with google-genai python novel_to_comic/scripts/test_vertex_native.py \
      --request-json projects/<user>/<project>/draw/pages/page_002/request_001.json \
      --modalities TEXT,IMAGE

A block prints prompt_feedback/finish_reason and exits 2 instead of raising.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types


DEFAULT_PROMPT = (
    "Painterly comic panel. A young woman and a wary man stand inside the "
    "referenced tavern. Preserve the two referenced character identities, use "
    "the tavern as the setting, cinematic warm lamplight, no text or captions."
)

# Kept identical to litellm_handlers/vertex_multimodal.py so a probe run
# reproduces production rather than a friendlier variant of it.
_SAFETY_CATEGORIES = (
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_credentials_path() -> Path:
    return _repo_root() / "litellm" / "gcp-credentials.json"


def _load_project_from_credentials(path: Path) -> str:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return ""
    return str(data.get("project_id") or "").strip()


def _mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/png"


def _image_part(path: Path) -> types.Part:
    return types.Part.from_bytes(data=path.read_bytes(), mime_type=_mime_type(path))


def _image_size_for_dimensions(width: int, height: int) -> str:
    pixels = width * height
    tiers = {"1K": 1024 * 1024, "2K": 2048 * 2048, "4K": 4096 * 4096}
    return min(tiers, key=lambda tier: abs(tiers[tier] - pixels))


def _aspect_for_dimensions(width: int, height: int) -> str:
    supported = {
        "9:16": 9 / 16,
        "2:3": 2 / 3,
        "3:4": 3 / 4,
        "4:5": 4 / 5,
        "1:1": 1.0,
        "5:4": 5 / 4,
        "4:3": 4 / 3,
        "3:2": 3 / 2,
        "16:9": 16 / 9,
        "21:9": 21 / 9,
    }
    requested = width / height
    return min(supported, key=lambda key: abs(supported[key] - requested))


def _extract_image_bytes(
    response: types.GenerateContentResponse,
) -> tuple[bytes, str] | None:
    for candidate in response.candidates or []:
        content = candidate.content
        for part in content.parts if content and content.parts else []:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data, inline.mime_type or "image/png"
    return None


def _response_text(response: types.GenerateContentResponse) -> list[str]:
    texts: list[str] = []
    for candidate in response.candidates or []:
        content = candidate.content
        for part in content.parts if content and content.parts else []:
            text = getattr(part, "text", None)
            if text:
                texts.append(text)
    return texts


def _ratings(ratings: Any) -> list[str]:
    return [
        f"{getattr(rating, 'category', None)}"
        f"(prob={getattr(rating, 'probability', None)},"
        f" blocked={getattr(rating, 'blocked', None)})"
        for rating in ratings or []
    ]


def _report_block(response: types.GenerateContentResponse) -> dict[str, Any]:
    feedback = getattr(response, "prompt_feedback", None)
    return {
        "blocked": True,
        "model_version": getattr(response, "model_version", None),
        "prompt_feedback": {
            "block_reason": str(getattr(feedback, "block_reason", None) or ""),
            "block_reason_message": getattr(feedback, "block_reason_message", None),
            "safety_ratings": _ratings(getattr(feedback, "safety_ratings", None)),
        },
        "candidates": [
            {
                "finish_reason": str(getattr(candidate, "finish_reason", None) or ""),
                "finish_message": getattr(candidate, "finish_message", None),
                "safety_ratings": _ratings(getattr(candidate, "safety_ratings", None)),
            }
            for candidate in response.candidates or []
        ],
        "text_parts": _response_text(response),
    }


def _usage_dict(response: types.GenerateContentResponse) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return {}
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    return {
        "prompt_token_count": getattr(usage, "prompt_token_count", None),
        "candidates_token_count": getattr(usage, "candidates_token_count", None),
        "total_token_count": getattr(usage, "total_token_count", None),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemini-3-pro-image")
    parser.add_argument("--project", default=os.environ.get("VERTEXAI_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "")
    parser.add_argument("--location", default=os.environ.get("VERTEXAI_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION") or "global")
    parser.add_argument("--credentials", type=Path, default=Path(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or _default_credentials_path()))
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--prompt-file", type=Path, default=None, help="read the prompt verbatim from this file")
    parser.add_argument(
        "--request-json",
        type=Path,
        default=None,
        help="frozen draw request (draw/pages/page_XXX/request_NNN.json): replays its prompt and geometry",
    )
    parser.add_argument("--modalities", default="IMAGE", help="comma-separated response_modalities, e.g. TEXT,IMAGE")
    parser.add_argument("--image-size", default=None, choices=("1K", "2K", "4K"))
    parser.add_argument("--aspect-ratio", default=None, help="native aspect, e.g. 2:3")
    parser.add_argument(
        "--safety-off",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="send threshold=OFF safety settings like the handler does (default: on)",
    )
    parser.add_argument("--output", type=Path, default=Path("/tmp/vertex-native.png"))
    parser.add_argument("--metadata-output", type=Path, default=None)
    parser.add_argument("--ref", dest="refs", action="append", type=Path, default=[])
    args = parser.parse_args()

    prompt = args.prompt
    image_size = args.image_size
    aspect_ratio = args.aspect_ratio
    if args.request_json is not None:
        frozen = json.loads(args.request_json.read_text())
        prompt = frozen["prompt"]
        width = int(frozen.get("output_width") or 0)
        height = int(frozen.get("output_height") or 0)
        if width > 0 and height > 0:
            image_size = image_size or _image_size_for_dimensions(width, height)
            aspect_ratio = aspect_ratio or _aspect_for_dimensions(width, height)
    elif args.prompt_file is not None:
        prompt = args.prompt_file.read_text()

    if args.credentials.exists():
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(args.credentials))
    project = args.project or _load_project_from_credentials(args.credentials)
    if not project:
        raise SystemExit("Set --project or VERTEXAI_PROJECT/GOOGLE_CLOUD_PROJECT.")

    # References go before the prompt, matching the handler's contents order.
    contents: list[str | types.Part] = [_image_part(ref) for ref in args.refs if ref.exists()]
    contents.append(prompt)

    config_kwargs: dict[str, Any] = {
        "response_modalities": [part.strip() for part in args.modalities.split(",") if part.strip()],
    }
    if args.safety_off:
        config_kwargs["safety_settings"] = [
            types.SafetySetting(category=category, threshold="OFF")
            for category in _SAFETY_CATEGORIES
        ]
    image_config_kwargs = {
        key: value
        for key, value in (("image_size", image_size), ("aspect_ratio", aspect_ratio))
        if value is not None
    }
    if image_config_kwargs:
        config_kwargs["image_config"] = types.ImageConfig(**image_config_kwargs)

    client = genai.Client(vertexai=True, project=project, location=args.location)
    started = time.perf_counter()
    response = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    metadata: dict[str, Any] = {
        "model": args.model,
        "project": project,
        "location": args.location,
        "response_modalities": config_kwargs["response_modalities"],
        "safety_off": args.safety_off,
        "image_config": image_config_kwargs,
        "prompt_characters": len(prompt),
        "prompt_source": str(args.request_json or args.prompt_file or "inline"),
        "ref_count": len(args.refs),
        "latency_ms": latency_ms,
        "usage": _usage_dict(response),
    }

    extracted = _extract_image_bytes(response)
    if extracted is None:
        metadata.update(_report_block(response))
        print(json.dumps(metadata, indent=2))
        if args.metadata_output:
            args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
            args.metadata_output.write_text(json.dumps(metadata, indent=2) + "\n")
        sys.exit(2)

    image_bytes, mime = extracted
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image_bytes)
    metadata.update({
        "blocked": False,
        "output": str(args.output),
        "bytes": len(image_bytes),
        "mime": mime,
        "text_parts": _response_text(response),
    })
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
