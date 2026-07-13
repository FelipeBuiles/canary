import { describe, expect, it } from "vitest";
import { pinnedTailPath } from "../components/compose/tailPath";

describe("pinnedTailPath", () => {
  it("lands the curved tail on the exact panel-relative target", () => {
    const path = pinnedTailPath(240, 120, 420, 360);

    expect(path).toContain("420 360");
    expect(path).toContain("110.4");
    expect(path).not.toContain(" 120 Q");
    expect(path.endsWith("Z")).toBe(true);
  });
});
