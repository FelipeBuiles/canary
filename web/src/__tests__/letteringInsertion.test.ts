import { describe, expect, it } from "vitest";
import { alignChars, alignLettering } from "../components/pages/lettering";
describe("alignLettering insertions", () => {
  it("reads a leading addition as one insertion beside unchanged lines", () => {
    const rows = alignLettering(["A", "B"], ["X", "A", "B"]);
    expect(rows).toEqual([
      { type: "extra", recognized: "X" },
      { type: "same", expected: "A", recognized: "A" },
      { type: "same", expected: "B", recognized: "B" },
    ]);
  });
  it("keeps one copy of duplicated text and marks only the surplus", () => {
    expect(alignLettering(["A", "A"], ["A"]).map((row) => row.type)).toEqual([
      "same",
      "missing",
    ]);
    expect(alignLettering(["A"], ["A", "A"]).map((row) => row.type)).toEqual([
      "same",
      "extra",
    ]);
    const surplus = alignLettering(["A", "A"], ["A"]);
    expect(surplus.some((row) => row.type === "moved")).toBe(false);
    expect(surplus.find((row) => row.type === "missing")?.expected).toBe("A");
  });
  it("aligns Unicode segments without splitting characters", () => {
    expect(alignLettering(["café 🎉", "B"], ["café 🎉", "B"]).every((row) => row.type === "same")).toBe(true);
    const [only] = alignLettering(["naïve 🎉"], ["naïve 🎊"]);
    expect(only?.type).toBe("changed");
    expect(only?.expected).toBe("naïve 🎉");
    expect(only?.recognized).toBe("naïve 🎊");
    const hunks = alignChars("a🎉b", "a🎊b");
    expect(hunks.map((hunk) => hunk.type)).toEqual(["same", "changed", "same"]);
    const changed = hunks[1]!;
    expect(changed.expected).toBe("🎉");
    expect(changed.recognized).toBe("🎊");
    expect(Array.from(changed.expected)).toHaveLength(1);
  });
});
