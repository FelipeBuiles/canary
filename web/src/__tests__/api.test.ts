import { describe, it, expect } from "vitest";
import {
  STAGE_ORDER,
  STAGE_DISPLAY_NAMES,
} from "../types/api";
import { BACKEND_STAGE_TO_UI_ROUTE, UI_STAGES } from "../lib/uiStages";

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

describe("UI_STAGES", () => {
  it("contains one user-facing shot plan stage and no plan/storyboard UI stages", () => {
    const keys = UI_STAGES.map((stage) => stage.key);
    expect(keys.filter((key) => key === "shot-plan")).toHaveLength(1);
    expect(keys).not.toContain("plan");
    expect(keys).not.toContain("storyboard");
  });

  it("maps plan and storyboard backend stages to the shot plan route", () => {
    expect(BACKEND_STAGE_TO_UI_ROUTE.plan).toBe("shot-plan");
    expect(BACKEND_STAGE_TO_UI_ROUTE.storyboard).toBe("shot-plan");
  });

  it("uses product vocabulary for visible stages", () => {
    expect(UI_STAGES.map((stage) => stage.label)).toEqual([
      "Extract",
      "Look & Feel",
      "Cast & Places",
      "Script",
      "Shot Plan",
      "Prompt Review",
      "Generate Panels",
      "Letter & Compose",
    ]);
  });
});
