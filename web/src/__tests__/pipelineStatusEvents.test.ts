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
      brief: stage("pending"),
      finish: stage("pending"),
      draw: stage("pending"),
    },
  };
}

describe("applyStageEventToProjectStatus", () => {
  it("applies stage_begin totals to the running stage", () => {
    const next = applyStageEventToProjectStatus(status(), {
      type: "stage_begin",
      stage: "finish",
      total: 12,
    });

    expect(next?.is_running).toBe(true);
    expect(next?.stages.finish).toMatchObject({
      status: "running",
      items_done: 0,
      items_total: 12,
      error: null,
      finished_at: null,
    });
  });

  it("applies stage_progress without waiting for status polling", () => {
    const current = status();
    current.stages.finish = stage("running", 12);

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_progress",
      stage: "finish",
      done: 5,
      total: 12,
    });

    expect(next?.stages.finish.items_done).toBe(5);
    expect(next?.stages.finish.items_total).toBe(12);
    expect(next?.stages.finish.status).toBe("running");
  });

  it("ignores stage_activity so a streaming fraction never becomes item progress", () => {
    const current = status();
    current.stages.adapt = stage("running", 5);
    current.stages.adapt.items_done = 2;

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_activity",
      stage: "adapt",
      fraction: 0.9,
      detail: "drafting 4 shards",
      at: "2026-07-29T12:00:00.000Z",
    });

    expect(next).toBe(current);
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
    current.stages.finish = stage("running", 8);

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_complete",
      stage: "finish",
      done: 8,
      total: 8,
    });

    expect(next?.stages.finish.status).toBe("complete");
    expect(next?.stages.finish.items_done).toBe(8);
  });

  it("marks Brief complete as awaiting review", () => {
    const current = status();
    current.stages.brief = stage("running", 4);

    const next = applyStageEventToProjectStatus(current, {
      type: "stage_complete",
      stage: "brief",
      done: 4,
      total: 4,
    });

    expect(next?.stages.brief.status).toBe("awaiting_review");
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
