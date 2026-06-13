/**
 * Theme + font tokens for the live comic canvas.
 *
 * Tokens are synced from the canonical backend file
 * (novel_to_comic/.../assembly/theme_tokens.json) via `npm run sync-tokens`
 * into src/generated/theme_tokens.json, so the canvas and the PNG/PDF renderer
 * can never drift. A vitest parity test asserts the two stay identical.
 */
import tokens from "../../generated/theme_tokens.json";
import type { LetteringStyle } from "../../types/api";

export type ThemeName = "default" | "noir" | "manga" | "vintage" | "painted";

export const THEME_NAMES: ThemeName[] = ["default", "noir", "manga", "vintage", "painted"];

export const BASE_VARS: Record<string, string> = tokens.base;
export const THEMES: Record<string, Record<string, string>> = tokens.themes;
export const FONT_PAIRS: Record<string, Record<string, string>> = tokens.font_pairs;

/** Merge base vars with a theme preset's overrides. */
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

/**
 * Resolve the full CSS-var set for a project's lettering style, lowest →
 * highest precedence: BASE → theme → font pair → sanitized overrides.
 * Mirrors the backend's `_vars_css(ls.theme, FONT_PAIRS[ls.font_pair] | ls.vars)`.
 */
export function resolveLetteringVars(ls: LetteringStyle | undefined | null): Record<string, string> {
  if (!ls) return { ...BASE_VARS };
  return {
    ...BASE_VARS,
    ...(THEMES[ls.theme] ?? {}),
    ...(FONT_PAIRS[ls.font_pair] ?? {}),
    ...sanitizeStyleVars(ls.vars),
  };
}

/** Return CSS variable declarations as a style object for React. */
export function themeStyleObj(themeName: string): React.CSSProperties {
  return resolveThemeVars(themeName) as unknown as React.CSSProperties;
}
