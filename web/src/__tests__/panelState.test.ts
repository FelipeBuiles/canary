import { describe, it, expect } from "vitest";
import { getPanelDisplayState } from "../lib/panelState";

describe("getPanelDisplayState", () => {
  it("returns accepted when accepted=true regardless of version count or in-flight", () => {
    expect(getPanelDisplayState({ status: "done", accepted: true, version_count: 1 })).toBe("accepted");
    expect(getPanelDisplayState({ status: "done", accepted: true, version_count: 3 })).toBe("accepted");
    expect(getPanelDisplayState({ status: "failed", accepted: true })).toBe("accepted");
    expect(getPanelDisplayState({ status: "pending", accepted: true }, { inFlight: true })).toBe("accepted");
  });

  it("returns generating when regenMode=running or panel is in flight", () => {
    expect(getPanelDisplayState({ status: "pending", accepted: false }, { regenMode: "running" })).toBe("generating");
    expect(getPanelDisplayState({ status: "pending", accepted: false }, { inFlight: true })).toBe("generating");
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 1 }, { inFlight: true })).toBe("generating");
  });

  it("returns generating when retry-failed run is targeting this failed panel", () => {
    expect(getPanelDisplayState({ status: "failed", accepted: false }, { isRetryFailedRunning: true })).toBe("generating");
  });

  it("returns queued when regenMode=queued", () => {
    expect(getPanelDisplayState({ status: "pending", accepted: false }, { regenMode: "queued" })).toBe("queued");
  });

  it("returns queued when panel is in current run target but not yet in flight", () => {
    expect(getPanelDisplayState({ status: "pending", accepted: false }, { queuedInRun: true })).toBe("queued");
  });

  it("inFlight wins over queuedInRun (panel started)", () => {
    expect(
      getPanelDisplayState(
        { status: "pending", accepted: false },
        { queuedInRun: true, inFlight: true },
      ),
    ).toBe("generating");
  });

  it("returns failed when status=failed and not accepted (no retry-failed run)", () => {
    expect(getPanelDisplayState({ status: "failed", accepted: false })).toBe("failed");
  });

  it("returns generated when status=done, not accepted, version_count=1", () => {
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 1 })).toBe("generated");
    expect(getPanelDisplayState({ status: "done", accepted: false })).toBe("generated");
  });

  it("returns regenerated when status=done, not accepted, version_count>1", () => {
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 3 })).toBe("regenerated");
    expect(getPanelDisplayState({ status: "done", accepted: false, version_count: 2 })).toBe("regenerated");
  });

  it("returns pending for pending status without any active run", () => {
    expect(getPanelDisplayState({ status: "pending", accepted: false })).toBe("pending");
  });
});
