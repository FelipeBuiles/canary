import { describe, it, expect } from "vitest";
import {
  STAGE_ORDER,
  STAGE_DISPLAY_NAMES,
} from "../types/api";
import { BACKEND_STAGE_TO_UI_ROUTE, UI_STAGES } from "../lib/uiStages";

describe("STAGE_ORDER", () => {
  it("contains the eight page-generation stages in order", () => {
    expect(STAGE_ORDER).toEqual([
      "extract", "brief", "style", "cast", "adapt", "plan", "draw", "finish",
    ]);
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

  it("finish maps to FINISH", () => {
    expect(STAGE_DISPLAY_NAMES.finish).toBe("FINISH");
  });
});

describe("UI_STAGES", () => {
  it("contains only the four target stations", () => {
    expect(UI_STAGES.map((stage) => stage.key)).toEqual(["story", "look", "pages", "book"]);
  });

  it("maps automatic page work to Pages", () => {
    expect(BACKEND_STAGE_TO_UI_ROUTE.adapt).toBe("pages");
    expect(BACKEND_STAGE_TO_UI_ROUTE.plan).toBe("pages");
    expect(BACKEND_STAGE_TO_UI_ROUTE.draw).toBe("pages");
  });

  it("uses target product vocabulary", () => {
    expect(UI_STAGES.map((stage) => stage.label)).toEqual([
      "Story",
      "Look",
      "Pages",
      "Book",
    ]);
  });
});
