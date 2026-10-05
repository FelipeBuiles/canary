import type { ReferenceFreshness } from "../../api/storyBible";

/** Cast opens with this so the author's edits lead straight to its generate confirmation (see OutdatedReferences). */
export const UPDATE_REFERENCES_SEARCH = "?references=update";

/**
 * References the author's edits left without a current image: changed
 * entries (outdated) and added entries or looks (missing). Before Cast has
 * made any image every reference is missing, which is just Cast's first run,
 * so nothing is reported then.
 */
export function referencesToUpdate(references: ReferenceFreshness[] | undefined): ReferenceFreshness[] {
  const all = references ?? [];
  if (!all.some((ref) => ref.status !== "missing")) return [];
  return all.filter((ref) => ref.status !== "current");
}
