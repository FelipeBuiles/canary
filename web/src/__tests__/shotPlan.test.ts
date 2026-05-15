import { describe, expect, it } from "vitest";
import { getShotPlanAction, getShotPlanSubStatus } from "../lib/shotPlan";
import type { ProjectStatus, StageInfo, StageStatus } from "../types/api";

function stage(status: StageStatus, failed: string[] = []): StageInfo {
  return {
    status,
    items_done: 0,
    items_total: 0,
    items_failed: failed,
    cost_credits: 0,
    estimated_cost_credits: 0,
    error: null,
    started_at: null,
    finished_at: null,
    last_progress_at: null,
    stale: false,
    in_flight: [],
  };
}

function status(plan?: StageStatus, storyboard?: StageStatus): ProjectStatus {
  return {
    id: "project",
    project_name: "Project",
    created_at: "2026-05-02T00:00:00Z",
    total_cost_credits: 0,
    misc_cost_credits: 0,
    total_estimated_cost_credits: 0,
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

  it("runs plan when no stages exist yet", () => {
    expect(getShotPlanAction(status())).toMatchObject({
      kind: "run",
      backendStage: "plan",
      label: "Run Shot Plan",
    });
  });

  it("reruns plan when layout failed", () => {
    expect(getShotPlanAction(status("failed"))).toMatchObject({
      kind: "rerun",
      backendStage: "plan",
      label: "Fix Shot Plan",
    });
  });

  it("reruns storyboard when board failed", () => {
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

  it("has no local action while plan is running (storyboard auto-chains)", () => {
    expect(getShotPlanAction(status("running"))).toEqual({
      kind: "none",
      label: "Running…",
    });
  });

  it("has no local action while storyboard is running", () => {
    expect(getShotPlanAction(status("complete", "running"))).toEqual({
      kind: "none",
      label: "Running…",
    });
  });
});

describe("getShotPlanSubStatus", () => {
  it("shows running when plan is complete and storyboard is auto-chaining", () => {
    expect(getShotPlanSubStatus(status("complete", "pending"))).toMatchObject({
      status: "running",
    });
  });

  it("shows complete when both stages are done", () => {
    expect(getShotPlanSubStatus(status("complete", "complete"))).toMatchObject({
      status: "complete",
      detail: "Layout complete · Board complete",
    });
  });

  it("shows failed when storyboard failed", () => {
    expect(getShotPlanSubStatus(status("complete", "failed"))).toMatchObject({
      status: "failed",
    });
  });
});
