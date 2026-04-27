"""Update pricing.yaml with verified prices from the OpenRouter models API.

OpenRouter publishes live per-token pricing for every model it carries, including
direct Anthropic, Google, and OpenAI models.  Prices are in USD per token; we
convert to USD per 1M tokens to match our yaml format.

Usage:
    python update_pricing.py            # dry-run, show diff only
    python update_pricing.py --apply    # write changes to pricing.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx
import yaml

PRICING_YAML = Path(__file__).parent / "src/novel_to_comic/pricing.yaml"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Map our model IDs to OpenRouter's {provider}/{model} IDs.
# OpenRouter uses the provider-prefixed form; we use the bare model ID internally.
OPENROUTER_ID_MAP: dict[str, str] = {
    # Google Gemini
    "gemini-3.1-pro-preview":       "google/gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite-preview": "google/gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro":               "google/gemini-2.5-pro",
    "gemini-2.5-flash":             "google/gemini-2.5-flash",
    "gemini-2.5-flash-lite":        "google/gemini-2.5-flash-lite",
    # Anthropic Claude (OpenRouter uses dots: claude-opus-4.6 vs our claude-opus-4-6)
    "claude-opus-4-6":              "anthropic/claude-opus-4.6",
    "claude-sonnet-4-6":            "anthropic/claude-sonnet-4.6",
    # OpenAI
    "gpt-5.4":                      "openai/gpt-5.4",
    "gpt-5.4-mini":                 "openai/gpt-5.4-mini",
}

# Image model prices are not exposed via the OpenRouter API (they're per-image or
# token-billed via separate provider endpoints).  Hardcode verified values here;
# update manually from the source URLs in pricing.yaml.
#
# Set to None to leave the existing yaml value unchanged.
IMAGE_MODEL_OVERRIDES: dict[str, dict] = {
    # sources: ai.google.dev/pricing (Gemini image generation)
    "gemini-3-pro-image-preview":    {"per_image_usd": 0.04},
    "gemini-3.1-flash-image-preview": {"per_image_usd": 0.02},
    # sources: openai.com/api/pricing
    "gpt-image-2":  {"input_per_m": 5.00, "output_per_m": 40.00, "per_image_usd": 0.04},
    "dall-e-3":     {"per_image_usd": 0.04},
    # sources: together.ai/pricing
    "black-forest-labs/FLUX.1-pro":          {"per_image_usd": 0.055},
    "black-forest-labs/FLUX.1-kontext-pro":  {"per_image_usd": 0.055},
    "black-forest-labs/FLUX.2-kontext-pro":  {"per_image_usd": 0.075},
    "black-forest-labs/FLUX.1-dev":          {"per_image_usd": 0.025},
    "black-forest-labs/FLUX.1-schnell":      {"per_image_usd": 0.006},
}


def fetch_openrouter_prices() -> dict[str, dict[str, float]]:
    """Return {openrouter_model_id: {input_per_m, output_per_m}} for all OR models."""
    resp = httpx.get(OPENROUTER_MODELS_URL, timeout=15)
    resp.raise_for_status()
    models = resp.json().get("data", [])
    result: dict[str, dict[str, float]] = {}
    for m in models:
        mid = m.get("id", "")
        pricing = m.get("pricing") or {}
        try:
            prompt = float(pricing.get("prompt") or 0)
            completion = float(pricing.get("completion") or 0)
        except (TypeError, ValueError):
            continue
        result[mid] = {
            "input_per_m": round(prompt * 1_000_000, 6),
            "output_per_m": round(completion * 1_000_000, 6),
        }
    return result


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def _patch_field(raw: str, model_id: str, field: str, new_val: float) -> str:
    """Replace a single price field value for model_id in the raw YAML string.

    Preserves all comments and surrounding formatting — only touches the
    numeric value on the matching field line within the model's block.
    """
    model_re = re.escape(model_id) + r":"
    model_match = re.search(r"^\s+" + model_re, raw, re.MULTILINE)
    if not model_match:
        return raw
    block_start = model_match.end()
    # The model block ends at the next 2-space-indented key (sibling model or section comment)
    next_sibling = re.search(r"\n  \S", raw[block_start:])
    block_end = block_start + next_sibling.start() if next_sibling else len(raw)
    block = raw[block_start:block_end]
    patched = re.sub(
        re.escape(field) + r":\s*[\d.]+",
        f"{field}: {_fmt(new_val)}",
        block,
    )
    return raw[:block_start] + patched + raw[block_end:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes to pricing.yaml")
    args = parser.parse_args()

    print("Fetching OpenRouter model prices …")
    try:
        or_prices = fetch_openrouter_prices()
    except Exception as exc:
        print(f"ERROR fetching OpenRouter API: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(or_prices)} models returned\n")

    with PRICING_YAML.open() as f:
        raw = f.read()
    data = yaml.safe_load(raw)
    models: dict[str, dict] = data.get("models") or {}

    changes: list[str] = []
    not_found: list[str] = []

    for our_id, spec in models.items():
        # ── image-only models ────────────────────────────────────────────────
        if our_id in IMAGE_MODEL_OVERRIDES:
            override = IMAGE_MODEL_OVERRIDES[our_id]
            diffs = []
            for key, new_val in override.items():
                old_val = spec.get(key, 0.0)
                if abs(old_val - new_val) > 1e-9:
                    diffs.append(f"  {key}: {_fmt(old_val)} → {_fmt(new_val)}")
                    spec[key] = new_val
            if diffs:
                changes.append(f"{our_id}:\n" + "\n".join(diffs))
            continue

        # ── text models via OpenRouter ───────────────────────────────────────
        or_id = OPENROUTER_ID_MAP.get(our_id)
        if or_id is None:
            not_found.append(f"{our_id}  (no OpenRouter mapping defined)")
            continue

        prices = or_prices.get(or_id)
        if prices is None:
            not_found.append(f"{our_id}  → {or_id}  (NOT found in OpenRouter response)")
            continue

        diffs = []
        for key in ("input_per_m", "output_per_m"):
            old_val = float(spec.get(key, 0.0))
            new_val = prices[key]
            if abs(old_val - new_val) > 1e-9:
                diffs.append(f"  {key}: {_fmt(old_val)} → {_fmt(new_val)}")
                spec[key] = new_val
        if diffs:
            changes.append(f"{our_id}  (OpenRouter: {or_id}):\n" + "\n".join(diffs))

    # ── report ───────────────────────────────────────────────────────────────
    if changes:
        print("CHANGES DETECTED:")
        for c in changes:
            print(f"  {c}")
        print()
    else:
        print("All prices match — no changes needed.\n")

    if not_found:
        print("COULD NOT VERIFY (model not found in OpenRouter):")
        for nf in not_found:
            print(f"  ✗ {nf}")
        print()

    if not changes:
        return

    if not args.apply:
        print("Dry run — pass --apply to write changes to pricing.yaml.")
        return

    # ── patch in-place to preserve comments and formatting ───────────────────
    raw = PRICING_YAML.read_text()
    for model_id, spec in models.items():
        for field in ("input_per_m", "output_per_m", "per_image_usd"):
            if field in spec:
                raw = _patch_field(raw, model_id, field, spec[field])
    PRICING_YAML.write_text(raw)
    print(f"pricing.yaml updated ({len(changes)} change(s) applied).")


if __name__ == "__main__":
    main()
