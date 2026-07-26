export function completedStageArtifactQueryKeys(
  projectId: string,
  stage: string,
): unknown[][] {
  switch (stage) {
    case "extract":
    case "brief":
      return [["project", projectId, "story"]];
    case "cast":
      return [["project", projectId, "story-bible"]];
    case "style":
      return [["project", projectId, "styles"]];
    case "adapt":
      return [["project", projectId, "adaptation"]];
    case "plan":
      return [["project", projectId, "book-plan"], ["project", projectId, "complete-pages"]];
    case "draw":
      return [["project", projectId, "complete-pages"]];
    case "finish":
      return [["project", projectId, "finish-preflight"]];
    default:
      return [];
  }
}
