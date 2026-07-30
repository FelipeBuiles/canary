import { Link } from "react-router-dom";
import type { ProjectSummary, StageName } from "../types/api";
import { LazyImage } from "./ui/LazyImage";
import { Skeleton } from "./ui/Skeleton";
import { BACKEND_STAGE_TO_STATION_ROUTE, STATIONS, stationForRoute } from "../lib/stations";
import { useI18n } from "../i18n";

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
  coverPending?: boolean;
  coverFailed?: boolean;
  coverRetrying?: boolean;
  onRetryCover?: () => void;
  onDeleteIncompatible?: () => void;
  deleteIncompatiblePending?: boolean;
}

/** One status line does both jobs: what state, and where in the flow. */
function statusLine(project: ProjectSummary, t: (s: string) => string): { label: string; className: string } {
  if (project.incompatible) {
    return { label: t("Needs reset"), className: "bg-hero-red text-bristol" };
  }
  const stationRoute = project.furthest_stage
    ? BACKEND_STAGE_TO_STATION_ROUTE[project.furthest_stage as StageName]
    : null;
  const station = stationRoute ? stationForRoute(stationRoute) ?? STATIONS[0] : null;
  const stationLabel = station ? t(station.label) : null;

  if (project.is_running) {
    return {
      label: stationLabel ? `${t("In progress")} — ${stationLabel}` : t("In progress"),
      className: "bg-narrator-gold text-ink-black",
    };
  }
  if (project.furthest_stage === "finish") {
    return { label: t("Complete"), className: "bg-chip-sage text-archive-sage" };
  }
  if (project.furthest_stage) {
    return {
      label: stationLabel ? `${t("Needs your review")} — ${stationLabel}` : t("Needs your review"),
      className: "bg-chip-gold text-ink-black",
    };
  }
  return { label: t("New"), className: "bg-surface-container text-ink-muted" };
}

export function ProjectCard({
  project,
  coverPending = false,
  coverFailed = false,
  coverRetrying = false,
  onRetryCover,
  onDeleteIncompatible,
  deleteIncompatiblePending = false,
}: Props) {
  const { t } = useI18n();
  const card = statusLine(project, t);
  const coverUrl = `/api/projects/${encodeURIComponent(project.id)}/files/cover/cover.png`;
  const coverRevealed = project.has_cover && project.cover_job?.status === "complete";

  const stageKey = project.furthest_stage as StageName | null;
  const coverStyle = stageKey ? STAGE_COVER_STYLE[stageKey] : undefined;
  const coverBg = coverStyle?.bg ?? FALLBACK_BG;
  const byline = project.author ? `by ${project.author}` : "author pending";
  const stationRoute = stageKey ? BACKEND_STAGE_TO_STATION_ROUTE[stageKey] : null;
  const station = stationRoute ? stationForRoute(stationRoute) : null;

  const cardContent = (
    <article className={`h-full overflow-hidden border-[3px] border-ink-black/12 bg-bristol shadow-paper-sm transition-[border-color,box-shadow,transform] duration-200 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:border-ink-black group-hover:-translate-x-[2px] group-hover:-translate-y-[2px] group-hover:shadow-ink group-focus-visible:border-ink-black group-focus-visible:-translate-x-[2px] group-focus-visible:-translate-y-[2px] group-focus-visible:shadow-ink${coverRevealed ? " animate-comic-pop" : ""}`}>
      <div className="relative border-b-[2px] border-ink-black/12 transition-colors duration-200 group-hover:border-ink-black group-focus-visible:border-ink-black">
      {project.has_cover ? (
        <LazyImage
          src={coverUrl}
          alt={`${project.project_name} cover`}
          aspect="6 / 5"
          loading="lazy"
          containerClassName="w-full"
          className="transition-transform duration-300 group-hover:scale-[1.02]"
        />
      ) : coverPending ? (
        <div className="relative aspect-[6/5]">
          <Skeleton className="absolute inset-0" />
          <div className="absolute bottom-0 left-0 z-10 bg-narrator-gold px-4 py-2.5 font-meta text-[0.68rem] font-bold tracking-[0.12em] text-ink-black">
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
        <div className="absolute bottom-0 left-0 z-10 bg-narrator-gold px-4 py-2.5 font-meta text-[0.68rem] font-bold tracking-[0.12em] text-ink-black">
          <span className="animate-press-blink mr-2 inline-block h-2 w-2 bg-hero-red" />
          {t("DRAWING…")}
        </div>
      )}
      </div>

      <div className="p-4">
      <h3
        title={project.project_name}
        className="truncate font-display text-[1.34rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black"
      >
        {project.project_name}
      </h3>
      <p className="mt-2 truncate font-body text-[0.86rem] font-semibold leading-tight text-ink-muted">
        {byline}
      </p>

      <div className="mt-3">
        <span
          className={`inline-flex min-h-7 items-center px-3.5 font-meta text-[0.62rem] font-bold leading-none tracking-[0.16em] uppercase ${card.className}`}
        >
          {card.label}
        </span>
      </div>
      <div className="mt-4 flex items-center justify-between border-t-[2px] border-ink-black/10 pt-3 font-meta text-[0.58rem] font-bold tracking-[0.1em] text-ink-muted transition-colors group-hover:text-ink-black">
        <span>{project.incompatible ? t("PROJECT CANNOT OPEN") : t("OPEN FILE")}</span>
        <span aria-hidden="true" className="text-hero-red transition-transform duration-150 group-hover:translate-x-1">{project.incompatible ? "×" : "→"}</span>
      </div>
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
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-end p-4">
          <button
            type="button"
            className="pointer-events-auto min-h-11 bg-hero-red px-4 font-meta text-[0.62rem] font-bold uppercase tracking-[0.12em] text-bristol shadow-[3px_3px_0_0_var(--color-ink-black)] transition-transform hover:-translate-y-0.5 disabled:cursor-wait disabled:opacity-75"
            onClick={onDeleteIncompatible}
            disabled={deleteIncompatiblePending}
          >
            {deleteIncompatiblePending ? t("REMOVING…") : t("REMOVE OLD PROJECT")}
          </button>
        </div>
      )}

      {coverFailed && !project.has_cover && !coverPending && onRetryCover && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-20 flex aspect-[6/5] items-end p-4">
          <button
            type="button"
            className="pointer-events-auto min-h-11 bg-hero-red px-4 font-meta text-[0.62rem] font-bold uppercase tracking-[0.12em] text-bristol shadow-[3px_3px_0_0_var(--color-ink-black)] transition-transform hover:-translate-y-0.5 disabled:cursor-wait disabled:opacity-75"
            onClick={onRetryCover}
            disabled={coverRetrying}
          >
            {coverRetrying ? t("RETRYING COVER…") : t("COVER FAILED — RETRY")}
          </button>
        </div>
      )}
    </div>
  );
}
