import type { ProjectSummary, StageName } from "../types/api";
import { BACKEND_STAGE_TO_STATION_ROUTE, stationForRoute, type Station } from "./stations";

/** Where a production stands, as the Library groups and filters it. */
export type ProjectShelfState = "needs" | "working" | "done" | "reset";

export function projectShelfState(project: ProjectSummary): ProjectShelfState {
  if (project.incompatible) return "reset";
  if (project.is_running) return "working";
  if (project.furthest_stage === "finish") return "done";
  return "needs";
}

export function projectStation(project: ProjectSummary): Station | undefined {
  const route = project.furthest_stage ? BACKEND_STAGE_TO_STATION_ROUTE[project.furthest_stage as StageName] : null;
  return route ? stationForRoute(route) : undefined;
}

const STAGE_COVER_STYLE: Partial<Record<StageName, { bg: string }>> = {
  extract:   { bg: "#2d3a2e" },
  brief:     { bg: "#362017" },
  style:     { bg: "#31151a" },
  cast:      { bg: "#0d1a2b" },
  adapt:     { bg: "#20162d" },
  plan:      { bg: "#1a1530" },
  draw:      { bg: "#0d1425" },
  finish:    { bg: "#101a12" },
};
const FALLBACK_BG = "#111827";

/** The typeset cover's colour, by how far the production has come. */
export function projectCoverColor(project: ProjectSummary): string {
  return (project.furthest_stage && STAGE_COVER_STYLE[project.furthest_stage as StageName]?.bg) || FALLBACK_BG;
}
