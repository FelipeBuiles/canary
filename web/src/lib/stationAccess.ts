import type { ProjectStatus, StageName } from "../types/api";
import { msg } from "../locales/messages";
import type { DrawerKind } from "./stations";
import { getStageQueue } from "./stageQueue";

export type RoomRoute = "story" | "styles" | "cast" | "pages" | "book";

const requirements = [
  { stage: "extract", route: "story", message: msg("Finish reading the manuscript in Story.") },
  { stage: "brief", route: "story", message: msg("Review and approve your story brief.") },
  { stage: "style", route: "styles", message: msg("Choose a visual direction in Look.") },
  { stage: "cast", route: "cast", message: msg("Review and approve your characters and places.") },
  { stage: "adapt", route: "pages", message: msg("Finish preparing the comic script in Pages.") },
  { stage: "plan", route: "pages", message: msg("Finish preparing the page plan in Pages.") },
  { stage: "draw", route: "pages", message: msg("Finish drawing and approve your pages.") },
] as const satisfies ReadonlyArray<{ stage: StageName; route: RoomRoute; message: string }>;

const requiredCount: Record<RoomRoute, number> = { story: 0, styles: 2, cast: 3, pages: 4, book: 7 };

export type RoomAccess =
  | { state: "loading" }
  | { state: "available" }
  | { state: "locked"; route: RoomRoute; message: string };

/** Use current prerequisites, never the furthest stage or sidebar progress.
 * Pages owns Adapt/Plan progress and recovery, so those are Book prerequisites.
 * Finish readiness governs export, not access to Book's preflight/recovery UI.
 */
export function getRoomAccess(route: string, status: ProjectStatus | undefined): RoomAccess {
  if (!Object.hasOwn(requiredCount, route)) return { state: "available" };
  if (!status) return { state: "loading" };
  for (const requirement of requirements.slice(0, requiredCount[route as RoomRoute])) {
    const info = status.stages[requirement.stage];
    const ready = requirement.stage === "style"
      ? status.style_selected && !info?.stale
      : info?.status === "complete" && !info.stale
        && (!["brief", "cast", "draw"].includes(requirement.stage) || info.approved === true)
        && !info.approval_blocker;
    if (!ready) return { state: "locked", route: requirement.route, message: requirement.message };
  }
  if (route === "book" && !(status.page_count && status.page_count > 0)) {
    return { state: "locked", route: "pages", message: msg("Create your comic pages before opening Book.") };
  }
  return { state: "available" };
}

/** Redirect the project landing page to an accessible recovery room. */
export function accessibleRoom(route: string, status: ProjectStatus): string {
  const access = getRoomAccess(route, status);
  return access.state === "locked" ? access.route : route;
}

/** Reading subpages open only once their current documents are generated. */
export function canReadDocument(kind: DrawerKind, status: ProjectStatus | undefined): boolean {
  const stages: StageName[] = kind === "adaptation" ? ["adapt"] : ["adapt", "plan"];
  return stages.every((stage) => status?.stages[stage]?.status === "complete"
    && !status.stages[stage].stale && !getStageQueue(stage, status.active_jobs));
}
