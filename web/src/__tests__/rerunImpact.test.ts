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

  it("every entry has a downstream field", () => {
    for (const [, impact] of Object.entries(RERUN_IMPACT)) {
      expect(Array.isArray(impact.downstream)).toBe(true);
    }
  });

  it("extract has all seven downstream stages", () => {
    const extract = RERUN_IMPACT["extract"];
    expect(extract.downstream).toHaveLength(7);
    expect(extract.downstream).toContain("cast");
    expect(extract.downstream).toContain("finish");
  });

  it("finish has no downstream stages", () => {
    expect(RERUN_IMPACT.finish.downstream).toHaveLength(0);
  });

  it("downstream stages are in pipeline order (no cycles)", () => {
    // Each stage's downstream should only contain stages that come AFTER it in STAGE_ORDER.
    // This guarantees no cycles and correct ordering.
    for (const key of Object.keys(RERUN_IMPACT) as RerunStageKey[]) {
      const keyIndex = STAGE_ORDER.indexOf(key);
      for (const downstream of RERUN_IMPACT[key].downstream) {
        const downstreamIndex = STAGE_ORDER.indexOf(downstream);
        expect(downstreamIndex).toBeGreaterThan(keyIndex);
      }
    }
  });

  it("draw downstream contains only finish", () => {
    expect(RERUN_IMPACT.draw.downstream).toEqual(["finish"]);
  });

  it("Brief invalidates every stage that derives from it", () => {
    expect(RERUN_IMPACT.brief.downstream).toEqual([
      "style", "cast", "adapt", "plan", "draw", "finish",
    ]);
  });

});
