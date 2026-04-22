import { Link } from "react-router-dom";
import type { ProjectSummary, StageStatus } from "../types/api";
import { STAGE_ORDER } from "../types/api";
import { Card } from "./ui/Card";
import { Icon } from "./ui/Icon";
import { LazyImage } from "./ui/LazyImage";
import { Skeleton } from "./ui/Skeleton";
import { StatusPill } from "./ui/StatusPill";
import { STATUS_PRESENTATION } from "../lib/statusLabels";
import { useI18n } from "../i18n";

interface Props {
  project: ProjectSummary;
  coverPending?: boolean;
  coverFailed?: boolean;
}

function resolveStatus(project: ProjectSummary): StageStatus {
  if (project.is_running) return "running";
  if (project.furthest_stage === "assemble") return "complete";
  if (project.furthest_stage) return "awaiting_review";
  return "pending";
}

function formatCreated(createdAt: string) {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "ARCHIVE ACTIVE";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  });
}

export function ProjectCard({ project, coverPending = false, coverFailed = false }: Props) {
  const { stageName, t } = useI18n();
  const furthest = project.furthest_stage
    ? STAGE_ORDER.indexOf(project.furthest_stage as (typeof STAGE_ORDER)[number]) + 1
    : 0;
  const status = resolveStatus(project);
  const presentation = STATUS_PRESENTATION[status];
  const stageLabel = project.furthest_stage
    ? stageName(project.furthest_stage as (typeof STAGE_ORDER)[number])
    : t("ARCHIVE");
  const coverUrl = `/api/projects/${encodeURIComponent(project.name)}/files/cover/cover.png`;
  const progressPct = Math.round((furthest / STAGE_ORDER.length) * 100);
  const initial = (project.project_name?.[0] ?? project.name[0] ?? "?").toUpperCase();

  return (
    <Link
      to={`/project/${encodeURIComponent(project.name)}`}
      aria-label={`${t("OPEN FILE")}: ${project.project_name}`}
      className="group block h-full focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
    >
      <Card className="h-full overflow-hidden transition-transform duration-150 group-hover:-translate-y-[2px] group-focus-visible:-translate-y-[2px]">
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
            <div className="relative">
              <Skeleton aspect="4/5" />
              <div className="pointer-events-none absolute inset-0 flex items-end p-4 benday-paper/40">
                <div>
                  <div className="font-meta text-[0.48rem] tracking-[0.2em] text-ink-black/55">
                    {t("COVER GENERATING")}
                  </div>
                  <div className="mt-1 max-w-[10ch] font-display text-[2rem] font-bold leading-[0.88] tracking-[-0.05em] text-ink-black">
                    {project.project_name}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="relative flex aspect-[4/5] flex-col justify-end benday-paper p-4">
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <span
                  aria-hidden="true"
                  className="font-display font-bold leading-none tracking-[-0.08em] text-ink-black/12"
                  style={{ fontSize: "9rem" }}
                >
                  {initial}
                </span>
              </div>
              <div className="relative">
                <div className="font-meta text-[0.48rem] tracking-[0.2em] text-ink-black/55">
                  {coverFailed ? t("COVER FAILED") : t("COVER QUEUED")}
                </div>
                <div className="mt-1 max-w-[10ch] font-display text-[2rem] font-bold leading-[0.88] tracking-[-0.05em] text-ink-black">
                  {project.project_name}
                </div>
              </div>
            </div>
          )}

          {project.is_running && (
            <div className="absolute left-2 top-2 z-10 animate-pulse bg-hero-red px-2 py-1 font-meta text-[0.48rem] tracking-[0.18em] text-bristol">
              {t("ACTIVE")}
            </div>
          )}
        </div>

        <div className="p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="font-meta text-[0.48rem] tracking-[0.2em] text-ink-black/55">
                {t("CHECKPOINT")}
              </div>
              <div className="mt-0.5 truncate font-display text-[1.05rem] font-bold uppercase leading-none tracking-[-0.02em] text-ink-black">
                {stageLabel}
              </div>
            </div>
            <StatusPill tone={presentation.tone} title={presentation.description}>
              <Icon name={presentation.icon} size={10} className="mr-1" />
              {presentation.label}
            </StatusPill>
          </div>

          <div className="mt-3 h-2.5 border-[2px] border-ink-black bg-pulp-paper">
            <div className="h-full bg-archive-sage" style={{ width: `${progressPct}%` }} />
          </div>

          <div className="mt-3 flex items-center justify-between border-t-[2px] border-ink-black pt-2 text-[0.66rem]">
            <span className="font-meta tracking-[0.16em] text-ink-black/45">
              {formatCreated(project.created_at)}
            </span>
            <span className="font-body text-ink-black/80 tabular-nums">
              ${project.total_cost_usd.toFixed(2)}
            </span>
          </div>

          <div className="mt-1 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">
            {furthest}/7 · {project.project_name}
          </div>
        </div>
      </Card>
    </Link>
  );
}
