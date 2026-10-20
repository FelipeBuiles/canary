import type { QueryClient } from "@tanstack/react-query";
import { invalidateProject } from "./projectScope";

/** Every page change invalidates the render and its dependent review evidence. */
export function invalidatePageReview(qc: QueryClient, project: string, pageNumber?: number) {
  for (const resource of ["complete-pages", "page-visual-review", "page-render-correction", "page-analysis-estimate"] as const) {
    if (pageNumber == null) void invalidateProject(qc, project, resource);
    else {
      if (resource === "complete-pages") void invalidateProject(qc, project, resource);
      void invalidateProject(qc, project, resource, pageNumber);
    }
  }
  void qc.invalidateQueries({ queryKey: ["visual-review-estimate", project] });
  void invalidateProject(qc, project, "status");
  void invalidateProject(qc, project, "generation-jobs");
  void qc.invalidateQueries({ queryKey: ["credits", "history"] });
}
