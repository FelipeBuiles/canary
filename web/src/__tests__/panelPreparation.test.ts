import { describe, expect, it } from "vitest";
import { getPanelPreparationState } from "../lib/panelPreparation";
import type { ProjectStatus, StageInfo, StageStatus } from "../types/api";

function stage(
  status: StageStatus,
  overrides: Partial<StageInfo> = {},
): StageInfo {
  return {
    status,
    items_done: 0,
    items_total: 0,
    items_failed: [],
    approved: null,
    cost_credits: 0,
    estimated_cost_credits: 0,
    error: null,
    error_code: null,
    balance_credits: null,
    required_credits: null,
    shortfall_credits: null,
    started_at: null,
    finished_at: null,
    last_progress_at: null,
    stale: false,
    in_flight: [],
    ...overrides,
  };
}

function projectStatus(stages: ProjectStatus["stages"]): ProjectStatus {
  return {
    id: "project",
    project_name: "Project",
    created_at: "2026-07-13T00:00:00Z",
    total_cost_credits: 0,
    misc_cost_credits: 0,
    total_estimated_cost_credits: 0,
    is_running: true,
    has_cover: false,
    style_selected: true,
    is_public: false,
    share_token: null,
    stages,
  };
}

describe("getPanelPreparationState", () => {
  it("reports a failed Cast checkpoint instead of pretending preparation is starting", () => {
    const preparation = getPanelPreparationState(projectStatus({
      cast: stage("failed", { error: "location state image did not finish" }),
      adapt: stage("pending"),
      plan: stage("pending"),
      storyboard: stage("pending"),
      direct: stage("pending"),
    }));

    expect(preparation.blockedByStage).toBe("cast");
    expect(preparation.runningStage).toBeNull();
    expect(preparation.isReady).toBe(false);
  });

  it("derives completed, running, and waiting steps without combining totals", () => {
    const preparation = getPanelPreparationState(projectStatus({
      adapt: stage("complete", { items_done: 12, items_total: 12 }),
      plan: stage("running", { items_done: 4, items_total: 12 }),
      storyboard: stage("pending"),
      direct: stage("pending"),
    }));

    expect(preparation.completedCount).toBe(1);
    expect(preparation.runningStage).toBe("plan");
    expect(preparation.isReady).toBe(false);
    expect(preparation.steps.map((step) => step.state)).toEqual([
      "done",
      "running",
      "waiting",
      "waiting",
    ]);
    expect(preparation.steps[1]).toMatchObject({ itemsDone: 4, itemsTotal: 12 });
  });

  it("surfaces the interrupted stage", () => {
    const preparation = getPanelPreparationState(projectStatus({
      adapt: stage("complete"),
      plan: stage("complete"),
      storyboard: stage("failed", { error: "provider timeout" }),
      direct: stage("pending"),
    }));

    expect(preparation.failedStage).toBe("storyboard");
    expect(preparation.steps[2].state).toBe("failed");
    expect(preparation.isReady).toBe(false);
  });

  it("does not enable drawing when the final step completed with failed items", () => {
    const preparation = getPanelPreparationState(projectStatus({
      adapt: stage("complete"),
      plan: stage("complete"),
      storyboard: stage("complete"),
      direct: stage("complete", { items_failed: ["scene_03/panel_02"] }),
    }));

    expect(preparation.failedStage).toBe("direct");
    expect(preparation.completedCount).toBe(3);
    expect(preparation.isReady).toBe(false);
  });

  it("treats earlier stale failures as completed after a later stage progresses", () => {
    const preparation = getPanelPreparationState(projectStatus({
      adapt: stage("complete"),
      plan: stage("failed"),
      storyboard: stage("complete"),
      direct: stage("complete"),
    }));

    expect(preparation.failedStage).toBeNull();
    expect(preparation.completedCount).toBe(4);
    expect(preparation.isReady).toBe(true);
  });
});
