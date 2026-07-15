import { describe, expect, it } from "vitest";
import type { CreditLedgerRun } from "../types/api";
import { groupRunsByStage } from "../lib/creditsHistory";

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
  it("groups repeated runs under one stage and totals their usage", () => {
    const groups = groupRunsByStage([
      run({ run_id: "cast-1" }),
      run({ run_id: "cast-2", actual_credits: 6, last_activity_at: "2026-07-15T12:02:00Z" }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Characters & Places");
    expect(groups[0].runs).toHaveLength(2);
    expect(groups[0].actualCredits).toBe(10);
  });

  it("keeps purchases in the same section-run-detail hierarchy", () => {
    const groups = groupRunsByStage([
      run({ run_id: "purchase", job_id: null, stage: null, actual_credits: 0, credits_added: 1200 }),
    ]);

    expect(groups[0].key).toBe("credits-added");
    expect(groups[0].label).toBe("Credits added");
    expect(groups[0].creditsAdded).toBe(1200);
  });

  it("ignores an undefined run instead of crashing the credits page", () => {
    const groups = groupRunsByStage([undefined, run({ run_id: "cast-1" })]);

    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBe("cast");
  });
});
