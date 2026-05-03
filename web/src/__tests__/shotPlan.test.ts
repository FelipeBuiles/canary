import { describe, expect, it } from "vitest";
import { getShotPlanAction, getShotPlanSubStatus } from "../lib/shotPlan";
import type { ProjectStatus, StageInfo, StageStatus } from "../types/api";

function stage(status: StageStatus, failed: string[] = []): StageInfo {
  return {
    status,
    items_done: 0,
    items_total: 0,
    items_failed: failed,
    cost_usd: 0,
    estimated_cost_usd: 0,
    error: null,
    started_at: null,
    finished_at: null,
    stale: false,
  };
}

function status(plan?: StageStatus, storyboard?: StageStatus): ProjectStatus {
  return {
    id: "project",
    project_name: "Project",
    created_at: "2026-05-02T00:00:00Z",
    total_cost_usd: 0,
    misc_cost_usd: 0,
    total_estimated_cost_usd: 0,
    is_running: false,
    has_cover: false,
    style_selected: true,
    is_public: false,
    share_token: null,
    stages: {
      ...(plan ? { plan: stage(plan) } : {}),
      ...(storyboard ? { storyboard: stage(storyboard) } : {}),
    },
  };
}

describe("getShotPlanAction", () => {
  it("runs plan when layout is pending", () => {
    expect(getShotPlanAction(status("pending"))).toMatchObject({
      kind: "run",
      backendStage: "plan",
      label: "Run Shot Plan",
    });
  });

  it("approves layout and builds board when plan needs review", () => {
    expect(getShotPlanAction(status("awaiting_review"))).toMatchObject({
      kind: "approve",
      backendStage: "plan",
      estimateStage: "storyboard",
      runAfterApprove: true,
    });
  });

  it("builds board when layout is complete and board is pending", () => {
    expect(getShotPlanAction(status("complete", "pending"))).toMatchObject({
      kind: "run",
      backendStage: "storyboard",
      label: "Build Board",
    });
  });

  it("approves storyboard when board needs review", () => {
    expect(getShotPlanAction(status("complete", "awaiting_review"))).toMatchObject({
      kind: "approve",
      backendStage: "storyboard",
      label: "Approve Shot Plan & Continue",
    });
  });

  it("reruns the failed sub-stage", () => {
    expect(getShotPlanAction(status("complete", "failed"))).toMatchObject({
      kind: "rerun",
      backendStage: "storyboard",
      label: "Fix Board",
    });
  });

  it("has no local action when both sub-stages are complete", () => {
    expect(getShotPlanAction(status("complete", "complete"))).toEqual({
      kind: "none",
      label: "Shot Plan Complete",
    });
  });
});

describe("getShotPlanSubStatus", () => {
  it("summarizes layout and board review state", () => {
    expect(getShotPlanSubStatus(status("complete", "awaiting_review"))).toMatchObject({
      status: "awaiting_review",
      detail: "Layout complete · Board needs review",
    });
  });
});
