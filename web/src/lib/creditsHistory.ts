import { msg } from "../locales/messages";
import type { CreditLedgerRun } from "../types/api";

export interface LedgerDayGroup {
  key: string;
  latestAt: string;
  chargedCredits: number;
  /** Credits still reserved by unfinished work, beyond what it has already been charged. */
  openHoldCredits: number;
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

function openHold(run: CreditLedgerRun): number {
  return run.status === "in_flight" ? Math.max(0, run.estimate_credits - run.actual_credits) : 0;
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
      chargedCredits: 0,
      openHoldCredits: 0,
      creditsAdded: 0,
      runs: [],
    };
    existing.runs.push(run);
    existing.chargedCredits += run.actual_credits;
    existing.openHoldCredits += openHold(run);
    existing.creditsAdded += run.credits_added;
    groups.set(key, existing);
  }

  return [...groups.values()].sort((a, b) => b.latestAt.localeCompare(a.latestAt));
}

/** One sitting of the same kind of work on one project, e.g. eleven page draws. */
export interface LedgerSession {
  key: string;
  stage: string | null;
  action: string | null;
  projectId: string | null;
  purchase: boolean;
  /** Newest first, like the ledger. */
  runs: CreditLedgerRun[];
  startedAt: string;
  endedAt: string;
  chargedCredits: number;
  creditsAdded: number;
  /** Holds of finished runs: what was set aside, and what came back. */
  settledReservedCredits: number;
  returnedCredits: number;
  /** Unfinished runs: what they set aside so far, and what they have used of it. */
  openReservedCredits: number;
  openUsedCredits: number;
  inFlight: boolean;
  pageNumbers: number[];
}

export type LedgerEntry =
  | { kind: "session"; session: LedgerSession }
  | { kind: "unfinished"; key: string; runs: CreditLedgerRun[] };

/** Runs of the same work further apart than this start a new session. */
export const SESSION_GAP_MS = 45 * 60_000;

function newSession(key: string, run: CreditLedgerRun): LedgerSession {
  return {
    key,
    stage: run.stage,
    action: run.action,
    projectId: run.project_id,
    purchase: run.credits_added > 0,
    runs: [],
    startedAt: run.started_at,
    endedAt: run.last_activity_at,
    chargedCredits: 0,
    creditsAdded: 0,
    settledReservedCredits: 0,
    returnedCredits: 0,
    openReservedCredits: 0,
    openUsedCredits: 0,
    inFlight: false,
    pageNumbers: [],
  };
}

function addRun(session: LedgerSession, run: CreditLedgerRun) {
  session.runs.push(run);
  if (run.started_at < session.startedAt) session.startedAt = run.started_at;
  if (run.last_activity_at > session.endedAt) session.endedAt = run.last_activity_at;
  session.chargedCredits += run.actual_credits;
  session.creditsAdded += run.credits_added;
  if (run.status === "in_flight") {
    session.inFlight = true;
    session.openReservedCredits += run.estimate_credits;
    session.openUsedCredits += run.actual_credits;
  } else {
    session.settledReservedCredits += run.estimate_credits;
    session.returnedCredits += run.returned_credits;
  }
  if (run.page_number !== null && !session.pageNumbers.includes(run.page_number)) {
    session.pageNumbers.push(run.page_number);
    session.pageNumbers.sort((a, b) => a - b);
  }
}

/**
 * Fold one day's runs into work sessions without merging their accounting.
 * Same project and same kind of work within {@link SESSION_GAP_MS} of each
 * other form one session; purchases stand alone; runs that ended without a
 * charge collect in one quiet entry at the end of the day.
 */
export function groupRunsIntoSessions(runs: readonly CreditLedgerRun[]): LedgerEntry[] {
  const entries: LedgerEntry[] = [];
  const open = new Map<string, LedgerSession>();
  const unfinished: CreditLedgerRun[] = [];
  const ordered = [...runs].sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at));

  for (const run of ordered) {
    if (run.status === "failed" && run.actual_credits === 0) {
      unfinished.push(run);
      continue;
    }
    const kind = run.credits_added > 0 ? `purchase:${run.run_id}` : run.action ?? run.stage ?? "adjustment";
    const key = JSON.stringify([run.project_id, kind]);
    let session = open.get(key);
    if (!session || Date.parse(session.startedAt) - Date.parse(run.last_activity_at) > SESSION_GAP_MS) {
      session = newSession(`${key}:${run.run_id}`, run);
      open.set(key, session);
      entries.push({ kind: "session", session });
    }
    addRun(session, run);
  }

  if (unfinished.length) entries.push({ kind: "unfinished", key: `unfinished:${unfinished[0].run_id}`, runs: unfinished });
  return entries;
}

/** One line of a session's breakdown: a step, a page, or a run of identical pages. */
export interface ChargeLine {
  key: string;
  label: string;
  pages: number[];
  /** How many charges this line combines (model steps, or page attempts). */
  steps: number;
  /** Distinct step labels behind a single page, in order. */
  details: string[];
  credits: number;
}

/** Customer-facing charge labels the server sends; listed so they are translated. */
export const CHARGE_LABELS = [
  msg("Story map"), msg("Story map summary"), msg("Scenes"), msg("Story bible"), msg("Adaptation brief"),
  msg("Story bible entry"), msg("Style suggestions"), msg("Sample brief"), msg("Style sample"),
  msg("Sample lettering"), msg("Production style"), msg("Style name"), msg("Style direction"), msg("Style check"),
  msg("Character and place designs"), msg("Character reference"), msg("Appearance reference"),
  msg("Location reference"), msg("Location variant"), msg("Location style board"), msg("Prop reference"), msg("Prop variant"),
  msg("Instruction rewrite"), msg("Visual check"), msg("Book adaptation"), msg("Narrative treatment"),
  msg("Scene blueprint"), msg("Lettering copy"), msg("Book plan"), msg("Page map"), msg("Page details"),
  msg("Page art"), msg("Text check"), msg("Story review"), msg("Lettering translation"), msg("Cover"),
  msg("Other steps"),
];

function chargedRows(session: LedgerSession) {
  // Oldest run first, so lines read in the order the work happened.
  return [...session.runs].reverse().flatMap((run) =>
    run.rows
      .filter((row) => row.status === "settled" && row.amount_credits < 0)
      .map((row) => ({ run, row })));
}

function stepLines(rows: ReturnType<typeof chargedRows>): ChargeLine[] {
  const lines = new Map<string, ChargeLine>();
  for (const { row } of rows) {
    const line = lines.get(row.label) ?? { key: `step:${row.label}`, label: row.label, pages: [], steps: 0, details: [], credits: 0 };
    line.steps += 1;
    line.credits += -row.amount_credits;
    lines.set(row.label, line);
  }
  return [...lines.values()];
}

/**
 * Summarize what a session paid for. Steps with the same name combine into
 * one line; page draws become one line per page, and pages that each cost the
 * same single page-art charge combine into one ranged line.
 */
export function chargeBreakdown(session: LedgerSession): ChargeLine[] {
  const rows = chargedRows(session);
  if (session.stage !== "draw") return stepLines(rows);

  const pages = new Map<number, { credits: number; attempts: Set<string>; details: string[] }>();
  const unpaged: typeof rows = [];
  for (const entry of rows) {
    const page = entry.run.page_number;
    if (page === null) { unpaged.push(entry); continue; }
    const current = pages.get(page) ?? { credits: 0, attempts: new Set<string>(), details: [] };
    current.credits += -entry.row.amount_credits;
    current.attempts.add(entry.run.run_id);
    if (!current.details.includes(entry.row.label)) current.details.push(entry.row.label);
    pages.set(page, current);
  }

  const lines: ChargeLine[] = [];
  const plain = new Map<number, number[]>();
  for (const [page, info] of [...pages.entries()].sort(([a], [b]) => a - b)) {
    const isPlain = info.attempts.size === 1 && info.details.length === 1 && info.details[0] === "Page art";
    if (isPlain) {
      plain.set(info.credits, [...(plain.get(info.credits) ?? []), page]);
      continue;
    }
    lines.push({ key: `page:${page}`, label: "Page art", pages: [page], steps: info.attempts.size, details: info.details, credits: info.credits });
  }
  for (const [each, pageList] of plain) {
    lines.push({ key: `pages:${each}`, label: "Page art", pages: pageList, steps: pageList.length, details: ["Page art"], credits: each * pageList.length });
  }
  lines.sort((a, b) => a.pages[0] - b.pages[0]);
  return [...lines, ...stepLines(unpaged)];
}

/** "1–3, 5, 6, 8–11": runs of three or more pages collapse into a range. */
export function formatPageRanges(pages: readonly number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let index = 0; index < sorted.length;) {
    let end = index;
    while (end + 1 < sorted.length && sorted[end + 1] === sorted[end] + 1) end++;
    if (end - index >= 2) parts.push(`${sorted[index]}–${sorted[end]}`);
    else for (let page = index; page <= end; page++) parts.push(String(sorted[page]));
    index = end + 1;
  }
  return parts.join(", ");
}

export interface SpendPhase {
  key: string;
  label: string;
  credits: number;
}

const PHASES: ReadonlyArray<{ key: string; label: string; stages: readonly string[] }> = [
  { key: "story", label: msg("Story"), stages: ["extract", "brief"] },
  { key: "look", label: msg("Look"), stages: ["style", "cast"] },
  { key: "adapt", label: msg("Adapt and plan"), stages: ["adapt", "plan"] },
  { key: "draw", label: msg("Draw"), stages: ["draw"] },
  { key: "finish", label: msg("Finish"), stages: ["finish"] },
];

/** Fold per-stage charges into the phases an author recognizes; empty phases drop out. */
export function spendByPhase(spendByStage: Readonly<Record<string, number>> | undefined): SpendPhase[] {
  const phases = PHASES.map((phase) => ({ key: phase.key, label: phase.label, credits: 0 }));
  const other: SpendPhase = { key: "other", label: msg("Other"), credits: 0 };
  for (const [stage, credits] of Object.entries(spendByStage ?? {})) {
    const index = PHASES.findIndex((phase) => phase.stages.includes(stage));
    (index < 0 ? other : phases[index]).credits += credits;
  }
  return [...phases, other].filter((phase) => phase.credits > 0);
}
