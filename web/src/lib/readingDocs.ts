import type { CompletePageSummary, PageContent, PanelCamera, StoryBible } from "../types/api";

export type EntityKind = "character" | "place" | "prop";
export interface EntityRef { name: string; kind: EntityKind }

/** Story Bible names by entity id, so plans read "Mr. White", never `p0001s0001_mr_white`. */
export function entityNames(bible: StoryBible | undefined): Map<string, EntityRef> {
  const names = new Map<string, EntityRef>();
  for (const item of bible?.characters ?? []) names.set(item.id, { name: item.name, kind: "character" });
  for (const item of bible?.locations ?? []) names.set(item.id, { name: item.name, kind: "place" });
  for (const item of bible?.props ?? []) names.set(item.id, { name: item.name, kind: "prop" });
  return names;
}

/** A readable fallback for an id the Story Bible no longer has. */
export function entityLabel(names: Map<string, EntityRef>, id: string): string {
  const known = names.get(id);
  if (known) return known.name;
  const bare = id.replace(/^p\d+s\d+_/, "").replaceAll("_", " ");
  return bare.charAt(0).toUpperCase() + bare.slice(1);
}

/** Replaces entity ids inside free text (a gaze of `p0001s0001_mr_white`) with names. */
export function withEntityNames(names: Map<string, EntityRef>, text: string): string {
  return text.replace(/\bp\d+s\d+_[a-z0-9_]+\b/g, (id) => entityLabel(names, id));
}

/** The page each adapted beat lands on (its first appearance in reading order). */
export function beatPages(pages: CompletePageSummary[] | undefined): Map<string, number> {
  const placed = new Map<string, number>();
  for (const item of [...(pages ?? [])].sort((a, b) => a.page.page_number - b.page.page_number)) {
    for (const panel of item.page.content) {
      for (const beat of panel.beat_ids) if (!placed.has(beat)) placed.set(beat, item.page.page_number);
    }
  }
  return placed;
}

/** Panels in the page's reading order, falling back to their own order. */
export function panelsInOrder(content: PageContent[], readingOrder: string[]): PageContent[] {
  const position = new Map(readingOrder.map((id, index) => [id, index]));
  return [...content].sort((a, b) => (position.get(a.id) ?? 1000 + a.order) - (position.get(b.id) ?? 1000 + b.order));
}

/**
 * The author-facing layout note. Plan appends a "Canonical staging" block for
 * Draw; its facts are shown as structured panels instead, so the prose stops
 * before it.
 */
export function layoutSummary(layoutIntent: string): string {
  return layoutIntent.split(/\n\s*\n?Canonical staging/i)[0].trim();
}

export const SHOT_LABELS: Record<PanelCamera["shot"], string> = {
  extreme_close_up: "Extreme close-up", close_up: "Close-up", medium_close_up: "Medium close-up", medium: "Medium",
  medium_wide: "Medium wide", wide: "Wide", extreme_wide: "Extreme wide", insert: "Insert",
};
export const ANGLE_LABELS: Record<PanelCamera["angle"], string> = {
  eye_level: "Eye level", low_angle: "Low angle", high_angle: "High angle", overhead: "Overhead", worms_eye: "Worm’s-eye", dutch: "Dutch angle",
};
export const ROLE_LABELS: Record<PageContent["panel_role"], string> = {
  establishing: "Establishing", standard: "", detail: "Detail", reaction: "Reaction", action: "Action",
  transition: "Transition", splash: "Splash", inset: "Inset",
};
