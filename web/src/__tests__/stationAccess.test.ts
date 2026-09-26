import { describe, expect, it } from "vitest";
import { accessibleRoom, getRoomAccess } from "../lib/stationAccess";
import { STAGE_ORDER, type ProjectStatus } from "../types/api";

export function readyProject(): ProjectStatus {
  return {
    style_selected: true, page_count: 3,
    stages: Object.fromEntries(STAGE_ORDER.map((stage) => [stage, {
      status: "complete", approved: true, stale: false,
    }])),
  } as ProjectStatus;
}

describe("station access prerequisites", () => {
  it("fails closed before status loads while keeping settings reachable", () => {
    expect(getRoomAccess("pages", undefined).state).toBe("loading");
    expect(getRoomAccess("settings", undefined).state).toBe("available");
  });

  it.each(["styles", "cast", "pages", "book"])("blocks %s at the earliest unmet prerequisite even with downstream artifacts", (route) => {
    const status = readyProject();
    status.stages.brief.status = "awaiting_review";
    expect(getRoomAccess(route, status)).toMatchObject({ state: "locked", route: "story" });
    expect(accessibleRoom(route, status)).toBe("story");
  });

  it("requires explicit approval and selected style rather than a completed label", () => {
    const status = readyProject();
    status.stages.cast.approved = false;
    expect(getRoomAccess("pages", status)).toMatchObject({ state: "locked", route: "cast" });
    status.style_selected = false;
    expect(getRoomAccess("cast", status)).toMatchObject({ state: "locked", route: "styles" });
    expect(getRoomAccess("styles", status).state).toBe("available");
  });

  it.each(["pending", "running", "failed", "awaiting_review"] as const)("keeps Pages accessible during %s page production and blocks Book", (state) => {
    const status = readyProject();
    status.stages.adapt.status = state;
    expect(getRoomAccess("pages", status).state).toBe("available");
    expect(getRoomAccess("book", status)).toMatchObject({ state: "locked", route: "pages" });
  });

  it("relocks after upstream invalidation or an approval blocker", () => {
    const status = readyProject();
    status.stages.cast.stale = true;
    expect(getRoomAccess("pages", status).state).toBe("locked");
    status.stages.cast.stale = false;
    status.stages.cast.approval_blocker = "Missing reference";
    expect(getRoomAccess("pages", status).state).toBe("locked");
    delete status.stages.cast;
    expect(getRoomAccess("pages", status).state).toBe("locked");
  });

  it("requires approved, nonempty pages but allows Book preflight to fail", () => {
    const status = readyProject();
    status.stages.draw.status = "awaiting_review";
    expect(getRoomAccess("book", status).state).toBe("locked");
    status.stages.draw.status = "complete";
    status.page_count = 0;
    expect(getRoomAccess("book", status).state).toBe("locked");
    status.page_count = 3;
    status.finish_ready = false;
    status.stages.finish.status = "failed";
    expect(getRoomAccess("book", status).state).toBe("available");
  });
});
