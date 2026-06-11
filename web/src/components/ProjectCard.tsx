import { useState } from "react";
import { Link } from "react-router-dom";
import type { ProjectSummary, StageName } from "../types/api";
import { LazyImage } from "./ui/LazyImage";
import { Skeleton } from "./ui/Skeleton";
import { BACKEND_STAGE_TO_STATION_ROUTE, STATIONS, stationForRoute } from "../lib/stations";
import { useI18n } from "../i18n";

const STAGE_COVER_STYLE: Partial<Record<StageName, { bg: string }>> = {
  extract:   { bg: "#2d3a2e" },
  cast:      { bg: "#0d1a2b" },
  plan:      { bg: "#1a1530" },
  direct:    { bg: "#1c1408" },
  draw:      { bg: "#0d1425" },
  compose:   { bg: "#101a12" },
};
const FALLBACK_BG = "#111827";

type ShapeKind = "chevron" | "diamond" | "triangle" | "circle";

const STAGE_SHAPE: Partial<Record<StageName, ShapeKind>> = {
  extract:   "chevron",
  cast:      "circle",
  plan:      "diamond",
  direct:    "triangle",
  draw:      "diamond",
  compose:   "chevron",
};

function CoverShape({ kind }: { kind: ShapeKind }) {
  const cls = "h-24 w-24 text-white/12";
  const stroke = { stroke: "currentColor", fill: "none", strokeWidth: "1.5" };
  if (kind === "circle")
    return <svg viewBox="0 0 100 100" className={cls} {...stroke}><circle cx="50" cy="50" r="34"/></svg>;
  if (kind === "diamond")
    return <svg viewBox="0 0 100 100" className={cls} {...stroke}><polygon points="50,14 86,50 50,86 14,50"/></svg>;
  if (kind === "triangle")
    return <svg viewBox="0 0 100 100" className={cls} {...stroke}><polygon points="50,16 84,82 16,82"/></svg>;
  return <svg viewBox="0 0 100 100" className={cls} {...stroke}><polyline points="22,52 42,68 78,34"/></svg>;
}

interface Props {
  project: ProjectSummary;
  coverPending?: boolean;
}

/** One status line does both jobs: what state, and where in the flow. */
function statusLine(project: ProjectSummary, t: (s: string) => string): { label: string; className: string } {
  const stationRoute = project.furthest_stage
    ? BACKEND_STAGE_TO_STATION_ROUTE[project.furthest_stage as StageName]
    : null;
  const station = stationRoute ? stationForRoute(stationRoute) ?? STATIONS[0] : null;
  const stationLabel = station ? t(station.label) : null;

  if (project.is_running) {
    return {
      label: stationLabel ? `${t("In progress")} — ${stationLabel}` : t("In progress"),
      className: "bg-surface-container text-ink-black",
    };
  }
  if (project.furthest_stage === "compose") {
    return { label: t("Complete"), className: "bg-surface-container text-ink-black/70" };
  }
  if (project.furthest_stage) {
    return {
      label: stationLabel ? `${t("Needs your review")} — ${stationLabel}` : t("Needs your review"),
      className: "bg-surface-container text-ink-black",
    };
  }
  return { label: t("New"), className: "bg-surface-container text-ink-black/60" };
}

export function ProjectCard({ project, coverPending = false }: Props) {
  const { t } = useI18n();
  const card = statusLine(project, t);
  const coverUrl = `/api/projects/${encodeURIComponent(project.id)}/files/cover/cover.png`;

  // Pop the card once when a cover that was generating lands. Cards that
  // mount already-covered never fire; LazyImage handles the opacity fade.
  const [coverArrival, setCoverArrival] = useState<"idle" | "pending" | "revealed">(
    coverPending && !project.has_cover ? "pending" : "idle",
  );
  if (coverArrival === "idle" && coverPending && !project.has_cover) {
    setCoverArrival("pending");
  }
  if (coverArrival === "pending" && project.has_cover) {
    setCoverArrival("revealed");
  }
  const coverRevealed = coverArrival === "revealed";

  const stageKey = project.furthest_stage as StageName | null;
  const coverStyle = stageKey ? STAGE_COVER_STYLE[stageKey] : undefined;
  const coverBg = coverStyle?.bg ?? FALLBACK_BG;
  const shapeKind: ShapeKind = (stageKey ? STAGE_SHAPE[stageKey] : undefined) ?? "circle";
  const byline = project.author ? `by ${project.author}` : "author pending";

  return (
    <Link
      to={`/project/${encodeURIComponent(project.id)}`}
      aria-label={`${t("OPEN FILE")}: ${project.project_name}`}
      className="group block h-full focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
    >
      <article className={`h-full overflow-hidden border-[3px] border-ink-black/12 bg-bristol shadow-paper-sm transition-[border-color,box-shadow,transform] duration-200 ease-out group-hover:border-ink-black group-hover:-translate-x-[2px] group-hover:-translate-y-[2px] group-hover:shadow-ink group-focus-visible:border-ink-black group-focus-visible:-translate-x-[2px] group-focus-visible:-translate-y-[2px] group-focus-visible:shadow-ink${coverRevealed ? " animate-comic-pop" : ""}`}>
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
            <Skeleton aspect="6 / 5" />
          ) : (
            <div
              className="relative flex aspect-[6/5] items-center justify-center bg-[radial-gradient(circle_at_1px_1px,rgba(255,255,255,0.08)_1px,transparent_0)] [background-size:24px_24px]"
              style={{ backgroundColor: coverBg }}
            >
              <CoverShape kind={shapeKind} />
            </div>
          )}

          {project.is_running && (
            <div className="absolute bottom-0 left-0 z-10 animate-pulse bg-ink-black/70 px-5 py-3 font-meta text-[0.82rem] tracking-[0.22em] text-bristol">
              {t("DRAWING…")}
            </div>
          )}
        </div>

        <div className="p-4">
          <h3
            title={project.project_name}
            className="truncate font-display text-[1.34rem] font-black uppercase leading-none tracking-[-0.055em] text-ink-black"
          >
            {project.project_name}
          </h3>
          <p className="mt-2 truncate font-body text-[0.86rem] font-semibold leading-tight text-ink-black/55">
            {byline}
          </p>

          <div className="mt-3">
            <span
              className={`inline-flex min-h-7 items-center px-3.5 font-meta text-[0.62rem] font-bold leading-none tracking-[0.16em] uppercase ${card.className}`}
            >
              {card.label}
            </span>
          </div>
        </div>
      </article>
    </Link>
  );
}
