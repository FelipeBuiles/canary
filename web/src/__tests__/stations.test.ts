import { describe, expect, it } from "vitest";
import { STATIONS, stationDestination } from "../lib/stations";
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

function projectStatus(stages: ProjectStatus["stages"]): ProjectStatus {
  return {
    id: "project",
    project_name: "Project",
    created_at: "2026-07-09T00:00:00Z",
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

describe("stationDestination", () => {
  const look = STATIONS.find((station) => station.key === "look")!;

  it("opens the style decision while it needs review", () => {
    const status = projectStatus({
      style: stage("awaiting_review"),
      cast: stage("pending"),
    });

    expect(stationDestination(look, status)).toBe("styles");
  });

  it("advances the station link to cast after style is complete", () => {
    const status = projectStatus({
      style: stage("complete"),
      cast: stage("awaiting_review"),
    });

    expect(stationDestination(look, status)).toBe("cast");
  });

  it("returns to the station's primary room after every decision is complete", () => {
    const status = projectStatus({
      style: stage("complete"),
      cast: stage("complete"),
    });

    expect(stationDestination(look, status)).toBe("styles");
  });
});
