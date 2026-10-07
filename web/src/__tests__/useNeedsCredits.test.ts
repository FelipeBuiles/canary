// @vitest-environment jsdom

import { renderHook } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import type { ProjectStatus, StageInfo } from "../types/api";

// Mutable fixtures the mocked hooks read from. Tests set these before
// rendering the hook.
let statusFixture: ProjectStatus | undefined;
let balanceFixture: number;
let estimateFixture: { estimate_credits: number } | undefined;

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({ data: statusFixture }),
  useCreditBalance: () => ({ data: { balance_credits: balanceFixture } }),
  useStageEstimate: () => ({ data: estimateFixture }),
}));

import { useNeedsCredits } from "../hooks/useNeedsCredits";

function stage(overrides: Partial<StageInfo> = {}): StageInfo {
  return {
    status: "pending",
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

function status(stages: Record<string, StageInfo>): ProjectStatus {
  return {
    id: "p",
    project_name: "p",
    created_at: "2026-07-06T00:00:00Z",
    total_cost_credits: 0,
    misc_cost_credits: 0,
    total_estimated_cost_credits: 0,
    is_running: false, part_busy: false, series_busy: false,
    has_cover: false,
    style_selected: true,
    is_public: false,
    share_token: null,
    stages,
  };
}

beforeEach(() => {
  statusFixture = undefined;
  balanceFixture = 0;
  estimateFixture = undefined;
});

describe("useNeedsCredits", () => {
  it("blocks on a persisted credit failure (survives reload)", () => {
    statusFixture = status({
      extract: stage({
        status: "failed",
        error_code: "insufficient_credits",
        required_credits: 100,
        shortfall_credits: 100,
        balance_credits: 0,
      }),
    });
    balanceFixture = 0;
    const { result } = renderHook(() => useNeedsCredits("p", "extract"));
    expect(result.current).toMatchObject({
      blocked: true,
      reason: "persisted",
      required: 100,
      shortfall: 100,
      balance: 0,
    });
  });

  it("uses the live balance for the Balance column even when persisted balance is stale", () => {
    statusFixture = status({
      extract: stage({
        status: "failed",
        error_code: "insufficient_credits",
        required_credits: 100,
        balance_credits: 0, // persisted snapshot was 0
      }),
    });
    balanceFixture = 50; // but they've since topped up to 50
    const { result } = renderHook(() => useNeedsCredits("p", "extract"));
    expect(result.current).toMatchObject({
      blocked: true,
      balance: 50,
      required: 100,
      shortfall: 50,
    });
  });

  it("blocks heuristically when pending, estimate > 0, and balance below it", () => {
    statusFixture = status({
      extract: stage({ status: "pending" }),
    });
    estimateFixture = { estimate_credits: 120 };
    balanceFixture = 10;
    const { result } = renderHook(() => useNeedsCredits("p", "extract"));
    expect(result.current).toMatchObject({
      blocked: true,
      reason: "heuristic",
      required: 120,
      balance: 10,
      shortfall: 110,
    });
  });

  it("blocks heuristically on a non-credit failed stage (retrying costs credits)", () => {
    statusFixture = status({
      cast: stage({
        status: "failed",
        error_code: null,
      }),
    });
    estimateFixture = { estimate_credits: 200 };
    balanceFixture = 5;
    const { result } = renderHook(() => useNeedsCredits("p", "cast"));
    expect(result.current).toMatchObject({ blocked: true, reason: "heuristic" });
  });

  it("does not block when estimate is 0 (free stage)", () => {
    statusFixture = status({
      adapt: stage({ status: "pending" }),
    });
    estimateFixture = { estimate_credits: 0 };
    balanceFixture = 0;
    const { result } = renderHook(() => useNeedsCredits("p", "adapt"));
    expect(result.current).toEqual({ blocked: false });
  });

  it("does not block on awaiting_review", () => {
    statusFixture = status({
      extract: stage({ status: "awaiting_review", estimated_cost_credits: 100 }),
    });
    balanceFixture = 0;
    const { result } = renderHook(() => useNeedsCredits("p", "extract"));
    expect(result.current).toEqual({ blocked: false });
  });

  it("does not block on complete", () => {
    statusFixture = status({
      extract: stage({ status: "complete", estimated_cost_credits: 100 }),
    });
    balanceFixture = 0;
    const { result } = renderHook(() => useNeedsCredits("p", "extract"));
    expect(result.current).toEqual({ blocked: false });
  });

  it("does not block when balance covers the estimate", () => {
    statusFixture = status({
      extract: stage({ status: "pending" }),
    });
    estimateFixture = { estimate_credits: 100 };
    balanceFixture = 150;
    const { result } = renderHook(() => useNeedsCredits("p", "extract"));
    expect(result.current).toEqual({ blocked: false });
  });

  it("returns not-blocked while status is loading", () => {
    statusFixture = undefined;
    const { result } = renderHook(() => useNeedsCredits("p", "extract"));
    expect(result.current).toEqual({ blocked: false });
  });
});
