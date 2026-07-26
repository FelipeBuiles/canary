import type { CreditLedgerRun } from "../types/api";

export interface LedgerDayGroup {
  key: string;
  latestAt: string;
  actualCredits: number;
  creditsAdded: number;
  runs: CreditLedgerRun[];
}

function localDayKey(iso: string): string {
  const date = new Date(iso);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Keep accounting activity in ledger order, using dates only as scan anchors. */
export function groupRunsByDay(
  runs: ReadonlyArray<CreditLedgerRun | null | undefined>,
): LedgerDayGroup[] {
  const groups = new Map<string, LedgerDayGroup>();
  const orderedRuns = runs
    .filter((run): run is CreditLedgerRun => Boolean(run))
    .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at));

  for (const run of orderedRuns) {
    const key = localDayKey(run.last_activity_at);
    const existing = groups.get(key) ?? {
      key,
      latestAt: run.last_activity_at,
      actualCredits: 0,
      creditsAdded: 0,
      runs: [],
    };
    existing.runs.push(run);
    existing.actualCredits += run.actual_credits;
    existing.creditsAdded += run.credits_added;
    groups.set(key, existing);
  }

  return [...groups.values()].sort((a, b) => b.latestAt.localeCompare(a.latestAt));
}

const STAGE_ACTIVITY_LABELS: Record<string, string> = {
  extract: "Analyze story",
  brief: "Set adaptation brief",
  style: "Create art style",
  cast: "Create characters & places",
  adapt: "Adapt story",
  plan: "Plan pages",
  finish: "Finish book",
};

/** Describe what the author asked Scenewright to do, not the internal stage. */
export function runActivityLabel(run: CreditLedgerRun): string {
  if (run.credits_added > 0) return "Credit purchase";

  if (run.stage === "draw") {
    const imageCount = run.rows.reduce(
      (total, row) => total + (row.status === "settled" && row.amount_credits < 0 ? (row.image_count ?? 0) : 0),
      0,
    );
    if (imageCount === 1) return "Draw page";
    if (imageCount > 1) return `Draw ${imageCount} pages`;
    return "Draw pages";
  }

  if (run.stage && STAGE_ACTIVITY_LABELS[run.stage]) {
    return STAGE_ACTIVITY_LABELS[run.stage];
  }
  return "Account adjustment";
}
