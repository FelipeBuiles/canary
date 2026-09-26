import { describe, expect, it } from "vitest";
import { getStageQueue } from "../lib/stageQueue";
import { getStationState, STATIONS } from "../lib/stations";
import type { GenerationJob, ProjectStatus } from "../types/api";

const queued = { kind: "pipeline_stage", stage: "adapt", payload: { stage: "adapt" }, status: "queued" } as unknown as GenerationJob;
const cover = { kind: "project_cover", status: "running", stage: "cast" } as unknown as GenerationJob;
describe("queue evidence", () => {
  it("requires a stage job, not just a running cover or a pending stage", () => {
    expect(getStageQueue("adapt", [cover])).toBeUndefined();
    expect(getStageQueue("cast", [cover])).toBeUndefined();
    expect(getStageQueue("plan", [queued, cover])).toBeUndefined();
  });
  it("explains cover, account, and ordinary queue waits from active jobs", () => {
    expect(getStageQueue("adapt", [queued, cover])).toEqual({ state: "queued", waitingFor: "cover" });
    expect(getStageQueue("adapt", [{ ...queued, waiting_for_other_project: true }, cover])?.waitingFor).toBe("other-project");
    expect(getStageQueue("adapt", [queued])?.waitingFor).toBe("work");
  });
  it("distinguishes worker pickup and terminal jobs", () => {
    expect(getStageQueue("adapt", [{ ...queued, status: "running" }])?.state).toBe("starting");
    for (const status of ["complete", "failed", "cancelled"] as const) {
      expect(getStageQueue("adapt", [{ ...queued, status }])).toBeUndefined();
    }
  });
  it("shows queued in Pages navigation until the stage begins", () => {
    const status = { stages: { adapt: { status: "pending" } }, active_jobs: [queued, cover] } as unknown as ProjectStatus;
    expect(getStationState(STATIONS[2], status)).toBe("queued");
    status.stages.adapt.status = "running";
    expect(getStationState(STATIONS[2], status)).toBe("running");
  });
});
