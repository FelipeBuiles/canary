import { describe, expect, it } from "vitest";
import { getCastCheckpointAction } from "../lib/castCheckpoint";

describe("getCastCheckpointAction", () => {
  it("resumes a failed cast instead of navigating to Panels", () => {
    expect(getCastCheckpointAction("failed")).toBe("resume");
  });

  it("only advances after approval or completion", () => {
    expect(getCastCheckpointAction("awaiting_review")).toBe("approve");
    expect(getCastCheckpointAction("complete")).toBe("continue");
    expect(getCastCheckpointAction("pending")).toBe("wait");
    expect(getCastCheckpointAction("running")).toBe("wait");
  });
});

it.each(["awaiting_review", "complete"] as const)("resumes %s when the server reports an approval blocker", (status) => {
  expect(getCastCheckpointAction(status, "Resume Cast to finish missing references")).toBe("resume");
});
