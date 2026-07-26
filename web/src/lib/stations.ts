import { STAGE_ORDER, type ProjectStatus, type StageName, type StageStatus } from "../types/api";

/**
 * The 4 user-facing stations — a UI grouping over the 8 backend stages.
 * Backend stages stay discrete (see AGENTS.md); this module is the only
 * place that knows how they roll up into stations.
 *
 * Gated substeps are user decisions and navigate to a room. Auto substeps
 * run without approval and open a read-only inspect drawer instead — they
 * never block progression.
 */

export type StationKey = "story" | "look" | "pages" | "book";
export type DrawerKind = "adaptation" | "page-plan";

export interface StationSubstep {
  key: string;
  label: string;
  kind: "gated" | "auto";
  backendStages: StageName[];
  /** Gated substeps navigate to this project-relative route. */
  route?: string;
  /** Auto substeps open this inspect drawer. */
  drawer?: DrawerKind;
}

export interface Station {
  key: StationKey;
  number: string;
  label: string;
  /** Routes whose room belongs to this station (for active detection). */
  routes: string[];
  primaryRoute: string;
  substeps: StationSubstep[];
}

export const STATIONS: Station[] = [
  {
    key: "story",
    number: "01",
    label: "Story",
    routes: ["story"],
    primaryRoute: "story",
    substeps: [
      { key: "brief", label: "Story & brief", kind: "gated", backendStages: ["extract", "brief"], route: "story" },
    ],
  },
  {
    key: "look",
    number: "02",
    label: "Look",
    routes: ["styles", "cast"],
    primaryRoute: "styles",
    substeps: [
      { key: "style", label: "Art style", kind: "gated", backendStages: ["style"], route: "styles" },
      { key: "cast", label: "Characters & places", kind: "gated", backendStages: ["cast"], route: "cast" },
    ],
  },
  {
    key: "pages",
    number: "03",
    label: "Pages",
    routes: ["pages"],
    primaryRoute: "pages",
    substeps: [
      { key: "adapt", label: "Book adaptation", kind: "auto", backendStages: ["adapt"], drawer: "adaptation" },
      { key: "plan", label: "Page plan", kind: "auto", backendStages: ["plan"], drawer: "page-plan" },
      { key: "draw", label: "Complete pages", kind: "gated", backendStages: ["draw"], route: "pages" },
    ],
  },
  {
    key: "book",
    number: "04",
    label: "Book",
    routes: ["book"],
    primaryRoute: "book",
    substeps: [
      { key: "finish", label: "Preflight & export", kind: "gated", backendStages: ["finish"], route: "book" },
    ],
  },
];

export type StationState = "done" | "review" | "running" | "failed" | "wait";

function stageStatusOf(status: ProjectStatus | undefined, stage: StageName): StageStatus {
  return status?.stages[stage]?.status ?? "pending";
}

function stageFailed(status: ProjectStatus | undefined, stage: StageName): boolean {
  const info = status?.stages[stage];
  if (!info) return false;
  if (info.approved) return false; // user signed off — partial failures no longer block
  return info.status === "failed" || (info.status === "complete" && (info.items_failed?.length ?? 0) > 0);
}

/**
 * Station state derives from its substeps. Auto substeps can mark a station
 * running or failed (work is happening / broke), but never keep it from
 * being "done" — only the user's gated decisions do that.
 */
export function getStationState(station: Station, status: ProjectStatus | undefined): StationState {
  const allStages = station.substeps.flatMap((s) => s.backendStages);
  const gatedStages = station.substeps.filter((s) => s.kind === "gated").flatMap((s) => s.backendStages);
  const gatedStageSuperseded = (stage: StageName) => {
    const index = STAGE_ORDER.indexOf(stage);
    return index >= 0 && STAGE_ORDER
      .slice(index + 1)
      .some((laterStage) => stageStatusOf(status, laterStage) !== "pending");
  };

  if (allStages.some((s) => stageStatusOf(status, s) === "running")) return "running";
  // A live downstream stage is the current truth for the station. An older
  // failed auto-step must not mask that work while the recovery chain runs.
  // The same applies to an earlier gated step: once a later gated step has
  // started, the user has necessarily accepted/progressed past the earlier
  // step (style selection is the gate that allows cast to run). Keep the
  // sidebar focused on the unresolved failure rather than stale history.
  if (allStages.some((stage) => {
    if (!stageFailed(status, stage)) return false;
    return !gatedStageSuperseded(stage);
  })) return "failed";
  if (gatedStages.some((s) =>
    stageStatusOf(status, s) === "awaiting_review" && !gatedStageSuperseded(s)
  )) return "review";
  if (gatedStages.every((s) => stageStatusOf(status, s) === "complete" || gatedStageSuperseded(s))) return "done";
  return "wait";
}

export type SubstepState = "done" | "current" | "pending";

export function getSubstepState(substep: StationSubstep, status: ProjectStatus | undefined): SubstepState {
  const statuses = substep.backendStages.map((s) => stageStatusOf(status, s));
  if (statuses.every((s) => s === "complete")) return "done";
  if (statuses.some((s) => s === "running" || s === "awaiting_review" || s === "failed")) return "current";
  return "pending";
}

export function stationForRoute(route: string): Station | undefined {
  return STATIONS.find((station) => station.routes.includes(route));
}

/**
 * Land on the decision that currently needs the user, not blindly on the
 * station's first route. This lets the sidebar stay at four stations without
 * making the user understand the gated backend steps inside Look.
 */
export function stationDestination(
  station: Station,
  status: ProjectStatus | undefined,
): string {
  const gated = station.substeps.filter(
    (substep): substep is StationSubstep & { route: string } =>
      substep.kind === "gated" && Boolean(substep.route),
  );

  const active = gated.find((substep) =>
    substep.backendStages.some((stage) => {
      const stageStatus = stageStatusOf(status, stage);
      return stageStatus === "awaiting_review" || stageStatus === "running" || stageStatus === "failed";
    }),
  );
  if (active) return active.route;

  const next = gated.find((substep) =>
    substep.backendStages.some((stage) => stageStatusOf(status, stage) !== "complete"),
  );
  return next?.route ?? station.primaryRoute;
}

/**
 * The backend stage a drawer's "Rerun from here" action targets: the first
 * backend stage of the auto substep that owns the drawer. Rerunning it clears
 * and regenerates that substep plus everything downstream (see RERUN_IMPACT /
 * clean_cascade), which is how the four-station UI re-exposes "re-run from a
 * determinate stage" for the auto chain.
 */
export function rerunStageForDrawer(kind: DrawerKind): StageName {
  for (const station of STATIONS) {
    const substep = station.substeps.find((s) => s.drawer === kind);
    if (substep) return substep.backendStages[0];
  }
  throw new Error(`No substep owns drawer kind: ${kind}`);
}

/**
 * Where to land for a given pipeline position. Auto stages resolve to the
 * room where the user watches/acts on their outcome, never to the demoted
 * machine-artifact rooms.
 */
export const BACKEND_STAGE_TO_STATION_ROUTE: Record<StageName, string> = {
  extract: "story",
  brief: "story",
  style: "styles",
  cast: "cast",
  adapt: "pages",
  plan: "pages",
  draw: "pages",
  finish: "book",
};
