/** Theme CSS variable maps — ported from Python html_renderer.py _BASE_VARS + THEMES */

export type ThemeName = "default" | "noir" | "manga" | "vintage" | "painted";

export const THEME_NAMES: ThemeName[] = ["default", "noir", "manga", "vintage", "painted"];

export const BASE_VARS: Record<string, string> = {
  "--page-bg":              "#FFFFFF",
  "--gutter":               "16px",
  "--margin":               "30px",
  "--panel-border":         "#111111",
  "--panel-border-width":   "3px",
  "--panel-bg":             "#888888",
  "--caption-bg":           "#F7F0DC",
  "--caption-border":       "#9B8A5A",
  "--caption-color":        "#3A2A10",
  "--caption-font-size":    "26px",
  "--bubble-bg":            "#FFFFFF",
  "--bubble-border":        "#1A1A1A",
  "--bubble-border-width":  "2px",
  "--bubble-radius":        "14px",
  "--bubble-font-size":     "32px",
  "--bubble-padding":       "7px 11px",
  "--bubble-max-width":     "52%",
  "--bubble-center-width":  "68%",
  "--speaker-color":        "#664400",
  "--speaker-font-size":    "9px",
  "--thought-border-style": "dashed",
  "--thought-radius":       "50px",
  "--sfx-color":            "#CC1111",
  "--sfx-shadow":           "#000000",
  "--sfx-font-size":        "37px",
  "--page-num-color":       "#AAAAAA",
  "--page-num-font-size":   "17px",
};

export const THEMES: Record<string, Record<string, string>> = {
  default: {},
  noir: {
    "--page-bg":              "#1C1C1C",
    "--panel-border":         "#DDDDDD",
    "--panel-border-width":   "2px",
    "--panel-bg":             "#444444",
    "--caption-bg":           "#2A2A2A",
    "--caption-border":       "#666666",
    "--caption-color":        "#DDDDDD",
    "--bubble-bg":            "#F0F0F0",
    "--bubble-border":        "#111111",
    "--speaker-color":        "#444444",
    "--sfx-color":            "#FFFFFF",
    "--sfx-shadow":           "#000000",
    "--page-num-color":       "#555555",
  },
  manga: {
    "--panel-border-width":   "2px",
    "--panel-border":         "#000000",
    "--caption-bg":           "#FFFFFF",
    "--caption-border":       "#000000",
    "--caption-color":        "#000000",
    "--bubble-border":        "#000000",
    "--bubble-font-size":     "33px",
    "--sfx-color":            "#000000",
    "--sfx-shadow":           "transparent",
    "--thought-border-style": "solid",
  },
  vintage: {
    "--page-bg":              "#FFF8E7",
    "--panel-border":         "#8B4513",
    "--panel-border-width":   "4px",
    "--caption-bg":           "#FFE4B5",
    "--caption-border":       "#8B4513",
    "--caption-color":        "#5C2E00",
    "--bubble-bg":            "#FFFACD",
    "--bubble-border":        "#8B4513",
    "--speaker-color":        "#8B2500",
    "--sfx-color":            "#8B0000",
    "--sfx-shadow":           "#3A0000",
    "--page-num-color":       "#8B4513",
  },
  painted: {
    "--page-bg":              "#F5F0E8",
    "--panel-border":         "#4A3728",
    "--panel-border-width":   "3px",
    "--caption-bg":           "#E8DCC8",
    "--caption-border":       "#4A3728",
    "--caption-color":        "#2A1A0A",
    "--bubble-border":        "#4A3728",
    "--sfx-color":            "#7B3B00",
    "--sfx-shadow":           "#2A1000",
  },
};

/** Merge base vars with theme overrides, return as CSSStyleDeclaration-compatible object */
export function resolveThemeVars(themeName: string): Record<string, string> {
  return { ...BASE_VARS, ...(THEMES[themeName] ?? {}) };
}

function normalizePx(value: string | undefined, min: number, max: number): string | undefined {
  if (!value) return undefined;
  const match = value.match(/^(\d+(?:\.\d+)?)px$/);
  if (!match) return undefined;
  const n = Number(match[1]);
  if (!Number.isFinite(n)) return undefined;
  return `${Math.min(max, Math.max(min, n))}px`;
}

function normalizePct(value: string | undefined, min: number, max: number): string | undefined {
  if (!value) return undefined;
  const match = value.match(/^(\d+(?:\.\d+)?)%$/);
  if (!match) return undefined;
  const n = Number(match[1]);
  if (!Number.isFinite(n)) return undefined;
  return `${Math.min(max, Math.max(min, n))}%`;
}

export function sanitizeStyleVars(input: Record<string, string> | undefined): Record<string, string> {
  if (!input) return {};
  const out: Record<string, string> = { ...input };

  const bubbleFontSize = normalizePx(out["--bubble-font-size"], 16, 200);
  if (bubbleFontSize) out["--bubble-font-size"] = bubbleFontSize;
  else delete out["--bubble-font-size"];

  const captionFontSize = normalizePx(out["--caption-font-size"], 14, 80);
  if (captionFontSize) out["--caption-font-size"] = captionFontSize;
  else delete out["--caption-font-size"];

  const bubbleRadius = normalizePx(out["--bubble-radius"], 6, 120);
  if (bubbleRadius) out["--bubble-radius"] = bubbleRadius;
  else delete out["--bubble-radius"];

  const borderWidth = normalizePx(out["--bubble-border-width"], 1, 10);
  if (borderWidth) out["--bubble-border-width"] = borderWidth;
  else delete out["--bubble-border-width"];

  const bubbleMaxWidth = normalizePct(out["--bubble-max-width"], 38, 95);
  if (bubbleMaxWidth) out["--bubble-max-width"] = bubbleMaxWidth;
  else delete out["--bubble-max-width"];

  const bubbleCenterWidth = normalizePct(out["--bubble-center-width"], 45, 98);
  if (bubbleCenterWidth) out["--bubble-center-width"] = bubbleCenterWidth;
  else delete out["--bubble-center-width"];

  return out;
}

/** Return CSS variable declarations as a style object for React */
export function themeStyleObj(themeName: string): React.CSSProperties {
  const vars = resolveThemeVars(themeName);
  return vars as unknown as React.CSSProperties;
}
