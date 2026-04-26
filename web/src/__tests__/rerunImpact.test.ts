import { describe, it, expect } from "vitest";
import {
  RERUN_IMPACT,
  type RerunStageKey,
} from "../lib/rerunImpact";
import { STAGE_ORDER } from "../types/api";

describe("RERUN_IMPACT", () => {
  it("has an entry for every pipeline stage", () => {
    for (const stage of STAGE_ORDER) {
      expect(RERUN_IMPACT[stage]).toBeDefined();
    }
  });

  it("has a style entry", () => {
    expect(RERUN_IMPACT["style"]).toBeDefined();
  });

  it("every entry has downstream and cost fields", () => {
    for (const [, impact] of Object.entries(RERUN_IMPACT)) {
      expect(Array.isArray(impact.downstream)).toBe(true);
      expect(typeof impact.cost).toBe("string");
      expect(typeof impact.costIsPlaceholder).toBe("boolean");
    }
  });

  it("costIsPlaceholder is true for all entries", () => {
    // All current entries are placeholder estimates
    for (const impact of Object.values(RERUN_IMPACT)) {
      expect(impact.costIsPlaceholder).toBe(true);
    }
  });

  it("extract has the most downstream stages (all 7 others)", () => {
    const extract = RERUN_IMPACT["extract"];
    expect(extract.downstream).toHaveLength(7);
    expect(extract.downstream).toContain("cast");
    expect(extract.downstream).toContain("compose");
  });

  it("compose has no downstream stages", () => {
    const compose = RERUN_IMPACT["compose"];
    expect(compose.downstream).toHaveLength(0);
  });

  it("downstream stages are in pipeline order (no cycles)", () => {
    // Each stage's downstream should only contain stages that come AFTER it in STAGE_ORDER.
    // This guarantees no cycles and correct ordering.
    for (const key of Object.keys(RERUN_IMPACT) as RerunStageKey[]) {
      const keyIndex = STAGE_ORDER.indexOf(key as any);
      for (const downstream of RERUN_IMPACT[key].downstream) {
        const downstreamIndex = STAGE_ORDER.indexOf(downstream as any);
        expect(downstreamIndex).toBeGreaterThan(keyIndex);
      }
    }
  });

  it("draw downstream contains only compose", () => {
    const draw = RERUN_IMPACT["draw"];
    expect(draw.downstream).toEqual(["compose"]);
  });

  it("direct downstream contains draw and compose", () => {
    const direct = RERUN_IMPACT["direct"];
    expect(direct.downstream).toContain("draw");
    expect(direct.downstream).toContain("compose");
    expect(direct.downstream.indexOf("draw")).toBeLessThan(
      direct.downstream.indexOf("compose")
    );
  });

  it("style has the same downstream as extract", () => {
    const style = RERUN_IMPACT["style"];
    const extract = RERUN_IMPACT["extract"];
    expect(style.downstream).toEqual(extract.downstream);
  });

  it("cost strings are non-empty", () => {
    for (const [, impact] of Object.entries(RERUN_IMPACT)) {
      expect(impact.cost.length).toBeGreaterThan(0);
    }
  });
});
