import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StageRunning } from "../components/composites/StagePlaceholder";
import { panelRows } from "../lib/planProgress";
import { applyStageEventToProjectStatus } from "../lib/pipelineStatusEvents";
import { I18nProvider } from "../i18n";
import type { PlanProgressSnapshot, ProjectStatus, StageInfo } from "../types/api";

function snapshot(overrides: Partial<PlanProgressSnapshot> = {}): PlanProgressSnapshot {
  const pages = Array.from({ length: 8 }, (_, index) => ({
    page: index + 1,
    emphasis: index === 5 ? "peak" : "initial",
    turn: index === 3 ? "reveal" : "none",
    spread: "single",
    density: "standard",
    beats: 2,
    panels: index < 4 ? 3 : null,
    lettering: 2,
  }));
  return {
    kind: "plan",
    phase: "laying_out",
    beats: 16,
    lettering_total: 16,
    target_pages: { min: 6, max: 10 },
    serial_transport: true,
    pages,
    batches: [
      { first: 1, last: 4, state: "done" },
      { first: 5, last: 6, state: "writing" },
      { first: 7, last: 8, state: "queued" },
    ],
    pages_laid_out: 4,
    panels: 12,
    lettering_placed: 8,
    ...overrides,
  };
}

describe("Plan progress board", () => {
  it("shows the validated book taking shape, not elapsed-time guesses", () => {
    render(<I18nProvider><StageRunning stage="plan" snapshot={snapshot()} /></I18nProvider>);

    expect(screen.getByText("Lay out panels").closest("li")?.getAttribute("aria-current")).toBe("step");
    expect(screen.getByText("8")).toBeTruthy();
    expect(screen.getByText("Target 6–10")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("4 of 8 pages laid out")).toBeTruthy();
    expect(screen.getByText("8/16")).toBeTruthy();
    const sheet = screen.getByRole("list", { name: "Page plan contact sheet" });
    const tiles = within(sheet).getAllByRole("listitem");
    expect(tiles).toHaveLength(8);
    expect(tiles[0].getAttribute("aria-label")).toBe("Page 1 · 3 panels");
    expect(tiles[3].getAttribute("aria-label")).toBe("Page 4 · 3 panels · Page-turn reveal");
    expect(tiles[5].getAttribute("aria-label")).toBe("Page 6 · 2 story beats · Peak moment");
    // Queued batches are waiting, not in flight, on a one-at-a-time model.
    expect(screen.getByText(/Writing pages 5–6\. 1 batch waiting\. This model writes one batch at a time/)).toBeTruthy();
    // The generic "results appear when the step finishes" copy is replaced.
    expect(screen.queryByText(/Results appear when the step finishes/)).toBeNull();
  });

  it("falls back to the generic running view before the first snapshot", () => {
    render(<I18nProvider><StageRunning stage="plan" /></I18nProvider>);
    expect(screen.getByText(/Results appear when the step finishes/)).toBeTruthy();
  });

  it("lays out plausible thumbnail rows for any panel count", () => {
    expect(panelRows(1)).toEqual([1]);
    expect(panelRows(5)).toEqual([2, 1, 2]);
    expect(panelRows(8)).toEqual([3, 3, 2]);
    for (let count = 1; count <= 12; count += 1) {
      expect(panelRows(count).reduce((sum, cells) => sum + cells, 0)).toBe(count);
    }
  });
});

describe("stage_snapshot events", () => {
  function plan(status: StageInfo["status"]): StageInfo {
    return {
      status, items_done: 1, items_total: 5, items_failed: [], approved: null,
      cost_credits: 0, estimated_cost_credits: 0, error: null, error_code: null,
      balance_credits: null, required_credits: null, shortfall_credits: null,
      started_at: null, finished_at: null, last_progress_at: null, stale: false, in_flight: [],
    };
  }
  const project = (info: StageInfo) => ({ stages: { plan: info }, is_running: true } as unknown as ProjectStatus);

  it("stores the snapshot without touching the stage lifecycle", () => {
    const next = applyStageEventToProjectStatus(project(plan("running")), {
      type: "stage_snapshot", stage: "plan", snapshot: snapshot(),
    });
    expect(next?.stages.plan).toMatchObject({ status: "running", items_done: 1, items_total: 5 });
    expect(next?.stages.plan.snapshot?.pages_laid_out).toBe(4);
  });

  it("clears a previous run's snapshot when the stage begins again", () => {
    const next = applyStageEventToProjectStatus(
      project({ ...plan("failed"), snapshot: snapshot() }),
      { type: "stage_begin", stage: "plan", total: 0 },
    );
    expect(next?.stages.plan.snapshot).toBeNull();
  });
});
