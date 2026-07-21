import { describe, expect, it } from "vitest";
import type { CreditLedgerRun, CreditTransaction } from "../types/api";
import { groupRunsByDay, runActivityLabel } from "../lib/creditsHistory";

function transaction(overrides: Partial<CreditTransaction> = {}): CreditTransaction {
  return {
    id: "tx-1",
    amount_credits: -4,
    status: "settled",
    stage: "cast",
    description: "Model call: cast.reference",
    project_id: "project-1",
    created_at: "2026-07-15T12:00:00Z",
    image_count: 0,
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
    rows: [],
    ...overrides,
  };
}

describe("credits history hierarchy", () => {
  it("keeps runs chronological and groups only by calendar day", () => {
    const groups = groupRunsByDay([
      run({ run_id: "older", last_activity_at: "2026-07-15T12:02:00Z" }),
      run({ run_id: "newest", stage: "draw", last_activity_at: "2026-07-16T13:00:00Z" }),
      run({ run_id: "middle", stage: "style", actual_credits: 6, last_activity_at: "2026-07-15T14:00:00Z" }),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0].runs.map((item) => item.run_id)).toEqual(["newest"]);
    expect(groups[1].runs.map((item) => item.run_id)).toEqual(["middle", "older"]);
    expect(groups[1].actualCredits).toBe(10);
  });

  it("keeps purchases in chronology and totals added credits by day", () => {
    const groups = groupRunsByDay([
      run({ run_id: "purchase", job_id: null, stage: null, actual_credits: 0, credits_added: 1200 }),
    ]);

    expect(groups[0].creditsAdded).toBe(1200);
    expect(groups[0].runs[0].run_id).toBe("purchase");
  });

  it("uses author-facing action labels and panel counts", () => {
    const drawRun = run({
      stage: "draw",
      rows: [
        transaction({ stage: "draw", image_count: 1 }),
        transaction({ id: "tx-2", stage: "draw", image_count: 1 }),
      ],
    });

    expect(runActivityLabel(drawRun)).toBe("Draw 2 panels");
    expect(runActivityLabel(run({ stage: "cast" }))).toBe("Create characters & places");
    expect(runActivityLabel(run({ stage: null, credits_added: 1200 }))).toBe("Credit purchase");
  });

  it("ignores an undefined run instead of crashing the credits page", () => {
    const groups = groupRunsByDay([undefined, run({ run_id: "cast-1" })]);

    expect(groups).toHaveLength(1);
    expect(groups[0].runs[0].run_id).toBe("cast-1");
  });
});
