import { describe, it, expect, beforeEach } from "vitest";
import {
  useDrawProgressStore,
  computeThroughputPerMin,
  computeEtaSeconds,
  formatEta,
  formatRelative,
  type FinishRecord,
} from "../store/drawProgress";
import type { StageInfo } from "../types/api";

const PROJECT = "proj-1";

function emptyStage(): StageInfo {
  return {
    status: "running",
    items_done: 0,
    items_total: 10,
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

beforeEach(() => {
  useDrawProgressStore.setState({ byProject: {} });
});

describe("drawProgress store", () => {
  it("hydrates in-flight from a status payload", () => {
    const stage: StageInfo = {
      ...emptyStage(),
      in_flight: [
        { scene_id: "s_1", panel_number: 3, started_at: "2026-05-15T18:00:00Z" },
        { scene_id: "s_1", panel_number: 4, started_at: "2026-05-15T18:00:05Z" },
      ],
    };
    useDrawProgressStore.getState().hydrate(PROJECT, stage);
    const state = useDrawProgressStore.getState().byProject[PROJECT];
    expect(Object.keys(state.inFlight).sort()).toEqual(["s_1-3", "s_1-4"]);
  });

  it("preserves recentFinishes across hydrate (SSE may have arrived first)", () => {
    useDrawProgressStore
      .getState()
      .applyPanelDone(PROJECT, "s_1", 1, "ok", 5000, null);
    useDrawProgressStore.getState().hydrate(PROJECT, emptyStage());
    expect(useDrawProgressStore.getState().byProject[PROJECT].recentFinishes).toHaveLength(1);
  });

  it("applyPanelStart adds to in-flight; applyPanelDone removes it and pushes a finish", () => {
    const s = useDrawProgressStore.getState();
    s.applyPanelStart(PROJECT, "s_2", 7, new Date().toISOString());
    expect(useDrawProgressStore.getState().byProject[PROJECT].inFlight["s_2-7"]).toBeDefined();
    s.applyPanelDone(PROJECT, "s_2", 7, "ok", 12000, null);
    const next = useDrawProgressStore.getState().byProject[PROJECT];
    expect(next.inFlight["s_2-7"]).toBeUndefined();
    expect(next.recentFinishes[0].sceneId).toBe("s_2");
    expect(next.recentFinishes[0].status).toBe("ok");
  });

  it("recentFinishes is capped at 10 entries (newest first)", () => {
    const s = useDrawProgressStore.getState();
    for (let i = 1; i <= 15; i++) {
      s.applyPanelDone(PROJECT, "s_1", i, "ok", 1000, null);
    }
    const finishes = useDrawProgressStore.getState().byProject[PROJECT].recentFinishes;
    expect(finishes).toHaveLength(10);
    // Most recent = panel 15 should be first.
    expect(finishes[0].panelNumber).toBe(15);
  });

  it("clear() drops the project entry", () => {
    const s = useDrawProgressStore.getState();
    s.applyPanelStart(PROJECT, "s_1", 1, new Date().toISOString());
    s.clear(PROJECT);
    expect(useDrawProgressStore.getState().byProject[PROJECT]).toBeUndefined();
  });

  it("applyPanelStart is idempotent on duplicate events", () => {
    const s = useDrawProgressStore.getState();
    s.applyPanelStart(PROJECT, "s_1", 1, "2026-05-15T18:00:00Z");
    s.applyPanelStart(PROJECT, "s_1", 1, "2026-05-15T18:00:05Z");
    const inFlight = useDrawProgressStore.getState().byProject[PROJECT].inFlight;
    expect(Object.keys(inFlight)).toHaveLength(1);
  });
});

describe("throughput / ETA math", () => {
  function finish(at: number, status: "ok" | "failed" = "ok"): FinishRecord {
    return {
      sceneId: "s",
      panelNumber: 1,
      status,
      durationMs: 1000,
      finishedAt: at,
    };
  }

  it("returns null when fewer than 3 finishes in the last 60s", () => {
    const now = 100_000;
    expect(computeThroughputPerMin([finish(now - 10_000), finish(now - 5_000)], now)).toBeNull();
  });

  it("returns the count for a 60s window once enough samples are present", () => {
    const now = 100_000;
    const finishes = [
      finish(now - 1_000),
      finish(now - 5_000),
      finish(now - 30_000),
      finish(now - 70_000), // outside window — excluded
    ];
    expect(computeThroughputPerMin(finishes, now)).toBe(3);
  });

  it("computeEtaSeconds returns null when throughput is null", () => {
    expect(computeEtaSeconds(50, null)).toBeNull();
  });

  it("computeEtaSeconds returns 0 when nothing remaining", () => {
    expect(computeEtaSeconds(0, 5)).toBe(0);
  });

  it("computeEtaSeconds = remaining / throughput * 60", () => {
    expect(computeEtaSeconds(60, 4)).toBe(900); // 60 / 4 * 60 = 900s
  });

  it("formatEta formats seconds, minutes, hours", () => {
    expect(formatEta(null)).toBe("—");
    expect(formatEta(45)).toBe("45s");
    expect(formatEta(125)).toBe("2m");
    expect(formatEta(3700)).toBe("1h 2m");
  });

  it("formatRelative formats elapsed times", () => {
    const now = 100_000;
    expect(formatRelative(now - 5_000, now)).toBe("5s");
    expect(formatRelative(now - 90_000, now)).toBe("2m");
  });
});
