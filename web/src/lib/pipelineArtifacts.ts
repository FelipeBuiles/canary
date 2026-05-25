export function completedStageArtifactQueryKeys(
  projectId: string,
  stage: string,
): unknown[][] {
  switch (stage) {
    case "extract":
    case "cast":
      return [["project", projectId, "story-bible"]];
    case "style":
      return [["project", projectId, "styles"]];
    case "adapt":
      return [["project", projectId, "screenplays"]];
    case "plan":
      return [["project", projectId, "plan"]];
    case "storyboard":
      return [["project", projectId, "storyboard"]];
    case "direct":
      return [["project", projectId, "direct"]];
    case "draw":
      return [["project", projectId, "draw"]];
    case "compose":
      return [["project", projectId, "pages"]];
    default:
      return [];
  }
}
