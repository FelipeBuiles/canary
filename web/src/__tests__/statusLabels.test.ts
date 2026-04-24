import { describe, it, expect } from "vitest";
import {
  STATUS_PRESENTATION,
  statusLabel,
  statusTone,
} from "../lib/statusLabels";
import type { StageStatus } from "../types/api";

describe("STATUS_PRESENTATION", () => {
  const statuses: StageStatus[] = [
    "pending",
    "running",
    "awaiting_review",
    "complete",
    "failed",
  ];

  it("covers every StageStatus", () => {
    expect(statuses.every((s) => s in STATUS_PRESENTATION)).toBe(true);
  });

  it("pending has neutral tone and circle icon", () => {
    const p = STATUS_PRESENTATION.pending;
    expect(p.tone).toBe("neutral");
    expect(p.icon).toBe("circle");
    expect(p.label.length).toBeLessThanOrEqual(8);
  });

  it("running has gold tone and loader icon", () => {
    const p = STATUS_PRESENTATION.running;
    expect(p.tone).toBe("gold");
    expect(p.icon).toBe("loader");
  });

  it("awaiting_review has red tone and alert icon", () => {
    const p = STATUS_PRESENTATION.awaiting_review;
    expect(p.tone).toBe("red");
    expect(p.icon).toBe("alert");
  });

  it("complete has sage tone and check icon", () => {
    const p = STATUS_PRESENTATION.complete;
    expect(p.tone).toBe("sage");
    expect(p.icon).toBe("check");
  });

  it("failed has red tone and alert icon", () => {
    const p = STATUS_PRESENTATION.failed;
    expect(p.tone).toBe("red");
    expect(p.icon).toBe("alert");
  });

  it("all labels are ≤ 8 characters", () => {
    for (const s of statuses) {
      expect(STATUS_PRESENTATION[s].label.length).toBeLessThanOrEqual(8);
    }
  });

  it("all descriptions are non-empty", () => {
    for (const s of statuses) {
      expect(STATUS_PRESENTATION[s].description.length).toBeGreaterThan(0);
    }
  });
});

describe("statusLabel", () => {
  it("returns label for each status", () => {
    expect(statusLabel("pending")).toBe("WAITING");
    expect(statusLabel("running")).toBe("RUNNING");
    expect(statusLabel("awaiting_review")).toBe("REVIEW");
    expect(statusLabel("complete")).toBe("COMPLETE");
    expect(statusLabel("failed")).toBe("FAILED");
  });
});

describe("statusTone", () => {
  it("pending is neutral", () => expect(statusTone("pending")).toBe("neutral"));
  it("running is gold", () => expect(statusTone("running")).toBe("gold"));
  it("awaiting_review is red", () =>
    expect(statusTone("awaiting_review")).toBe("red"));
  it("complete is sage", () => expect(statusTone("complete")).toBe("sage"));
  it("failed is red", () => expect(statusTone("failed")).toBe("red"));
});
