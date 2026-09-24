import { describe, expect, it } from "vitest";
import { readableAnchor } from "../lib/visualAnchor";

describe("readableAnchor", () => {
  it("reads a character tag list as a sentence without subject-count tags", () => {
    expect(readableAnchor("1man, adult male, 27 years old, short hair, heavy leather jacket"))
      .toBe("Adult male, 27 years old, short hair, heavy leather jacket.");
    expect(readableAnchor("1cat, tortoiseshell persian cat, flat face")).toBe("Tortoiseshell persian cat, flat face.");
    expect(readableAnchor("1male rat-like humanoid, beard")).toBe("Male rat-like humanoid, beard.");
  });

  it("keeps eras, ages, and dimensions that only look like counts", () => {
    expect(readableAnchor("1man, adult male, 70s, tall weathered build")).toBe("Adult male, 70s, tall weathered build.");
    expect(readableAnchor("1920s private study, 3d globe, oak desk")).toBe("1920s private study, 3d globe, oak desk.");
  });

  it("reads place tags as a sentence and drops repeated tags", () => {
    expect(readableAnchor("interior, house hallway, stairway, Stairway,  , downstairs"))
      .toBe("Interior, house hallway, stairway, downstairs.");
  });

  it("leaves prose anchors and empty values as written", () => {
    const prose = "A bulky, heavy-canvas spacesuit sized for a very small wearer. Held by its collar.";
    expect(readableAnchor(prose)).toBe(prose);
    expect(readableAnchor("  ")).toBe("");
    expect(readableAnchor(null)).toBe("");
    expect(readableAnchor("1person")).toBe("");
  });
});
