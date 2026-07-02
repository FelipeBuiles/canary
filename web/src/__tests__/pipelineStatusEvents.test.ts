import { describe, expect, it } from "vitest";
import { applyStageEventToProjectStatus } from "../lib/pipelineStatusEvents";
import type { ProjectStatus, StageInfo, StageStatus } from "../types/api";

function stage(status: StageStatus, total = 0): StageInfo {
  return {
    status,
    items_done: 0,
    items_total: total,
    items_failed: [],
    approved: null,
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

function status(): ProjectStatus {
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
      compose: stage("pending"),
      draw: stage("pending"),
    },
  };
}

describe("applyStageEventToProjectStatus", () => {
  it("applies stage_begin totals to the running stage", () => {
    const next = applyStageEventToProjectStatus(status(), {
      type: "stage_begin",
      stage: "compose",
      total: 12,
    });

    expect(next?.is_running).toBe(true);
    expect(next?.stages.compose).toMatchObject({
      status: "running",
      items_done: 0,
      items_total: 12,
      error: null,
      finished_at: null,
    });
  });

  it("applies stage_progress without waiting for status polling", () => {
    const current = status();
    current.stages.compose = stage("running", 12);

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_progress",
      stage: "compose",
      done: 5,
      total: 12,
    });

    expect(next?.stages.compose.items_done).toBe(5);
    expect(next?.stages.compose.items_total).toBe(12);
    expect(next?.stages.compose.status).toBe("running");
  });

  it("marks completed checkpoint stages as awaiting review", () => {
    const current = status();
    current.stages.draw = stage("running", 3);

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_complete",
      stage: "draw",
      done: 3,
      total: 3,
    });

    expect(next?.is_running).toBe(true);
    expect(next?.stages.draw.status).toBe("awaiting_review");
    expect(next?.stages.draw.items_done).toBe(3);
    expect(next?.stages.draw.finished_at).toBeTruthy();
  });

  it("marks completed non-checkpoint stages as complete", () => {
    const current = status();
    current.stages.compose = stage("running", 8);

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_complete",
      stage: "compose",
      done: 8,
      total: 8,
    });

    expect(next?.stages.compose.status).toBe("complete");
    expect(next?.stages.compose.items_done).toBe(8);
  });

  it("marks failed stages with the streamed error", () => {
    const current = status();
    current.stages.draw = stage("running", 3);

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_fail",
      stage: "draw",
      message: "image provider failed",
    });

    expect(next?.is_running).toBe(false);
    expect(next?.stages.draw.status).toBe("failed");
    expect(next?.stages.draw.error).toBe("image provider failed");
    expect(next?.stages.draw.finished_at).toBeTruthy();
  });
});
