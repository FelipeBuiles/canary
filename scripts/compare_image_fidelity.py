#!/usr/bin/env python3
"""Build a provider-free, non-destructive image comparison with native-pixel crops.

No inference, denoising, scoring, network access or source writes. Optional Canary
request JSON is summarized as *declared* metadata, not validated execution proof.
Run --help for usage. Only the full-page navigation preview is resized.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import math
from pathlib import Path
from typing import Any
import warnings

from PIL import Image

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_TOTAL_PIXELS = 80_000_000
MAX_CASES = 8
MAX_REGIONS = 8


def named_value(value: str) -> tuple[str, str]:
    name, sep, item = value.partition("=")
    if not sep or not name.strip() or not item.strip():
        raise ValueError("Expected NAME=VALUE with a nonempty name and value")
    return name.strip(), item.strip()


def region_value(value: str) -> tuple[str, tuple[float, float, float, float]]:
    name, raw = named_value(value)
    numbers = tuple(float(part) for part in raw.split(","))
    if len(numbers) != 4 or not all(math.isfinite(n) for n in numbers):
        raise ValueError("A region requires four finite fractions: NAME=x,y,width,height")
    x, y, width, height = numbers
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise ValueError("Regions must have positive area and lie entirely within 0..1")
    return name, (x, y, width, height)


def read_bounded(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    # Bound the actual read, not only stat(), in case a file changes meanwhile.
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Input exceeds the {limit}-byte limit: {path.name}")
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_summary(path: Path) -> dict[str, Any]:
    """Read only; never execute, rehash into production, or change a request.

    Explicit parents distinguish a correction from reference-conditioned creation.
    /images/edits alone does NOT imply a serial editing chain. Prompt/source paths
    and arbitrary request metadata are deliberately excluded from the report.
    """
    raw = read_bounded(path, 2 * 1024 * 1024)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Request JSON must contain an object")
    references = value.get("references")
    if not isinstance(references, list) or any(not isinstance(r, dict) for r in references):
        raise ValueError("Request JSON requires a list of reference objects")
    if value.get("discriminator") == "canary.provider-wire/3":
        parents = value.get("edit_parent_indices")
        if not isinstance(parents, list) or any(
            type(i) is not int or not 0 <= i < len(references) for i in parents
        ):
            raise ValueError("Invalid declared edit_parent_indices")
        provider = value.get("provider_key")
        prompt = value.get("prompt_parts")
        if not isinstance(prompt, list) or any(not isinstance(p, str) for p in prompt):
            raise ValueError("Invalid declared prompt_parts")
        controls = value.get("controls")
        if not isinstance(controls, list) or any(
            not isinstance(p, list) or len(p) != 2 or not isinstance(p[0], str) for p in controls
        ):
            raise ValueError("Invalid declared controls")
        quality = dict(controls).get("quality")
        details = {
            "requested_alias": value.get("requested_alias"),
            "configured_model": value.get("configured_provider_model"),
            "requested_dimensions": [value.get("width"), value.get("height")],
            "declared_quality": quality,
            "declared_execution_fingerprint": value.get("execution_fingerprint"),
        }
        parent_count = len(parents)
        input_count = len(references)  # Parents are already selected references.
    elif value.get("artifact_kind") == "complete_page" and "profile_id" in value:
        correction = value.get("correction")
        if correction is not None and not isinstance(correction, dict):
            raise ValueError("Invalid declared correction")
        provider = value.get("provider")
        prompt = [value.get("prompt")]
        if not isinstance(prompt[0], str):
            raise ValueError("Invalid declared page prompt")
        parent_count = int(correction is not None)
        input_count = len(references) + parent_count
        details = {
            "configured_model": value.get("model"),
            "profile_id": value.get("profile_id"),
            "requested_dimensions": [value.get("output_width"), value.get("output_height")],
            "declared_request_sha256": value.get("request_sha256"),
            # The frozen page shape does not carry an independent quality knob.
            "declared_quality": None,
            "quality_note": "Read the locked profile and execution trace; not recorded here.",
            "parent_image_sha256": (correction or {}).get("parent_render_image_sha256"),
        }
    else:
        raise ValueError("Expected a Canary provider-wire/3 or frozen complete-page request")
    operation = ("edit" if parent_count else
                 "reference_conditioned_generation" if references else "generation")
    http_providers = {"openai", "openrouter", "vertex-multimodal", "fal-queue"}
    endpoint = (("/v1/images/edits" if input_count else "/v1/images/generations")
                if provider in http_providers else None)
    return {
        "evidence": "Declared request metadata only; not validated execution or image linkage",
        "file_sha256": sha256(raw),
        "provider": provider,
        "logical_operation": operation,
        "derived_canary_gateway_endpoint": endpoint,
        "reference_count": len(references),
        "explicit_parent_count": parent_count,
        "image_input_count": input_count,
        "reference_sha256": [r.get("content_sha256") for r in references],
        "prompt_sha256": sha256(json.dumps(prompt, ensure_ascii=False).encode("utf-8")),
        **details,
    }


def build_comparison(
    images: list[tuple[str, Path]],
    regions: list[tuple[str, tuple[float, float, float, float]]],
    output: Path,
    requests: dict[str, Path] | None = None,
) -> Path:
    """Write a NEW report directory. Original images/requests remain untouched."""
    if not 1 <= len(images) <= MAX_CASES or not 1 <= len(regions) <= MAX_REGIONS:
        raise ValueError(f"Use 1..{MAX_CASES} images and 1..{MAX_REGIONS} regions")
    labels = [label for label, _ in images]
    if len(set(labels)) != len(labels) or len({name for name, _ in regions}) != len(regions):
        raise ValueError("Image and region labels must be unique within their groups")
    requests = requests or {}
    if set(requests) - set(labels):
        raise ValueError("Every request label must match an image label")
    if output.exists():
        raise ValueError("Output directory already exists; choose a new directory")
    # Validate programmatic callers just as strictly as the CLI.
    for name, box in regions:
        region_value(name + "=" + ",".join(str(n) for n in box))

    prepared = []
    total_pixels = 0
    for label, path in images:
        raw = read_bounded(path)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in {"PNG", "JPEG", "WEBP"} or getattr(original, "n_frames", 1) != 1:
                    raise ValueError("Use a single-frame PNG, JPEG or WebP image")
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError(f"Input exceeds the {MAX_PIXELS}-pixel limit")
                if original.mode not in {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"}:
                    raise ValueError("Use a PNG-compatible color mode; convert CMYK explicitly first")
                total_pixels += original.width * original.height
                if total_pixels > MAX_TOTAL_PIXELS:
                    raise ValueError(f"Inputs exceed the {MAX_TOTAL_PIXELS}-pixel total limit")
                original.load()
                # No EXIF autorotation: coordinates and pixel dimensions must
                # agree with the saved provider raster. Note orientation below.
                metadata = {
                    "label": label, "source_name": path.name, "source_sha256": sha256(raw),
                    "format": original.format, "mode": original.mode,
                    "width": original.width, "height": original.height,
                    "exif_orientation": original.getexif().get(274),
                    "has_icc_profile": bool(original.info.get("icc_profile")),
                    "request": request_summary(requests[label]) if label in requests else None,
                }
                raster = original.copy()
                # Derived crops keep color/alpha, but no EXIF orientation or
                # private camera metadata that could rotate or leak into them.
                raster.info = {key: original.info[key] for key in ("icc_profile", "transparency")
                               if key in original.info}
                prepared.append((raster, metadata))

    # Exclusive creation is the no-overwrite boundary, after all inputs validate.
    output.mkdir(parents=True, exist_ok=False)
    cases, columns = [], []
    for index, (image, metadata) in enumerate(prepared):
        preview = image.copy()
        preview.thumbnail((480, 640), Image.Resampling.LANCZOS)
        preview_name = f"case-{index}-preview.png"
        preview.save(output / preview_name, format="PNG")
        crops, figures = [], []
        for region_index, (name, box) in enumerate(regions):
            x, y, width, height = box
            left, top = math.floor(x * image.width), math.floor(y * image.height)
            right = min(image.width, math.ceil((x + width) * image.width))
            bottom = min(image.height, math.ceil((y + height) * image.height))
            pixel_box = (left, top, right, bottom)
            crop = image.crop(pixel_box)
            crop_name = f"case-{index}-region-{region_index}.png"
            crop.save(output / crop_name, format="PNG")
            crops.append({"name": name, "normalized_xywh": box, "pixel_ltrb": pixel_box,
                          "file": crop_name, "resampled": False})
            figures.append(
                f'<h3>{html.escape(name)}</h3><p>{crop.width} × {crop.height} native pixels</p>'
                f'<div class="crop"><img src="{crop_name}" width="{crop.width}" '
                f'height="{crop.height}" alt="{html.escape(name, quote=True)}"></div>'
            )
        cases.append({**metadata, "preview": preview_name, "preview_resampled": True, "crops": crops})
        columns.append(
            f'<section><h2>{html.escape(metadata["label"])}</h2>'
            f'<p>{metadata["width"]} × {metadata["height"]} · {metadata["format"]}</p>'
            f'<p>Navigation preview only — resized, not quality evidence.</p>'
            f'<img class="preview" src="{preview_name}" alt="Full image preview">'
            + "".join(figures) + '</section>'
        )
    manifest = {"schema_version": 1, "automatic_quality_verdict": None,
                "notes": ["No model calls or source modifications.",
                          "Crops are unresampled; use browser zoom 100% and compare originals too.",
                          "ICC profiles are preserved when present; browser color management may differ.",
                          "Different scenes are not paired A/B evidence; align the intended regions manually."],
                "cases": cases}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'img-src \'self\'; style-src \'unsafe-inline\'">'
        '<title>Canary image fidelity comparison</title><style>'
        'body{font:16px system-ui;margin:24px}main{display:flex;gap:24px;align-items:flex-start}'
        'section{flex:0 0 480px;min-width:0}.preview{max-width:100%;height:auto}'
        '.crop{overflow:auto;max-width:480px}.crop img{max-width:none;display:block}'
        'h3{margin-bottom:4px}p{line-height:1.5}</style><h1>Image fidelity comparison</h1>'
        '<p>These are source crops, not repaired images. Native means one raster pixel per CSS '
        'pixel at 100% browser zoom, not necessarily one physical display pixel. '
        'Judge both native crops and final reading size. No automatic pass/fail score.</p>'
        '<p><a href="manifest.json">Request declarations, image hashes and crop coordinates</a></p>'
        '<main>' + ''.join(columns) + '</main></html>'
    )
    (output / "index.html").write_text(report, encoding="utf-8")
    return output / "index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--region", action="append", required=True, metavar="NAME=X,Y,W,H")
    parser.add_argument("--request", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--output", type=Path, required=True, help="New directory; never overwritten")
    args = parser.parse_args()
    try:
        images = [(name, Path(path)) for name, path in map(named_value, args.image)]
        request_pairs = [named_value(item) for item in args.request]
        if len({name for name, _ in request_pairs}) != len(request_pairs):
            raise ValueError("Request labels must be unique")
        report = build_comparison(images, [region_value(r) for r in args.region], args.output,
                                  {name: Path(path) for name, path in request_pairs})
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        parser.error(str(exc))
    print(report)


if __name__ == "__main__":
    main()
