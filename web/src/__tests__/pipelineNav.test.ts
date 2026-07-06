import { describe, expect, it } from "vitest";
import { findPendingStage, findPendingStageAfter } from "../lib/pipelineNav";
import type { ProjectStatus, StageInfo, StageStatus } from "../types/api";

function stage(status: StageStatus): StageInfo {
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
  };
}

function status(stages: ProjectStatus["stages"]): ProjectStatus {
  return {
    id: "project",
    project_name: "Project",
    created_at: "2026-05-24T00:00:00Z",
    total_cost_credits: 0,
    misc_cost_credits: 0,
    total_estimated_cost_credits: 0,
    is_running: false,
    has_cover: false,
    style_selected: true,
    is_public: false,
    share_token: null,
    stages,
  };
}

describe("pipeline navigation stage selection", () => {
  it("finds the first pending stage in pipeline order", () => {
    expect(findPendingStage(status({
      extract: stage("complete"),
      style: stage("pending"),
      cast: stage("pending"),
    }))).toBe("style");
  });

  it("runs cast after approving style when style is selected", () => {
    expect(findPendingStageAfter(status({
      extract: stage("complete"),
      style: stage("awaiting_review"),
      cast: stage("pending"),
    }), "style")).toBe("cast");
  });

  it("does not look before the approved stage", () => {
    expect(findPendingStageAfter(status({
      extract: stage("pending"),
      style: stage("awaiting_review"),
      cast: stage("pending"),
    }), "style")).toBe("cast");
  });
});
