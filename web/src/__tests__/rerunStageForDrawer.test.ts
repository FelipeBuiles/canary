import { describe, it, expect } from "vitest";
import { rerunStageForDrawer, STATIONS, type DrawerKind } from "../lib/stations";
import { RERUN_IMPACT } from "../lib/rerunImpact";

const DRAWER_KINDS: DrawerKind[] = ["script", "shot-plan", "prompts"];

describe("rerunStageForDrawer", () => {
  it("maps each auto-step drawer to the first backend stage of its substep", () => {
    expect(rerunStageForDrawer("script")).toBe("adapt");
    expect(rerunStageForDrawer("shot-plan")).toBe("plan");
    expect(rerunStageForDrawer("prompts")).toBe("direct");
  });

  it("returns a stage that has a rerun-impact entry (so RerunStageAction can render)", () => {
    for (const kind of DRAWER_KINDS) {
      expect(RERUN_IMPACT[rerunStageForDrawer(kind)]).toBeDefined();
    }
  });

  it("covers every drawer kind declared in the stations config", () => {
    const declared = new Set(
      STATIONS.flatMap((s) => s.substeps).map((s) => s.drawer).filter(Boolean),
    );
    expect(new Set(DRAWER_KINDS)).toEqual(declared);
  });

  it("throws for an unknown drawer kind", () => {
    expect(() => rerunStageForDrawer("nope" as DrawerKind)).toThrow();
  });
});
