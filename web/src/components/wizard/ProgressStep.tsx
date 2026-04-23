import { Card } from "../ui/Card";
import { SectionLabel } from "../SectionLabel";
import type { PipelineEvent, StageName } from "../../types/api";
import { STAGE_DISPLAY_NAMES } from "../../types/api";
import { redactDevText, useShowDevContent } from "../../lib/devContent";

const STAGE_DESCRIPTIONS: Record<StageName, string> = {
  extract: "Reading your novel and building the story bible — characters, locations, scenes, and narrative arcs.",
  index: "Generating character reference sheets and location background plates from the story bible.",
  screenplay: "Converting scene prose into screenplay format with dialogue, action, and direction beats.",
  "layout-plan": "Planning canonical comic structure from screenplay beats — panel importance, shape intent, and page assignment.",
  panels: "Breaking screenplays into individual panel descriptions — shot types, camera angles, and compositions.",
  prompts: "Assembling image generation prompts from panel descriptions, character anchors, and location references.",
  generate: "Drawing every panel — the longest stage. Each image is generated from its assembled prompt.",
  assemble: "Compositing panels into comic pages with speech bubbles, narration, and SFX overlays.",
};

interface ProgressStepProps {
  stage: StageName;
  done: number;
  total: number;
  events?: PipelineEvent[];
}

const EXTRACT_STEPS = [
  "Novel text loaded",
  "Extraction instructions prepared",
  "Story bible drafted",
  "Project files written",
];

const STAGE_STEPS: Partial<Record<StageName, string[]>> = {
  extract: EXTRACT_STEPS,
  index: [
    "Scene search index",
    "Character reference sheets",
    "Location plates",
    "Cast ready for review",
  ],
  generate: [
    "Prompt list prepared",
    "Panel batches running",
    "Images saved",
    "Draw review ready",
  ],
};

function humanizeEventMessage(message: string) {
  return message
    .replace(/\/[^\s"'`]+/g, (match) => {
      const fileName = match.split("/").filter(Boolean).at(-1);
      return fileName ? `artifact ${fileName}` : "project artifact";
    })
    .replace(/[A-Za-z]:\\[^\s"'`]+/g, (match) => {
      const fileName = match.split("\\").filter(Boolean).at(-1);
      return fileName ? `artifact ${fileName}` : "project artifact";
    });
}

function eventMessageForDisplay(message: string, showDevContent: boolean) {
  return showDevContent ? message : redactDevText(humanizeEventMessage(message));
}

function milestoneState(stage: StageName, index: number, count: number, done: number, total: number) {
  if (stage === "extract") {
    if (done > index) return "done";
    if (done === index && done < total) return "running";
    return "pending";
  }

  if (total <= 0) {
    return index === 0 ? "running" : "pending";
  }

  if (done >= total) return "done";
  const progress = done / total;
  const start = index / count;
  const end = (index + 1) / count;
  if (progress >= end) return "done";
  if (progress >= start) return "running";
  return "pending";
}

export function ProgressStep({ stage, done, total, events = [] }: ProgressStepProps) {
  const [showDevContent] = useShowDevContent();
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const isIndeterminate = total === 0 || done < total;
  const visualPct = isIndeterminate ? Math.max(pct, 8) : pct;
  const milestones = STAGE_STEPS[stage] ?? [];
  const recentLogs = events
    .filter((event) => event.stage === stage && event.type === "log" && event.message)
    .slice(-4)
    .reverse();
  const currentActivity =
    (recentLogs[0]?.message ? eventMessageForDisplay(recentLogs[0].message, showDevContent) : null) ??
    (stage === "extract" ? "Preparing extraction run..." : STAGE_DESCRIPTIONS[stage]);

  return (
    <Card className="p-5 md:p-6">
      <SectionLabel tone="gold">PIPELINE RUNNING</SectionLabel>
      <div className="mt-4 flex items-baseline gap-3">
        <h1 className="display-headline">{STAGE_DISPLAY_NAMES[stage]}</h1>
        <span className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50 animate-pulse">
          PROCESSING…
        </span>
      </div>
      <p className="mt-4 text-[0.88rem] text-ink-black/65 leading-relaxed max-w-[52ch]">
        {STAGE_DESCRIPTIONS[stage]}
      </p>

      <div className="mt-5 border-[2px] border-ink-black bg-bristol p-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 animate-pulse bg-hero-red" />
          <span className="font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/55">
            CURRENT ACTIVITY
          </span>
        </div>
        <div className="mt-2 font-display text-[1rem] font-bold tracking-[-0.04em] text-ink-black">
          {currentActivity}
        </div>
      </div>

      <div className="mt-6">
        <div className="flex justify-between mb-1">
          <span className="font-meta text-[0.46rem] tracking-[0.14em] text-ink-black/50">
            PROGRESS
          </span>
          <span className="font-meta text-[0.46rem] tracking-[0.14em] text-ink-black/50">
            {done}/{total} ({pct}%)
          </span>
        </div>
        <div className="h-3 border-[2px] border-ink-black bg-pulp-paper">
          <div
            className={`h-full bg-narrator-gold transition-all duration-300 ${
              isIndeterminate ? "animate-pulse" : ""
            }`}
            style={{ width: `${visualPct}%` }}
          />
        </div>
      </div>

      {milestones.length > 0 && (
        <div className="mt-5 grid gap-2 sm:grid-cols-4">
          {milestones.map((label, index) => {
            const state = milestoneState(stage, index, milestones.length, done, total);
            return (
              <div
                key={label}
                className={`border-[2px] border-ink-black p-2 ${
                  state === "done"
                    ? "bg-archive-sage text-bristol"
                    : state === "running"
                      ? "bg-narrator-gold text-ink-black"
                      : "bg-pulp-paper text-ink-black/45"
                }`}
              >
                <div className="font-meta text-[0.42rem] tracking-[0.14em]">
                  {state === "done" ? "DONE" : state === "running" ? "RUNNING" : "WAITING"}
                </div>
                <div className="mt-1 font-body text-[0.7rem] leading-tight">
                  {label}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {recentLogs.length > 1 && (
        <div className="mt-4 space-y-1">
          {recentLogs.slice(1).map((event, index) => (
            <div key={`${event.message}-${index}`} className="font-meta text-[0.46rem] tracking-[0.12em] text-ink-black/40">
              {eventMessageForDisplay(event.message ?? "", showDevContent)}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
