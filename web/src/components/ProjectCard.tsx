import { Link } from "react-router-dom";
import type { ProjectSummary, StageStatus } from "../types/api";
import { STAGE_DISPLAY_NAMES, STAGE_ORDER } from "../types/api";
import { Card } from "./ui/Card";
import { Tag } from "./ui/Tag";

interface Props {
  project: ProjectSummary;
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

export function ProjectCard({ project }: Props) {
  const furthest = project.furthest_stage
    ? STAGE_ORDER.indexOf(project.furthest_stage as (typeof STAGE_ORDER)[number]) + 1
    : 0;
  const status = resolveStatus(project);
  const stageLabel = project.furthest_stage
    ? STAGE_DISPLAY_NAMES[project.furthest_stage as (typeof STAGE_ORDER)[number]]
    : "ARCHIVE";

  return (
    <Card className="transition-transform duration-150 hover:-translate-y-[2px]">
      <div className="border-b-[2px] border-ink-black p-2">
        <div className="relative border-[2px] border-ink-black bg-preview-tint p-2">
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

          <div className="grid aspect-[4/5] grid-rows-[1.1fr_0.9fr] gap-2">
            <div className="border border-ink-black bg-ink-black" />
            <div className="grid grid-cols-[1.1fr_0.9fr] gap-2">
              <div className="border border-ink-black bg-[#d7d0c1]" />
              <div className="grid gap-2">
                <div className="border border-ink-black bg-bristol" />
                <div className="border border-ink-black bg-hero-red" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="p-3">
        {project.furthest_stage && (
          <div className="mb-1 font-meta text-[0.48rem] tracking-[0.18em] text-ink-black/45">
            STAGE: {stageLabel}
          </div>
        )}
        <h3 className="font-display text-[1.85rem] font-bold leading-none tracking-[-0.05em] text-ink-black">
          {project.project_name}
        </h3>
        <p className="mt-2 text-[0.78rem] leading-6 text-ink-black/72">
          Stage dossier, live pipeline telemetry, and issue progression for this board.
        </p>

        <div className="mt-4 space-y-2 border-t-[2px] border-ink-black pt-3">
          <div className="flex items-center justify-between text-[0.66rem]">
            <span className="font-meta tracking-[0.16em] text-ink-black/45">
              OPENED
            </span>
            <span className="font-body text-ink-black/78">
              {formatCreated(project.created_at)}
            </span>
          </div>
          <div className="flex items-center justify-between text-[0.66rem]">
            <span className="font-meta tracking-[0.16em] text-ink-black/45">
              PROGRESS
            </span>
            <span className="font-body text-ink-black/78">{furthest}/7</span>
          </div>
          <div className="flex items-center justify-between text-[0.66rem]">
            <span className="font-meta tracking-[0.16em] text-ink-black/45">
              COST SO FAR
            </span>
            <span className="font-body text-ink-black/78">
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
