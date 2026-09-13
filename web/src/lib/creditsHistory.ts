import type { CreditLedgerRun } from "../types/api";

export interface LedgerDayGroup {
  key: string;
  latestAt: string;
  actualCredits: number;
  creditsAdded: number;
  runs: CreditLedgerRun[];
}

export type LedgerFilter = "all" | "charged" | "held" | "failed" | "added";

export function matchesLedgerFilter(run: CreditLedgerRun, filter: LedgerFilter): boolean {
  switch (filter) {
    case "charged": return run.actual_credits > 0;
    case "held": return run.status === "in_flight";
    case "failed": return run.status === "failed";
    case "added": return run.credits_added > 0;
    default: return true;
  }
}

export interface LedgerActivityGroup {
  key: string;
  label: string;
  projectId: string | null;
  actualCredits: number;
  heldCredits: number;
  creditsAdded: number;
  failedCount: number;
  heldCount: number;
  runs: CreditLedgerRun[];
}

/** Condense page jobs without merging their accounting records or outcomes. */
export function groupRunsByActivity(runs: readonly CreditLedgerRun[]): LedgerActivityGroup[] {
  const groups = new Map<string, LedgerActivityGroup>();
  for (const run of runs) {
    const category = run.credits_added > 0 ? "purchase" : run.stage ?? "adjustment";
    const key = JSON.stringify([run.project_id, category]);
    const group = groups.get(key) ?? {
      key, label: category === "draw" ? "Draw pages" : runActivityLabel(run),
      projectId: run.project_id, actualCredits: 0, heldCredits: 0, creditsAdded: 0,
      failedCount: 0, heldCount: 0, runs: [],
    };
    group.runs.push(run);
    group.actualCredits += run.actual_credits;
    group.creditsAdded += run.credits_added;
    group.failedCount += Number(run.status === "failed");
    if (run.status === "in_flight") {
      group.heldCount++;
      group.heldCredits += run.estimate_credits;
    }
    groups.set(key, group);
  }
  return [...groups.values()];
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
