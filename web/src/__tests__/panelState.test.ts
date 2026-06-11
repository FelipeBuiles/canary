import { describe, it, expect } from "vitest";
import { getPanelDisplayState, getPanelFilterBucket } from "../lib/panelState";

describe("getPanelDisplayState", () => {
  it("returns generating when regenMode=running or panel is in flight", () => {
    expect(getPanelDisplayState({ status: "pending", flagged: false }, { regenMode: "running" })).toBe("generating");
    expect(getPanelDisplayState({ status: "pending", flagged: false }, { inFlight: true })).toBe("generating");
    expect(getPanelDisplayState({ status: "done", flagged: false, version_count: 1 }, { inFlight: true })).toBe("generating");
  });

  it("activity wins over flag: a flagged panel mid-regen shows generating", () => {
    expect(getPanelDisplayState({ status: "done", flagged: true }, { inFlight: true })).toBe("generating");
    expect(getPanelDisplayState({ status: "done", flagged: true }, { regenMode: "queued" })).toBe("queued");
  });

  it("returns generating when retry-failed run is targeting this failed panel", () => {
    expect(getPanelDisplayState({ status: "failed", flagged: false }, { isRetryFailedRunning: true })).toBe("generating");
  });

  it("returns queued when regenMode=queued", () => {
    expect(getPanelDisplayState({ status: "pending", flagged: false }, { regenMode: "queued" })).toBe("queued");
  });

  it("returns queued when panel is in current run target but not yet in flight", () => {
    expect(getPanelDisplayState({ status: "pending", flagged: false }, { queuedInRun: true })).toBe("queued");
  });

  it("inFlight wins over queuedInRun (panel started)", () => {
    expect(
      getPanelDisplayState(
        { status: "pending", flagged: false },
        { queuedInRun: true, inFlight: true },
      ),
    ).toBe("generating");
  });

  it("returns failed when status=failed (no retry-failed run)", () => {
    expect(getPanelDisplayState({ status: "failed", flagged: false })).toBe("failed");
  });

  it("returns flagged when status=done and the user flagged it", () => {
    expect(getPanelDisplayState({ status: "done", flagged: true, version_count: 1 })).toBe("flagged");
    expect(getPanelDisplayState({ status: "done", flagged: true, version_count: 3 })).toBe("flagged");
  });

  it("returns generated when status=done, not flagged, version_count=1", () => {
    expect(getPanelDisplayState({ status: "done", flagged: false, version_count: 1 })).toBe("generated");
    expect(getPanelDisplayState({ status: "done", flagged: false })).toBe("generated");
  });

  it("returns regenerated when status=done, not flagged, version_count>1", () => {
    expect(getPanelDisplayState({ status: "done", flagged: false, version_count: 3 })).toBe("regenerated");
    expect(getPanelDisplayState({ status: "done", flagged: false, version_count: 2 })).toBe("regenerated");
  });

  it("returns pending for pending status without any active run", () => {
    expect(getPanelDisplayState({ status: "pending", flagged: false })).toBe("pending");
  });
});

describe("getPanelFilterBucket", () => {
  it("maps display states to filter buckets", () => {
    expect(getPanelFilterBucket("flagged")).toBe("flagged");
    expect(getPanelFilterBucket("generated")).toBe("generated");
    expect(getPanelFilterBucket("regenerated")).toBe("generated");
    expect(getPanelFilterBucket("failed")).toBe("failed");
    expect(getPanelFilterBucket("pending")).toBe("pending");
    expect(getPanelFilterBucket("queued")).toBe("pending");
    expect(getPanelFilterBucket("generating")).toBe("pending");
  });
});
