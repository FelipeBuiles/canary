"""Post-draw visual consistency evaluator.

Calls a multimodal LLM via the LiteLLM gateway to score each panel on:
  - identity_match: how well the rendered character matches the cast plate
  - location_continuity: how well the panel coheres with the prior panel's setting
  - forbidden_text_present: whether unintended on-panel lettering leaked through

Designed to be invoked standalone (CLI script, API endpoint, or notebook).
It is intentionally NOT registered as a pipeline stage so cost is opt-in.

Talks to the LiteLLM gateway directly via httpx so the existing
text-only ai client stays simple. Default model is the cheapest vision-
capable gateway alias; override via `model` argument.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from novel_to_comic.config import Config

logger = logging.getLogger(__name__)

_DEFAULT_VLM_MODEL = "gemini-2.5-flash-lite"

_SYSTEM_PROMPT = """You are a comic-book consistency reviewer.

You will be shown one PANEL image and up to two reference images: a CAST reference plate (the canonical look of a character) and an optional PRIOR PANEL (the panel that visually precedes this one in the story).

Score the PANEL on three dimensions:

1. identity_match — How well does the character in PANEL match the CAST reference?
   1.0 = same person, same wardrobe, same identifying features
   0.5 = recognizable but visibly drifted (different hair, off proportions, wrong outfit details)
   0.0 = looks like a different character
   Return null if no CAST reference was provided.

2. location_continuity — Is the setting consistent with the PRIOR PANEL?
   1.0 = clearly the same place / a natural cut within the same place
   0.5 = related setting but objects/architecture inconsistent
   0.0 = a totally different place when continuity was expected
   Return null if no PRIOR PANEL was provided.

3. forbidden_text_present — Is there ANY readable lettering, captions, speech bubbles, signage, watermark, subtitle, or alphabetic text rendered inside the panel image? Background text on real-world signs (a stop sign, store sign) does count as forbidden — text belongs in the lettering pass.
   true = yes, readable letters are visible somewhere in the image
   false = no readable letters

Also produce a one-sentence `notes` field summarising the most important issue (or "ok" if none).

Output STRICT JSON only, matching:
{
  "identity_match": float | null,
  "location_continuity": float | null,
  "forbidden_text_present": boolean,
  "notes": string
}"""


class PanelEvalResult(BaseModel):
    panel_path: str
    identity_match: Optional[float] = None
    location_continuity: Optional[float] = None
    forbidden_text_present: bool = False
    notes: str = ""
    model: str = _DEFAULT_VLM_MODEL
    raw_response: Optional[str] = Field(default=None, repr=False)


def _b64_image(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def _call_gateway(
    config: Config,
    model: str,
    panel_b64: str,
    cast_b64: Optional[str],
    prev_b64: Optional[str],
    timeout: float,
) -> str:
    base_url = config.litellm_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {config.litellm_api_key}",
        "Content-Type": "application/json",
    }
    user_parts: list[dict] = [{"type": "text", "text": "PANEL:"}]
    user_parts.append({"type": "image_url", "image_url": {"url": panel_b64}})
    if cast_b64:
        user_parts.append({"type": "text", "text": "CAST reference:"})
        user_parts.append({"type": "image_url", "image_url": {"url": cast_b64}})
    if prev_b64:
        user_parts.append({"type": "text", "text": "PRIOR PANEL:"})
        user_parts.append({"type": "image_url", "image_url": {"url": prev_b64}})

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_parts},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _parse_response(panel_path: Path, raw: str, model: str) -> PanelEvalResult:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:-1]).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("VLM eval: response not parseable as JSON for %s", panel_path)
        return PanelEvalResult(
            panel_path=str(panel_path),
            notes="VLM response was not valid JSON",
            model=model,
            raw_response=raw,
        )
    return PanelEvalResult(
        panel_path=str(panel_path),
        identity_match=obj.get("identity_match"),
        location_continuity=obj.get("location_continuity"),
        forbidden_text_present=bool(obj.get("forbidden_text_present", False)),
        notes=str(obj.get("notes", ""))[:300],
        model=model,
        raw_response=raw,
    )


async def evaluate_panel(
    *,
    panel_path: Path,
    cast_ref_path: Optional[Path] = None,
    prev_panel_path: Optional[Path] = None,
    config: Config,
    model: str = _DEFAULT_VLM_MODEL,
    timeout: float = 60.0,
) -> PanelEvalResult:
    """Score one panel on identity, continuity, and forbidden text."""
    if not panel_path.exists():
        return PanelEvalResult(
            panel_path=str(panel_path),
            notes=f"panel image missing: {panel_path}",
            model=model,
        )
    panel_b64 = _b64_image(panel_path)
    cast_b64 = _b64_image(cast_ref_path) if cast_ref_path and cast_ref_path.exists() else None
    prev_b64 = _b64_image(prev_panel_path) if prev_panel_path and prev_panel_path.exists() else None

    try:
        raw = await _call_gateway(config, model, panel_b64, cast_b64, prev_b64, timeout)
    except (httpx.HTTPError, KeyError) as exc:
        logger.warning("VLM eval: gateway call failed for %s: %s", panel_path, exc)
        return PanelEvalResult(
            panel_path=str(panel_path),
            notes=f"gateway error: {exc!s}"[:300],
            model=model,
        )
    return _parse_response(panel_path, raw, model)


async def evaluate_scene(
    *,
    project_dir: Path,
    scene_id: str,
    primary_character_id: Optional[str] = None,
    config: Config,
    model: str = _DEFAULT_VLM_MODEL,
    concurrency: int = 4,
) -> list[PanelEvalResult]:
    """Evaluate every drawn panel for one scene.

    Uses the first available reference view of `primary_character_id` (or the
    project's first character) as the CAST plate for identity scoring. Adjacent
    panels are paired so each panel except the first gets a PRIOR PANEL.

    Writes one JSON file per panel under `eval/{scene_id}/panel_NNN.json` and
    returns the in-memory results list.
    """
    draw_dir = project_dir / "draw" / scene_id
    if not draw_dir.is_dir():
        return []
    panels = sorted(draw_dir.glob("panel_*.png"))
    if not panels:
        return []

    # Pick a CAST plate for identity scoring.
    cast_ref: Optional[Path] = None
    refs_dir = project_dir / "refs"
    if primary_character_id:
        candidates = refs_dir / primary_character_id
        for view in ("front.png", "three_quarter.png", "sheet.png"):
            if (candidates / view).exists():
                cast_ref = candidates / view
                break
    if cast_ref is None and refs_dir.is_dir():
        for char_dir in sorted(refs_dir.iterdir()):
            if not char_dir.is_dir():
                continue
            for view in ("front.png", "three_quarter.png", "sheet.png"):
                if (char_dir / view).exists():
                    cast_ref = char_dir / view
                    break
            if cast_ref:
                break

    out_dir = project_dir / "eval" / scene_id
    out_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(concurrency)

    async def _one(idx: int, panel_path: Path) -> PanelEvalResult:
        async with semaphore:
            prev = panels[idx - 1] if idx > 0 else None
            result = await evaluate_panel(
                panel_path=panel_path,
                cast_ref_path=cast_ref,
                prev_panel_path=prev,
                config=config,
                model=model,
            )
            out_path = out_dir / f"{panel_path.stem}.json"
            out_path.write_text(result.model_dump_json(indent=2))
            return result

    results = await asyncio.gather(*[_one(i, p) for i, p in enumerate(panels)])
    return list(results)
