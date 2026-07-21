import { describe, expect, it } from "vitest";
import { speechTailGeometry, thoughtTailDots } from "../components/compose/tailPath";

describe("speaker tail geometry", () => {
  it("lands the curved speech tail on the exact panel-relative target without a stroked base seam", () => {
    const geometry = speechTailGeometry(240, 120, 420, 360);

    expect(geometry.fillPath).toContain("420 360");
    expect(geometry.fillPath.endsWith("Z")).toBe(true);
    expect(geometry.outlinePath).toContain("420 360");
    expect(geometry.outlinePath.endsWith("Z")).toBe(false);
  });

  it("ends the thought indicator at the requested speaker target", () => {
    const dots = thoughtTailDots(240, 120, 420, 360);

    expect(dots).toHaveLength(4);
    expect(dots[0].radius).toBeGreaterThan(dots[3].radius);
    expect(dots[3].cx).toBeCloseTo(417.9, 1);
    expect(dots[3].cy).toBeCloseTo(357.9, 1);
  });
});
