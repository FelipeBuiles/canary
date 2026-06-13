"""Project-level lettering & page styling — the single source of truth for how an
assembled comic page is themed (colors, borders, fonts, decorative vars).

Resolution order at render time, lowest -> highest precedence:
  BASE_VARS -> THEMES[theme] -> FONT_PAIRS[font_pair] -> vars -> per-bubble overrides
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LetteringStyle(BaseModel):
    # User intent. "auto" re-matches when the art style changes; "preset" is pinned.
    mode: str = "auto"
    preset: str | None = None
    # Resolved base anchor (one of the THEMES keys).
    theme: str = "default"
    # Curated font-pair id (one of FONT_PAIRS keys).
    font_pair: str = "golden-age"
    # Sanitized CSS-var overrides layered on top of theme + font pair.
    vars: dict[str, str] = Field(default_factory=dict)
    label: str = ""
    rationale: str = ""
    # Provenance: "ai" | "fallback" | "preset".
    source: str = "fallback"
    # Staleness key for auto mode — hash of the style template it was built from.
    style_template_hash: str = ""
    generated_at: str = ""
