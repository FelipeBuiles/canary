import type { PageRedrawChange, PageRedrawReason } from "../../types/api";

const REASONS: Record<PageRedrawReason, string> = {
  image: "Cast image changed",
  description: "description changed",
  continuity: "continuity note changed",
  removed: "removed from the Story Bible",
};

/** "Carl (Cast image changed)" for each entry, merging repeats of the same label. */
export function describeRedrawChanges(changes: PageRedrawChange[], t: (key: string) => string): string[] {
  const reasons = new Map<string, Set<PageRedrawReason>>();
  for (const change of changes) {
    const seen = reasons.get(change.label) ?? new Set();
    change.reasons.forEach((reason) => seen.add(reason));
    reasons.set(change.label, seen);
  }
  return [...reasons].map(([label, why]) => `${label} (${[...why].map((reason) => t(REASONS[reason])).join(", ")})`);
}
