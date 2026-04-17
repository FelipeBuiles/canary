import { Link } from "react-router-dom";
import type { ProjectSummary, StageStatus } from "../types/api";
import { STAGE_DISPLAY_NAMES, STAGE_ORDER } from "../types/api";
import { Card } from "./ui/Card";
import { Tag } from "./ui/Tag";

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

function resolveTone(status: StageStatus) {
  if (status === "complete") return "bg-bristol text-ink-black";
  if (status === "awaiting_review") return "bg-hero-red text-bristol";
  if (status === "running") return "bg-narrator-gold text-ink-black";
  if (status === "failed") return "bg-hero-red text-bristol";
  return "bg-pulp-paper text-ink-black";
}

function resolveTag(status: StageStatus) {
  if (status === "complete") return "ACCEPTED";
  if (status === "awaiting_review") return "REVIEW";
  if (status === "running") return "LIVE";
  if (status === "failed") return "ERROR";
  return "QUEUE";
}

export function ProjectCard({ project, coverPending = false, coverFailed = false }: Props) {
  const furthest = project.furthest_stage
    ? STAGE_ORDER.indexOf(project.furthest_stage as (typeof STAGE_ORDER)[number]) + 1
    : 0;
  const status = resolveStatus(project);
  const stageLabel = project.furthest_stage
    ? STAGE_DISPLAY_NAMES[project.furthest_stage as (typeof STAGE_ORDER)[number]]
    : "ARCHIVE";
  const coverUrl = `/api/projects/${encodeURIComponent(project.name)}/files/cover/cover.png`;
  const progressPct = Math.round((furthest / STAGE_ORDER.length) * 100);

  return (
    <Card className="overflow-hidden transition-transform duration-150 hover:-translate-y-[2px]">
      <div className="relative border-b-[2px] border-ink-black bg-ink-black">
        {project.has_cover ? (
          <img
            src={coverUrl}
            alt={`${project.project_name} cover`}
            loading="lazy"
            className="aspect-[4/5] w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
          />
        ) : (
          <div className="flex aspect-[4/5] flex-col justify-end bg-ink-black p-4 text-bristol">
            <div className="font-meta text-[0.46rem] tracking-[0.18em] text-bristol/45">
              {coverFailed ? "COVER FAILED" : coverPending ? "COVER GENERATING" : "COVER QUEUED"}
            </div>
            <div className="mt-2 max-w-[10ch] font-display text-[2.4rem] font-bold leading-[0.86] tracking-[-0.07em] text-bristol">
              {project.project_name}
            </div>
            <div className="mt-4 h-2 border border-bristol/35">
              <div className="h-full animate-pulse bg-narrator-gold" style={{ width: coverPending ? "60%" : "22%" }} />
            </div>
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-black/85 to-transparent p-3 pt-12">
          <div className="font-meta text-[0.48rem] tracking-[0.18em] text-bristol/70">
            {stageLabel}
          </div>
          <h3 className="mt-1 font-display text-[2rem] font-bold leading-none tracking-[-0.06em] text-bristol">
            {project.project_name}
          </h3>
        </div>

          {project.is_running && (
            <div className="absolute left-2 top-2 z-10 animate-pulse bg-hero-red px-2 py-1 font-meta text-[0.48rem] tracking-[0.18em] text-bristol">
              ACTIVE
            </div>
          )}
          <Tag
            className={`absolute right-2 top-2 ${resolveTone(status)}`}
          >
            {resolveTag(status)}
          </Tag>
      </div>

      <div className="p-3">
        <div className="grid grid-cols-[1fr_auto] gap-4">
          <p className="text-[0.78rem] leading-6 text-ink-black/72">
            {project.has_cover
              ? "Project cover, pipeline position, cost, and latest review checkpoint."
              : coverFailed
                ? "Cover generation failed; opening the project still gives access to every pipeline room."
                : "Cover art is being prepared from the story bible and selected visual style."}
          </p>
          <div className="text-right">
            <div className="font-display text-[1.8rem] font-bold leading-none tracking-[-0.05em] text-ink-black">
              {furthest}
            </div>
            <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/45">
              OF 7
            </div>
          </div>
        </div>

        <div className="mt-4 h-3 border-[2px] border-ink-black bg-pulp-paper">
          <div className="h-full bg-archive-sage" style={{ width: `${progressPct}%` }} />
        </div>

        <div className="mt-4 space-y-2 border-t-[2px] border-ink-black pt-3">
          <div className="flex items-center justify-between text-[0.66rem]">
            <span className="font-meta tracking-[0.16em] text-ink-black/45">
              CREATED
            </span>
            <span className="font-body text-ink-black/78">
              {formatCreated(project.created_at)}
            </span>
          </div>
          <div className="flex items-center justify-between text-[0.66rem]">
            <span className="font-meta tracking-[0.16em] text-ink-black/45">
              CHECKPOINT
            </span>
            <span className="font-body text-ink-black/78">{stageLabel}</span>
          </div>
          <div className="flex items-center justify-between text-[0.66rem]">
            <span className="font-meta tracking-[0.16em] text-ink-black/45">
              SPEND
            </span>
            <span className="font-body text-ink-black/78 tabular-nums">
              ${project.total_cost_usd.toFixed(2)}
            </span>
          </div>
        </div>

        <Link
          to={`/project/${encodeURIComponent(project.name)}`}
          className="mt-3 block border-[2px] border-ink-black bg-hero-red px-4 py-2 text-center font-meta text-[0.62rem] tracking-[0.16em] text-bristol hover:opacity-90"
        >
          OPEN FILE
        </Link>
      </div>
    </Card>
  );
}
