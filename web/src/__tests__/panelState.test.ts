import { describe, it, expect } from "vitest";
import { getPanelDisplayState } from "../lib/panelState";

describe("getPanelDisplayState", () => {
  it("returns accepted when accepted=true regardless of version count", () => {
    expect(getPanelDisplayState({ status: "done", accepted: true, version_count: 1 }, null, false)).toBe("accepted");
    expect(getPanelDisplayState({ status: "done", accepted: true, version_count: 3 }, null, false)).toBe("accepted");
    expect(getPanelDisplayState({ status: "failed", accepted: true }, null, false)).toBe("accepted");
  });

  it("returns generating when regenMode is queued or running", () => {
    expect(getPanelDisplayState({ status: "pending", accepted: false }, "queued", false)).toBe("generating");
    expect(getPanelDisplayState({ status: "pending", accepted: false }, "running", false)).toBe("generating");
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 1 }, "running", false)).toBe("generating");
  });

  it("returns failed when status=failed and not accepted", () => {
    expect(getPanelDisplayState({ status: "failed", accepted: false }, null, false)).toBe("failed");
  });

  it("returns stale when status=stale", () => {
    expect(getPanelDisplayState({ status: "stale", accepted: false }, null, false)).toBe("stale");
  });

  it("returns generating when draw stage is running and status=pending", () => {
    expect(getPanelDisplayState({ status: "pending", accepted: false }, null, true)).toBe("generating");
  });

  it("returns generated when status=done, not accepted, version_count=1", () => {
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 1 }, null, false)).toBe("generated");
    expect(getPanelDisplayState({ status: "done", accepted: false }, null, false)).toBe("generated");
  });

  it("returns regenerated when status=done, not accepted, version_count>1", () => {
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 3 }, null, false)).toBe("regenerated");
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 2 }, null, false)).toBe("regenerated");
  });

  it("returns pending for pending status without draw running", () => {
    expect(getPanelDisplayState({ status: "pending", accepted: false }, null, false)).toBe("pending");
  });

  it("regenMode takes priority over accepted=false done status", () => {
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 1 }, "queued", false)).toBe("generating");
  });
});
