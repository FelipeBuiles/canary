import { useState } from "react";
import { Link } from "react-router-dom";
import type { ProjectSummary, StageName } from "../types/api";
import { LazyImage } from "./ui/LazyImage";
import { Skeleton } from "./ui/Skeleton";
import { BACKEND_STAGE_TO_STATION_ROUTE, STATIONS, stationForRoute } from "../lib/stations";
import { useI18n } from "../i18n";
import { StatusPill } from "./ui/StatusPill";
import { partProjectKey, projectFileUrl } from "../api/projectScope";

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

interface Props {
  project: ProjectSummary;
  expanded?: boolean;
  coverPending?: boolean;
  coverFailed?: boolean;
  coverRetrying?: boolean;
  onRetryCover?: () => void;
  onDeleteIncompatible?: () => void;
  deleteIncompatiblePending?: boolean;
}

/** One status pill does both jobs: where in the flow, and the studio state word. */
function statusLine(project: ProjectSummary, t: (s: string) => string): { label: string; tone: "neutral" | "red" | "gold" | "sage" | "ink" } {
  if (project.incompatible) {
    return { label: t("Needs reset"), tone: "red" };
  }
  const stationRoute = project.furthest_stage
    ? BACKEND_STAGE_TO_STATION_ROUTE[project.furthest_stage as StageName]
    : null;
  const station = stationRoute ? stationForRoute(stationRoute) ?? STATIONS[0] : null;
  const where = (state: string) => (station ? `${t(station.label)} · ${state}` : state);

  if (project.is_running) return { label: where(t("Working")), tone: "ink" };
  if (project.furthest_stage === "finish") return { label: t("Ready"), tone: "sage" };
  if (project.furthest_stage) return { label: where(t("Needs you")), tone: "gold" };
  return { label: t("Not started"), tone: "neutral" };
}

export function ProjectCard({
  project,
  expanded = false,
  coverPending = false,
  coverFailed = false,
  coverRetrying = false,
  onRetryCover,
  onDeleteIncompatible,
  deleteIncompatiblePending = false,
}: Props) {
  const { t } = useI18n();
  const card = statusLine(project, t);
  // Each part has its own cover; the card shows the first part's.
  const coverUrl = projectFileUrl(partProjectKey(project.id, project.cover_part_id), "cover/cover.png");
  const coverComplete = project.has_cover && project.cover_job?.status === "complete";
  const [coverTransition, setCoverTransition] = useState({ project: project.id, complete: coverComplete, reveal: false });
  if (coverTransition.project !== project.id || coverTransition.complete !== coverComplete) {
    setCoverTransition({
      project: project.id,
      complete: coverComplete,
      reveal: coverTransition.project === project.id && !coverTransition.complete && coverComplete,
    });
  }

  const stageKey = project.furthest_stage as StageName | null;
  const coverStyle = stageKey ? STAGE_COVER_STYLE[stageKey] : undefined;
  const coverBg = coverStyle?.bg ?? FALLBACK_BG;
  const byline = project.author ? `by ${project.author}` : "author pending";
  const stationRoute = stageKey ? BACKEND_STAGE_TO_STATION_ROUTE[stageKey] : null;
  const station = stationRoute ? stationForRoute(stationRoute) : null;

  const cardContent = (
    <article className={`${expanded ? "sm:grid sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] sm:gap-6" : ""} h-full`}>
      {/* The cover is the card: it lifts like a page pulled from the stack. */}
      <div className="relative overflow-hidden outline outline-1 outline-ink-black/12 transition-[outline-color,box-shadow,translate] duration-[var(--motion-press)] group-hover:-translate-x-px group-hover:-translate-y-px group-hover:shadow-press group-hover:outline-2 group-hover:outline-ink-black group-focus-visible:-translate-x-px group-focus-visible:-translate-y-px group-focus-visible:shadow-press group-focus-visible:outline-2 group-focus-visible:outline-ink-black">
      {project.has_cover ? (
        <LazyImage
          src={coverUrl}
          alt={`${project.project_name} cover`}
          aspect="6 / 5"
          loading="lazy"
          containerClassName={`w-full${coverTransition.reveal ? " animate-proof-reveal" : ""}`}
          className="transition-transform duration-300 group-hover:scale-[1.02]"
        />
      ) : coverPending ? (
        <div className="relative aspect-[6/5]">
          <Skeleton className="absolute inset-0" />
          <div className="absolute bottom-0 left-0 z-10 bg-narrator-gold px-4 py-2.5 font-meta text-xs font-bold tracking-[0.08em] text-ink-black">
            <span className="animate-press-blink mr-2 inline-block h-2 w-2 bg-hero-red" />
            {t("DRAWING COVER…")}
          </div>
        </div>
      ) : (
        <div
          className="relative flex aspect-[6/5] flex-col justify-between overflow-hidden p-5 text-bristol"
          style={{ backgroundColor: coverBg }}
        >
          <div aria-hidden="true" className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(255,255,255,0.1)_1px,transparent_0)] [background-size:20px_20px]" />
          <div className="relative flex items-center justify-between border-b-[2px] border-bristol/35 pb-2 font-meta text-[0.5rem] font-bold tracking-[0.12em] text-bristol/75">
            <span>SCENEWRIGHT</span>
            <span>{station?.number ?? "00"}</span>
          </div>
          <div className="relative">
            <div
              aria-hidden="true"
              data-cover-title={project.project_name}
              className="font-display text-[1.65rem] font-black uppercase leading-[0.9] tracking-[-0.03em] before:content-[attr(data-cover-title)]"
            />
            <div className="mt-2 font-body text-[0.72rem] font-semibold text-bristol/70">{byline}</div>
          </div>
        </div>
      )}

      {project.is_running && !coverPending && (
        <div className="absolute bottom-0 left-0 z-10 bg-narrator-gold px-4 py-2.5 font-meta text-xs font-bold tracking-[0.08em] text-ink-black">
          <span className="animate-press-blink mr-2 inline-block h-2 w-2 bg-hero-red" />
          {station ? `${t(station.label)} · ${t("In progress")}` : t("In progress")}
        </div>
      )}
      </div>

      <div className={expanded ? "flex flex-col justify-center pt-3 sm:pt-0" : "pt-3"}>
      <h3
        title={project.project_name}
        className="break-words font-display text-[1.0625rem] font-black uppercase leading-none tracking-[-0.02em] text-ink-black"
      >
        {project.project_name}
      </h3>
      <p className="mt-1 truncate font-body text-xs text-ink-soft">
        {byline}
      </p>
      {!(project.is_running && !coverPending) && (
        <StatusPill tone={card.tone} className="mt-2">{card.label}</StatusPill>
      )}
      </div>
    </article>
  );

  return (
    <div className="relative h-full">
      {project.incompatible ? (
        <div className="block h-full" aria-label={`${t("PROJECT CANNOT OPEN")}: ${project.project_name}`}>
          {cardContent}
        </div>
      ) : (
        <Link
          to={`/project/${encodeURIComponent(project.id)}`}
          aria-label={`${t("OPEN FILE")}: ${project.project_name}`}
          className="group block h-full focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
        >
          {cardContent}
        </Link>
      )}

      {project.incompatible && onDeleteIncompatible && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-end">
          <button
            type="button"
            className="pointer-events-auto min-h-8 border-[2px] border-ink-black bg-hero-red px-3 font-meta text-xs font-semibold text-bristol shadow-press disabled:cursor-wait disabled:opacity-75"
            onClick={onDeleteIncompatible}
            disabled={deleteIncompatiblePending}
          >
            {deleteIncompatiblePending ? t("REMOVING…") : t("REMOVE OLD PROJECT")}
          </button>
        </div>
      )}

      {coverFailed && !project.has_cover && !coverPending && onRetryCover && (
        <div className={`pointer-events-none absolute inset-x-0 top-0 z-20 flex aspect-[6/5] items-start justify-end p-2 ${expanded ? "sm:right-auto sm:w-[45.4545%]" : ""}`}>
          <button
            type="button"
            className="pointer-events-auto min-h-8 border border-ink-black bg-pulp-paper px-2.5 font-meta text-xs font-medium text-ink-black transition-colors hover:bg-narrator-gold disabled:cursor-wait disabled:opacity-75"
            onClick={onRetryCover}
            disabled={coverRetrying}
          >
            {coverRetrying ? t("RETRYING COVER…") : t("Retry cover")}
          </button>
        </div>
      )}
    </div>
  );
}
