import { Link } from "react-router-dom";
import type { ProjectSummary, StageStatus, StageName } from "../types/api";
import { STAGE_ORDER } from "../types/api";
import { LazyImage } from "./ui/LazyImage";
import { Skeleton } from "./ui/Skeleton";
import { STATUS_PRESENTATION } from "../lib/statusLabels";
import { useI18n } from "../i18n";

const STAGE_COVER_STYLE: Partial<Record<StageName, { bg: string }>> = {
  extract: { bg: "#2d3a2e" },
  index:   { bg: "#0d1a2b" },
  prompts: { bg: "#1c1408" },
  generate:{ bg: "#0d1425" },
  assemble:{ bg: "#101a12" },
};
const FALLBACK_BG = "#111827";

type ShapeKind = "chevron" | "diamond" | "triangle" | "circle";

const STAGE_SHAPE: Partial<Record<StageName, ShapeKind>> = {
  extract:  "chevron",
  index:    "circle",
  prompts:  "triangle",
  generate: "diamond",
  assemble: "chevron",
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

function resolveStatus(project: ProjectSummary): StageStatus {
  if (project.is_running) return "running";
  if (project.furthest_stage === "assemble") return "complete";
  if (project.furthest_stage) return "awaiting_review";
  return "pending";
}

function statusClass(tone: string) {
  if (tone === "gold") return "bg-narrator-gold text-ink-black";
  if (tone === "sage") return "bg-archive-sage text-bristol";
  if (tone === "red") return "bg-hero-red text-bristol";
  return "bg-surface-container text-ink-black";
}

export function ProjectCard({ project, coverPending = false }: Props) {
  const { stageName, t } = useI18n();
  const status = resolveStatus(project);
  const presentation = STATUS_PRESENTATION[status];
  const stageLabel = project.furthest_stage
    ? stageName(project.furthest_stage as (typeof STAGE_ORDER)[number])
    : null;
  const coverUrl = `/api/projects/${encodeURIComponent(project.name)}/files/cover/cover.png`;

  const stageKey = project.furthest_stage as StageName | null;
  const coverStyle = stageKey ? STAGE_COVER_STYLE[stageKey] : undefined;
  const coverBg = coverStyle?.bg ?? FALLBACK_BG;
  const shapeKind: ShapeKind = (stageKey ? STAGE_SHAPE[stageKey] : undefined) ?? "circle";
  const byline = project.author ? `by ${project.author}` : "author pending";

  return (
    <Link
      to={`/project/${encodeURIComponent(project.name)}`}
      aria-label={`${t("OPEN FILE")}: ${project.project_name}`}
      className="group block h-full focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
    >
      <article className="h-full overflow-hidden border-[3px] border-ink-black/8 bg-bristol transition-[border-color,box-shadow] duration-150 group-hover:border-ink-black group-hover:shadow-paper-sm group-focus-visible:border-ink-black group-focus-visible:shadow-paper-sm">
        <div className="relative border-b-[2px] border-ink-black/8 transition-colors duration-150 group-hover:border-ink-black group-focus-visible:border-ink-black">
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

          {stageLabel && (
            <div className={`absolute bottom-0 left-0 z-10 px-5 py-3 font-meta text-[0.82rem] tracking-[0.22em] text-bristol ${project.is_running ? "animate-pulse bg-hero-red" : "bg-ink-black/70"}`}>
              {stageLabel}
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

          <div className="mt-3 flex items-center justify-between gap-4">
            <span
              title={presentation.description}
              className={`inline-flex min-h-7 items-center px-3.5 font-meta text-[0.66rem] font-bold leading-none tracking-[0.2em] uppercase ${statusClass(presentation.tone)}`}
            >
              {presentation.label}
            </span>
            <span className="font-body text-[0.86rem] font-bold leading-none text-ink-black/55 tabular-nums">
              ${project.total_cost_usd.toFixed(2)}
            </span>
          </div>
        </div>
      </article>
    </Link>
  );
}
