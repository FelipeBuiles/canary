import { splitProjectKey } from "../api/projectScope";
import type { Translator } from "../locales/messages";
import type { PartSummary } from "../types/api";

export type PartState = "not_started" | "analyzing" | "needs_brief" | "review" | "approved" | "finished" | "attention";

/** One reading of a part's progress, shared by the strip and its list. */
export function partState(part: PartSummary): PartState {
  const { extract, brief, finish } = part.stages;
  if (extract === "failed" || brief === "failed") return "attention";
  if (extract === "running" || brief === "running") return "analyzing";
  if (finish === "complete") return "finished";
  if (brief === "complete") return "approved";
  if (brief === "awaiting_review") return "review";
  if (extract === "complete") return "needs_brief";
  return "not_started";
}

/** How starting a part's analysis is explained when the book has several parts. */
export function partStartDescription(project: string, parts: PartSummary[], t: Translator) {
  const current = parts.find((part) => part.id === splitProjectKey(project).part);
  if (parts.length < 2 || !current) return undefined;
  return current.ordinal === 1
    ? t("Scenewright first reads the whole book once to map its acts and recurring characters, then analyzes Part 1 ({title}) in detail and prepares its story brief. Parts 2–{count} stay saved until you start them.", { title: current.title, count: parts.length })
    : t("Analyze Part {number} ({title}) and prepare its story brief. It continues from the parts before it; you review its brief before anything is drawn.", { number: current.ordinal, title: current.title });
}
