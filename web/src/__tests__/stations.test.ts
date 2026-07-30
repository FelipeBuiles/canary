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

describe("target station contract", () => {
  it("exposes only Story, Look, Pages, and Book", () => {
    expect(STATIONS.map(({ key, label, primaryRoute }) => ({
      key,
      label,
      primaryRoute,
    }))).toEqual([
      { key: "story", label: "Story", primaryRoute: "story" },
      { key: "look", label: "Look", primaryRoute: "styles" },
      { key: "pages", label: "Pages", primaryRoute: "pages" },
      { key: "book", label: "Book", primaryRoute: "book" },
    ]);
  });

  it("makes Brief the Story decision and keeps Adapt and Plan inspectable in Pages", () => {
    const story = STATIONS.find((station) => station.key === "story")!;
    const pages = STATIONS.find((station) => station.key === "pages")!;

    expect(story.substeps).toEqual([
      expect.objectContaining({
        key: "brief",
        kind: "gated",
        backendStages: ["extract", "brief"],
        route: "story",
      }),
    ]);
    expect(pages.substeps).toEqual([
      expect.objectContaining({ key: "adapt", kind: "auto", backendStages: ["adapt"] }),
      expect.objectContaining({ key: "plan", kind: "auto", backendStages: ["plan"] }),
      expect.objectContaining({ key: "draw", kind: "gated", backendStages: ["draw"], route: "pages" }),
    ]);
  });
});

describe("getStationState", () => {
  it("keeps Story in review when a draft brief reopens after Look completed", async () => {
    const { getStationState } = await import("../lib/stations");
    const story = STATIONS.find((station) => station.key === "story")!;
    const status = projectStatus({
      extract: stage("complete"),
      brief: stage("awaiting_review"),
      style: stage("complete"),
      cast: stage("complete"),
      adapt: stage("pending"),
    });

    expect(getStationState(story, status)).toBe("review");
  });

  it("shows running when an active stage follows an earlier failure", async () => {
    const { getStationState } = await import("../lib/stations");
    const pages = STATIONS.find((station) => station.key === "pages")!;
    const status = projectStatus({
      plan: stage("failed"),
      draw: stage("running"),
    });

    expect(getStationState(pages, status)).toBe("running");
  });

  it("still shows failed when no stage is running", async () => {
    const { getStationState } = await import("../lib/stations");
    const look = STATIONS.find((station) => station.key === "look")!;
    const status = projectStatus({
      style: stage("failed"),
      cast: stage("pending"),
    });

    expect(getStationState(look, status)).toBe("failed");
  });

  it("does not keep Look failed after cast has progressed", async () => {
    const { getStationState } = await import("../lib/stations");
    const look = STATIONS.find((station) => station.key === "look")!;
    const status = projectStatus({
      style: stage("failed"),
      cast: stage("complete"),
    });

    expect(getStationState(look, status)).toBe("done");
  });
});
