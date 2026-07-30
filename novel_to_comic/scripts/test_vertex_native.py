"""Smoke-test Gemini image generation through native Vertex `google-genai`.

Example:
    uv run --with google-genai python novel_to_comic/scripts/test_vertex_native.py \
      --ref novel_to_comic/src/novel_to_comic/labs/fixtures/reference_images/char_anya.png \
      --ref novel_to_comic/src/novel_to_comic/labs/fixtures/reference_images/char_rurik.png \
      --ref novel_to_comic/src/novel_to_comic/labs/fixtures/reference_images/loc_tavern.png \
      --output /tmp/vertex-native.png
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
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


def _extract_image_bytes(response: types.GenerateContentResponse) -> tuple[bytes, str]:
    for candidate in response.candidates or []:
        content = candidate.content
        for part in content.parts if content and content.parts else []:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data, inline.mime_type or "image/png"
    raise RuntimeError(f"Vertex response did not contain image bytes: {response}")


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
    parser.add_argument("--output", type=Path, default=Path("/tmp/vertex-native.png"))
    parser.add_argument("--metadata-output", type=Path, default=None)
    parser.add_argument("--ref", dest="refs", action="append", type=Path, default=[])
    args = parser.parse_args()

    if args.credentials.exists():
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(args.credentials))
    project = args.project or _load_project_from_credentials(args.credentials)
    if not project:
        raise SystemExit("Set --project or VERTEXAI_PROJECT/GOOGLE_CLOUD_PROJECT.")

    contents: list[str | types.Part] = [args.prompt]
    contents.extend(_image_part(ref) for ref in args.refs if ref.exists())

    client = genai.Client(vertexai=True, project=project, location=args.location)
    started = time.perf_counter()
    response = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    image_bytes, mime = _extract_image_bytes(response)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image_bytes)
    metadata = {
        "model": args.model,
        "project": project,
        "location": args.location,
        "output": str(args.output),
        "bytes": len(image_bytes),
        "mime": mime,
        "latency_ms": latency_ms,
        "ref_count": len(args.refs),
        "usage": _usage_dict(response),
    }
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
