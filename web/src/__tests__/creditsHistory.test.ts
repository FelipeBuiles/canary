import { describe, expect, it } from "vitest";
import type { CreditLedgerRun, CreditTransaction } from "../types/api";
import {
  chargeBreakdown,
  formatPageRanges,
  groupRunsByDay,
  groupRunsIntoSessions,
  matchesLedgerFilter,
  spendByPhase,
  type LedgerSession,
} from "../lib/creditsHistory";

function transaction(overrides: Partial<CreditTransaction> = {}): CreditTransaction {
  return {
    id: "tx-1",
    amount_credits: -4,
    status: "settled",
    stage: "cast",
    created_at: "2026-07-15T12:00:00Z",
    image_count: 0,
    label: "Character reference",
    page_number: null,
    ...overrides,
  };
}

function run(overrides: Partial<CreditLedgerRun>): CreditLedgerRun {
  return {
    run_id: "run-1",
    job_id: "job-1",
    stage: "cast",
    project_id: "project-1",
    started_at: "2026-07-15T12:00:00Z",
    last_activity_at: "2026-07-15T12:01:00Z",
    estimate_credits: 0,
    actual_credits: 4,
    returned_credits: 0,
    credits_added: 0,
    status: "complete",
    action: null,
    page_number: null,
    rows: [],
    ...overrides,
  };
}

function pageRun(page: number, minute: number, rows: Partial<CreditTransaction>[] = [{}], overrides: Partial<CreditLedgerRun> = {}) {
  const at = `2026-07-15T12:${String(minute).padStart(2, "0")}:00Z`;
  const charges = rows.map((row, index) => transaction({
    id: `p${page}-${minute}-${index}`, stage: "draw", label: "Page art", amount_credits: -1, page_number: page, ...row,
  }));
  return run({
    run_id: `page-${page}-${minute}`, stage: "draw", page_number: page, started_at: at, last_activity_at: at,
    estimate_credits: 4, actual_credits: charges.reduce((sum, row) => sum - row.amount_credits, 0),
    returned_credits: 4 - charges.reduce((sum, row) => sum - row.amount_credits, 0), rows: charges, ...overrides,
  });
}

function sessions(runs: CreditLedgerRun[]): LedgerSession[] {
  return groupRunsIntoSessions(runs).flatMap((entry) => entry.kind === "session" ? [entry.session] : []);
}

describe("credit history days", () => {
  it("keeps runs chronological and totals charges and still-open holds by day", () => {
    const groups = groupRunsByDay([
      run({ run_id: "older", last_activity_at: "2026-07-15T12:02:00Z" }),
      run({ run_id: "newest", stage: "draw", last_activity_at: "2026-07-16T13:00:00Z" }),
      run({ run_id: "middle", stage: "plan", status: "in_flight", actual_credits: 36, estimate_credits: 67, last_activity_at: "2026-07-15T14:00:00Z" }),
    ]);

    expect(groups.map((group) => group.runs.map((item) => item.run_id))).toEqual([["newest"], ["middle", "older"]]);
    expect(groups[1]).toMatchObject({ chargedCredits: 40, openHoldCredits: 31 });
  });

  it("ignores an undefined run instead of crashing the credits page", () => {
    expect(groupRunsByDay([undefined, run({ run_id: "cast-1" })])[0].runs[0].run_id).toBe("cast-1");
  });
});

describe("work sessions", () => {
  it("folds one sitting of page draws into a single session with its pages", () => {
    const [draw] = sessions([pageRun(3, 10), pageRun(1, 5), pageRun(2, 7)]);

    expect(draw.runs).toHaveLength(3);
    expect(draw.pageNumbers).toEqual([1, 2, 3]);
    expect(draw).toMatchObject({ chargedCredits: 3, settledReservedCredits: 12, returnedCredits: 9, inFlight: false });
    expect(draw.startedAt).toBe("2026-07-15T12:05:00Z");
    expect(draw.endedAt).toBe("2026-07-15T12:10:00Z");
  });

  it("starts a new session after a long gap, another project, or other work", () => {
    const result = sessions([
      pageRun(1, 0),
      pageRun(2, 59, [{}], { started_at: "2026-07-15T12:59:00Z", last_activity_at: "2026-07-15T13:50:00Z" }),
      pageRun(3, 1, [{}], { project_id: "project-2" }),
      run({ run_id: "plan", stage: "plan", last_activity_at: "2026-07-15T12:02:00Z" }),
    ]);

    expect(result.map((session) => session.runs.map((item) => item.run_id))).toEqual([
      ["page-2-59"], ["plan"], ["page-3-1"], ["page-1-0"],
    ]);
  });

  it("keeps purchases apart and gathers unfinished no-charge attempts at the end of the day", () => {
    const entries = groupRunsIntoSessions([
      run({ run_id: "buy-1", stage: null, credits_added: 1200, actual_credits: 0 }),
      run({ run_id: "buy-2", stage: null, credits_added: 500, actual_credits: 0 }),
      run({ run_id: "failed", stage: "draw", status: "failed", actual_credits: 0, estimate_credits: 4, returned_credits: 4 }),
    ]);

    expect(entries.map((entry) => entry.kind)).toEqual(["session", "session", "unfinished"]);
    expect(entries[2]).toMatchObject({ kind: "unfinished", runs: [expect.objectContaining({ run_id: "failed" })] });
  });

  it("tracks open holds separately from what unfinished work has used", () => {
    const [plan] = sessions([run({ stage: "plan", status: "in_flight", estimate_credits: 67, actual_credits: 36 })]);

    expect(plan).toMatchObject({ inFlight: true, openReservedCredits: 67, openUsedCredits: 36, settledReservedCredits: 0 });
  });

  it("names targeted actions as their own kind of work", () => {
    const result = sessions([
      run({ run_id: "ref", action: "Character reference" }),
      run({ run_id: "cast" }),
    ]);
    expect(result.map((session) => session.action)).toEqual(["Character reference", null]);
  });

  it("keeps the activity filters on accounting outcomes", () => {
    const failed = run({ status: "failed", actual_credits: 3 });
    expect(matchesLedgerFilter(failed, "failed")).toBe(true);
    expect(matchesLedgerFilter(failed, "charged")).toBe(true);
    expect(matchesLedgerFilter(failed, "held")).toBe(false);
    expect(matchesLedgerFilter(failed, "added")).toBe(false);
  });
});

describe("charge breakdown", () => {
  it("combines repeated steps instead of listing every model call", () => {
    const [plan] = sessions([run({
      stage: "plan",
      actual_credits: 36,
      rows: [
        transaction({ id: "hold", status: "released", amount_credits: -67, label: "Credit hold" }),
        transaction({ id: "map", amount_credits: -3, label: "Page map" }),
        ...[2, 2, 4, 9, 9, 7].map((credits, index) => transaction({ id: `d${index}`, amount_credits: -credits, label: "Page details" })),
      ],
    })]);

    expect(chargeBreakdown(plan)).toEqual([
      expect.objectContaining({ label: "Page map", steps: 1, credits: 3 }),
      expect.objectContaining({ label: "Page details", steps: 6, credits: 33 }),
    ]);
  });

  it("ranges plain pages together and calls out pages with extra work", () => {
    const [draw] = sessions([
      pageRun(1, 1), pageRun(2, 2), pageRun(3, 3), pageRun(5, 5),
      pageRun(4, 4, [{}, { label: "Visual check" }]),
      pageRun(7, 6), pageRun(7, 8),
    ]);

    const lines = chargeBreakdown(draw);
    expect(lines.map((line) => [line.pages, line.details, line.steps, line.credits])).toEqual([
      [[1, 2, 3, 5], ["Page art"], 4, 4],
      [[4], ["Page art", "Visual check"], 1, 2],
      [[7], ["Page art"], 2, 2],
    ]);
  });

  it("formats page ranges for reading", () => {
    expect(formatPageRanges([11, 1, 2, 3, 5, 6, 8, 9, 10])).toBe("1–3, 5, 6, 8–11");
  });
});

describe("spend by phase", () => {
  it("folds stages into author phases and drops empty ones", () => {
    expect(spendByPhase({ extract: 10, brief: 2, plan: 30, draw: 400, mystery: 3 })).toEqual([
      { key: "story", label: "Story", credits: 12 },
      { key: "adapt", label: "Adapt and plan", credits: 30 },
      { key: "draw", label: "Draw", credits: 400 },
      { key: "other", label: "Other", credits: 3 },
    ]);
    expect(spendByPhase(undefined)).toEqual([]);
  });
});
