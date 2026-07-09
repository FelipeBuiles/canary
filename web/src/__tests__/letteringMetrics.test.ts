import { describe, expect, it } from "vitest";

import { classifyLetteringMetrics } from "../lib/letteringMetrics";

describe("classifyLetteringMetrics", () => {
  const base = {
    pageNumber: 1,
    panelId: "scene_001-001",
    panelNumber: 1,
    coverageRatio: 0.12,
    maxAutoStackRatio: 0.18,
    overflowingBubbleIds: [],
  };

  it("warns when lettering approaches the art coverage limit", () => {
    expect(classifyLetteringMetrics([{ ...base, coverageRatio: 0.25 }])).toMatchObject([
      { type: "lettering_obscures_art", severity: "warning" },
    ]);
  });

  it("reports clipping and an oversized automatic stack as errors", () => {
    const issues = classifyLetteringMetrics([
      {
        ...base,
        maxAutoStackRatio: 0.41,
        overflowingBubbleIds: ["scene_001-p1-b0"],
      },
    ]);

    expect(issues.map((issue) => issue.type)).toEqual([
      "lettering_overflow",
      "lettering_stack_too_tall",
    ]);
    expect(issues.every((issue) => issue.severity === "error")).toBe(true);
  });
});
