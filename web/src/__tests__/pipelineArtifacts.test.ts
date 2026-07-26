import { describe, expect, it } from "vitest";
import { completedStageArtifactQueryKeys } from "../lib/pipelineArtifacts";

describe("completedStageArtifactQueryKeys", () => {
  it("invalidates the book adaptation when adapt completes", () => {
    expect(completedStageArtifactQueryKeys("proj", "adapt")).toEqual([
      ["project", "proj", "adaptation"],
    ]);
  });

  it("maps each stage to the artifact query its room reads", () => {
    expect(completedStageArtifactQueryKeys("proj", "extract")).toEqual([
      ["project", "proj", "story"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "brief")).toEqual([
      ["project", "proj", "story"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "style")).toEqual([
      ["project", "proj", "styles"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "plan")).toEqual([
      ["project", "proj", "book-plan"],
      ["project", "proj", "complete-pages"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "draw")).toEqual([
      ["project", "proj", "complete-pages"],
    ]);
    expect(completedStageArtifactQueryKeys("proj", "finish")).toEqual([
      ["project", "proj", "finish-preflight"],
    ]);
  });
});
