import { describe, expect, it } from "vitest";
import { completedStageArtifactQueryKeys } from "../lib/pipelineArtifacts";

describe("completedStageArtifactQueryKeys", () => {
  it("invalidates screenplay list and scene queries when adapt completes", () => {
    expect(completedStageArtifactQueryKeys("proj", "adapt")).toEqual([
      ["project", "proj", "screenplays"],
    ]);
  });

  it("maps each stage to the artifact query its room reads", () => {
    expect(completedStageArtifactQueryKeys("proj", "extract")).toEqual([
      ["project", "proj", "story-bible"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "style")).toEqual([
      ["project", "proj", "styles"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "plan")).toEqual([
      ["project", "proj", "plan"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "storyboard")).toEqual([
      ["project", "proj", "storyboard"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "direct")).toEqual([
      ["project", "proj", "direct"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "draw")).toEqual([
      ["project", "proj", "draw"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "compose")).toEqual([
      ["project", "proj", "pages"],
    ]);
  });
});
