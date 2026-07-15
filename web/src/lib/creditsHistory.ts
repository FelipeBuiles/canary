import { stageLabel } from "./stageLabels";
import type { CreditLedgerRun } from "../types/api";

export interface StageLedgerGroup {
  key: string;
  label: string;
  latestAt: string;
  actualCredits: number;
  creditsAdded: number;
  runs: CreditLedgerRun[];
}

export function groupRunsByStage(
  runs: ReadonlyArray<CreditLedgerRun | null | undefined>,
): StageLedgerGroup[] {
  const groups = new Map<string, StageLedgerGroup>();
  for (const run of runs) {
    if (!run) continue;
    const key = run.stage ?? (run.credits_added > 0 ? "credits-added" : "adjustments");
    const label = run.stage
      ? stageLabel(run.stage)
      : run.credits_added > 0
        ? "Credits added"
        : "Account adjustments";
    const existing = groups.get(key) ?? {
      key,
      label,
      latestAt: run.last_activity_at,
      actualCredits: 0,
      creditsAdded: 0,
      runs: [],
    };
    existing.runs.push(run);
    existing.actualCredits += run.actual_credits;
    existing.creditsAdded += run.credits_added;
    if (run.last_activity_at > existing.latestAt) existing.latestAt = run.last_activity_at;
    groups.set(key, existing);
  }
  return [...groups.values()].sort((a, b) => b.latestAt.localeCompare(a.latestAt));
}
