import { describe, expect, it } from "vitest";
import { reconcileStatusPoll } from "../lib/stageProgress";
import type { ProjectStatus, StageInfo, StageStatus } from "../types/api";

function stage(status: StageStatus, done = 0, total = 0): StageInfo {
  return {
    status,
    items_done: done,
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

function status(stages: Record<string, StageInfo>, is_running = true): ProjectStatus {
  return {
    id: "project",
    project_name: "Project",
    created_at: "2026-06-01T00:00:00Z",
    total_cost_credits: 0,
    misc_cost_credits: 0,
    total_estimated_cost_credits: 0,
    is_running,
    style_selected: true,
    stages,
  } as ProjectStatus;
}

describe("reconcileStatusPoll", () => {
  it("returns the fresh status when nothing is cached", () => {
    const fresh = status({ draw: stage("running", 3, 10) });
    expect(reconcileStatusPoll(undefined, fresh)).toBe(fresh);
  });

  it("does not let a stale poll regress counters SSE already advanced", () => {
    const cached = status({ draw: stage("running", 7, 10) });
    const fresh = status({ draw: stage("running", 5, 10) });
    const merged = reconcileStatusPoll(cached, fresh);
    expect(merged.stages.draw.items_done).toBe(7);
    expect(merged.stages.draw.items_total).toBe(10);
  });

  it("keeps the larger items_total when SSE saw more items than the poll", () => {
    const cached = status({ draw: stage("running", 8, 12) });
    const fresh = status({ draw: stage("running", 5, 10) });
    const merged = reconcileStatusPoll(cached, fresh);
    expect(merged.stages.draw.items_total).toBe(12);
  });

  it("accepts the poll when it is ahead of the cache", () => {
    const cached = status({ draw: stage("running", 3, 10) });
    const fresh = status({ draw: stage("running", 6, 10) });
    const merged = reconcileStatusPoll(cached, fresh);
    expect(merged.stages.draw.items_done).toBe(6);
  });

  it("never holds counters back once the stage stops running", () => {
    const cached = status({ draw: stage("running", 9, 10) });
    const fresh = status({ draw: stage("awaiting_review", 8, 10) }, false);
    const merged = reconcileStatusPoll(cached, fresh);
    // A terminal status is authoritative — the poll wins outright.
    expect(merged.stages.draw.items_done).toBe(8);
    expect(merged.stages.draw.status).toBe("awaiting_review");
  });
});
