import { describe, it, expect } from "vitest";
import {
  STAGE_ORDER,
  STAGE_DISPLAY_NAMES,
  STAGE_ROUTES,
  ROUTE_TO_STAGE,
} from "../types/api";

describe("STAGE_ORDER", () => {
  it("contains exactly 8 stages in order", () => {
    expect(STAGE_ORDER).toHaveLength(8);
    expect(STAGE_ORDER[0]).toBe("extract");
    expect(STAGE_ORDER[STAGE_ORDER.length - 1]).toBe("compose");
  });

  it("matches STAGE_DISPLAY_NAMES keys", () => {
    const displayKeys = new Set(Object.keys(STAGE_DISPLAY_NAMES));
    expect(new Set(STAGE_ORDER)).toEqual(displayKeys);
  });
});

describe("STAGE_DISPLAY_NAMES", () => {
  it("every stage has a non-empty display name", () => {
    for (const stage of STAGE_ORDER) {
      expect(STAGE_DISPLAY_NAMES[stage].length).toBeGreaterThan(0);
    }
  });

  it("extract maps to EXTRACT", () => {
    expect(STAGE_DISPLAY_NAMES.extract).toBe("EXTRACT");
  });

  it("compose maps to COMPOSE", () => {
    expect(STAGE_DISPLAY_NAMES.compose).toBe("COMPOSE");
  });
});

describe("STAGE_ROUTES", () => {
  it("every stage route equals the stage name", () => {
    for (const stage of STAGE_ORDER) {
      expect(STAGE_ROUTES[stage]).toBe(stage);
    }
  });

  it("every route maps back to the same stage via ROUTE_TO_STAGE", () => {
    for (const stage of STAGE_ORDER) {
      expect(ROUTE_TO_STAGE[stage]).toBe(stage);
    }
  });
});

describe("ROUTE_TO_STAGE", () => {
  it("has exactly 8 entries", () => {
    expect(Object.keys(ROUTE_TO_STAGE)).toHaveLength(8);
  });

  it("round-trips through STAGE_ROUTES", () => {
    const reversed: Record<string, string> = {};
    for (const [stage, route] of Object.entries(STAGE_ROUTES)) {
      reversed[route] = stage;
    }
    expect(reversed).toEqual(ROUTE_TO_STAGE);
  });
});
