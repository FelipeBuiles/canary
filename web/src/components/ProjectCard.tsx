import { Link } from "react-router-dom";
import type { ProjectSummary, StageStatus, StageName } from "../types/api";
import { STAGE_ORDER } from "../types/api";
import { Card } from "./ui/Card";
import { LazyImage } from "./ui/LazyImage";
import { Skeleton } from "./ui/Skeleton";
import { StatusPill } from "./ui/StatusPill";
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
  const cls = "h-20 w-20 text-white/12";
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

  return (
    <Link
      to={`/project/${encodeURIComponent(project.name)}`}
      aria-label={`${t("OPEN FILE")}: ${project.project_name}`}
      className="group block h-full focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
    >
      <Card shadow="lg" className="h-full overflow-hidden transition-transform duration-150 group-hover:-translate-y-[2px] group-hover:shadow-ink-sm group-focus-visible:-translate-y-[2px]">
        <div className="relative border-b-[2px] border-ink-black">
          {project.has_cover ? (
            <LazyImage
              src={coverUrl}
              alt={`${project.project_name} cover`}
              aspect="4/5"
              loading="lazy"
              containerClassName="w-full"
              className="transition-transform duration-300 group-hover:scale-[1.02]"
            />
          ) : coverPending ? (
            <Skeleton aspect="4/5" />
          ) : (
            <div
              className="relative flex aspect-[4/5] items-center justify-center"
              style={{ backgroundColor: coverBg }}
            >
              <CoverShape kind={shapeKind} />
            </div>
          )}

          {stageLabel && (
            <div className={`absolute bottom-2 left-2 z-10 px-2 py-0.5 font-meta text-[0.42rem] tracking-[0.18em] text-bristol ${project.is_running ? "animate-pulse bg-hero-red" : "bg-ink-black/70"}`}>
              {stageLabel}
            </div>
          )}
        </div>

        <div className="p-3">
          <h3 className="truncate font-display text-[1.1rem] font-bold uppercase leading-none tracking-[-0.03em] text-ink-black">
            {project.project_name}
          </h3>

          <div className="mt-2.5 flex items-center justify-between gap-2">
            <StatusPill tone={presentation.tone} title={presentation.description}>
              {presentation.label}
            </StatusPill>
            <span className="font-body text-[0.78rem] text-ink-black/70 tabular-nums">
              ${project.total_cost_usd.toFixed(2)}
            </span>
          </div>
        </div>
      </Card>
    </Link>
  );
}
