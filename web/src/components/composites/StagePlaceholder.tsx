import { useMemo, type ReactNode } from "react";
import { STAGE_ORDER, type StageName, type StageStatus } from "../../types/api";
import { usePipelineStore } from "../../store/pipeline";
import { useNeedsCredits } from "../../hooks/useNeedsCredits";
import { useRunAction } from "../../hooks/useRunAction";
import { Icon } from "../ui/Icon";
import { Button } from "../ui/Button";
import { CreditsGate } from "./CreditsGate";
import { useI18n } from "../../i18n";

// ── Stage metadata ────────────────────────────────────────────────────────────

interface StageMeta {
  label: string;
  title: string;
  description: string;
  inputs: string[];
  outputs: string[];
}

const STAGE_META: Record<StageName, StageMeta> = {
  extract: {
    label: "EXTRACT",
    title: "Story Bible",
    description: "Parses the source text into a structured bible — characters, locations, scenes, arcs, and props.",
    inputs: ["Source text"],
    outputs: ["Characters", "Locations", "Scenes", "Arcs"],
  },
  brief: {
    label: "BRIEF",
    title: "Adaptation Brief",
    description: "Sets the story promises, tone, emphasis, and approved target page range for the whole book.",
    inputs: ["Story Bible", "Source text"],
    outputs: ["Approved adaptation brief"],
  },
  style: {
    label: "LOOK & FEEL",
    title: "Visual Style",
    description: "Creates visual direction options and sample artwork so the comic has a consistent look before casting.",
    inputs: ["Story bible"],
    outputs: ["Style options", "Sample art"],
  },
  cast: {
    label: "CAST",
    title: "Visual Casting",
    description: "Generates reference images for each character and location extracted from the story bible.",
    inputs: ["Story bible"],
    outputs: ["Character refs", "Location plates"],
  },
  adapt: {
    label: "ADAPT",
    title: "Book Adaptation",
    description: "Creates one source-accounted book adaptation with complete lettering and a narrative treatment.",
    inputs: ["Approved brief", "Story bible"],
    outputs: ["Book adaptation"],
  },
  plan: {
    label: "PLAN",
    title: "Page Plan",
    description: "Allocates the complete adaptation into canonical pages, spreads, page turns, and reading order.",
    inputs: ["Book adaptation", "Approved references"],
    outputs: ["Canonical pages"],
  },
  draw: {
    label: "DRAW",
    title: "Complete Pages",
    description: "Generates one fully lettered page revision at a time and records review evidence.",
    inputs: ["Canonical pages", "Approved references"],
    outputs: ["Page renders", "Page issues"],
  },
  finish: {
    label: "FINISH",
    title: "Finish Preflight",
    description: "Verifies the completed book, normalizes production files, and creates export packages.",
    inputs: ["Complete page renders", "Page issues"],
    outputs: ["Preflight", "PDF", "CBZ"],
  },
};

function StageDocket({
  stage,
  state,
  tone,
  children,
}: {
  stage: StageName;
  state: string;
  tone: "muted" | "running" | "failed";
  children?: ReactNode;
}) {
  const { t } = useI18n();
  const meta = STAGE_META[stage];
  const stageNumber = String(STAGE_ORDER.indexOf(stage) + 1).padStart(2, "0");
  const plateClass = tone === "running"
    ? "bg-narrator-gold text-ink-black"
    : tone === "failed"
      ? "bg-hero-red text-bristol"
      : "bg-ink-black text-bristol";

  return (
    <div className="flex min-h-[50vh] items-center justify-center px-2 py-8 sm:px-6">
      <article className="grid w-full max-w-[760px] overflow-hidden border-[3px] border-ink-black bg-bristol shadow-paper md:grid-cols-[150px_minmax(0,1fr)]">
        <div className={`relative flex min-h-32 flex-col items-center justify-center px-5 py-6 text-center md:min-h-full ${plateClass}`}>
          <div className="font-display text-[2.5rem] font-black leading-none tracking-[-0.03em]">
            {stageNumber}
          </div>
          <div className="mt-3 font-meta text-[0.58rem] font-bold uppercase tracking-[0.12em] opacity-75">
            {t(meta.label)}
          </div>
          {tone === "running" && (
            <span aria-hidden="true" className="animate-press-blink absolute right-3 top-3 h-3 w-3 bg-hero-red" />
          )}
        </div>

        <div className="p-6 sm:p-8">
          <div className="font-meta text-[0.58rem] font-bold uppercase tracking-[0.1em] text-hero-red">
            {t(state)}
          </div>
          <h2 className="mt-2 font-display text-[2rem] font-black uppercase leading-[0.92] tracking-[-0.035em] text-ink-black">
            {t(meta.title)}
          </h2>
          <p className="mt-4 max-w-[58ch] font-body text-[0.9rem] font-semibold leading-7 text-ink-muted">
            {t(meta.description)}
          </p>
          {children}
        </div>
      </article>
    </div>
  );
}

// ── Pending state ─────────────────────────────────────────────────────────────

interface StagePendingProps {
  stage: StageName;
}

export function StagePending({ stage }: StagePendingProps) {
  const { t } = useI18n();
  const meta = STAGE_META[stage];

  return (
    <StageDocket stage={stage} state="WAITING IN THE PRODUCTION LINE" tone="muted">
      <div className="mt-6 grid gap-3 bg-surface-container p-4 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
          <div>
            <div className="mb-2 font-meta text-[0.54rem] font-bold uppercase tracking-[0.08em] text-ink-muted">{t("Receives")}</div>
            {meta.inputs.map((input) => (
              <div key={input} className="font-body text-[0.8rem] font-bold text-ink-black">
                {t(input)}
              </div>
            ))}
          </div>
          <div className="hidden h-9 w-9 items-center justify-center bg-narrator-gold sm:flex">
            <Icon name="arrow-right" size={16} className="text-ink-black" />
          </div>
          <div>
            <div className="mb-2 font-meta text-[0.54rem] font-bold uppercase tracking-[0.08em] text-ink-muted">{t("Produces")}</div>
            {meta.outputs.map((output) => (
              <div key={output} className="font-body text-[0.8rem] font-bold text-ink-black">
                {t(output)}
              </div>
            ))}
          </div>
      </div>
    </StageDocket>
  );
}

// ── Running state ─────────────────────────────────────────────────────────────

interface StageRunningProps {
  stage: StageName;
  itemsDone?: number;
  itemsTotal?: number;
}

export function StageRunning({ stage, itemsDone = 0, itemsTotal = 0 }: StageRunningProps) {
  const { t } = useI18n();
  const meta = STAGE_META[stage];
  const hasProgress = itemsTotal > 0;
  const pct = hasProgress ? Math.round((itemsDone / itemsTotal) * 100) : 0;

  // Live ticker: the last few human-readable log lines the pipeline emitted
  // for this stage over SSE. Error lines are excluded — failures have their
  // own surfacing.
  const events = usePipelineStore((s) => s.events);
  const logLines = useMemo(() => {
    const lines: { key: number; message: string }[] = [];
    events.forEach((event, index) => {
      if (
        event.type === "log" &&
        event.stage === stage &&
        typeof event.message === "string" &&
        event.message.length > 0 &&
        (event.level == null || event.level === "info" || event.level === "dim" || event.level === "bold")
      ) {
        lines.push({ key: index, message: event.message });
      }
    });
    return lines.slice(-3);
  }, [events, stage]);

  return (
    <StageDocket stage={stage} state="RUNNING" tone="running">
        <div className="mt-7">
          <div className="mb-2 flex items-center justify-between font-meta text-[0.62rem] font-bold tracking-[0.08em] text-ink-muted">
            <span>{hasProgress ? `${itemsDone} / ${itemsTotal}` : t("STARTING…")}</span>
            {hasProgress && <span>{pct}%</span>}
          </div>
          <div
            className="h-3 w-full overflow-hidden border-[2px] border-ink-black bg-pulp-paper"
            role="progressbar"
            aria-label={`${t(meta.title)} ${t("progress")}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={hasProgress ? pct : undefined}
          >
            <div
              className="h-full bg-hero-red transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
              style={{ width: hasProgress ? `${Math.max(4, pct)}%` : "0%" }}
            />
          </div>
          {logLines.length > 0 && (
            <div className="mt-3 space-y-1" aria-live="polite">
              {logLines.map((line, index) => (
                <div
                  key={line.key}
                  className={`animate-ticker-rise truncate font-body text-[0.75rem] font-semibold ${
                    index === logLines.length - 1 ? "text-ink-black" : "text-ink-muted"
                  }`}
                >
                  {line.message}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          {meta.outputs.map((output) => (
            <div
              key={output}
              className="border-[2px] border-ink-black/12 bg-surface-container px-3 py-1.5 font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-muted"
            >
              {t(output).toUpperCase()}
            </div>
          ))}
        </div>
    </StageDocket>
  );
}

// ── Failed state ──────────────────────────────────────────────────────────────

interface StageFailedProps {
  project: string;
  stage: StageName;
}

function StageFailed({ project, stage }: StageFailedProps) {
  const { t } = useI18n();
  const { handleRun, isPending } = useRunAction();
  return (
    <StageDocket stage={stage} state="PRESS STOPPED" tone="failed">
        <p className="mt-5 font-body text-[0.86rem] font-semibold leading-6 text-ink-muted">
          {t("This stage didn't complete. Try running it again.")}
        </p>
        <div className="mt-5 flex">
          <Button
            size="md"
            disabled={isPending}
            onClick={() => handleRun(project, stage)}
          >
            {isPending ? t("Starting…") : t("Retry stage")}
          </Button>
        </div>
    </StageDocket>
  );
}

// ── Combined switcher ─────────────────────────────────────────────────────────

interface StagePlaceholderProps {
  project: string;
  stage: StageName;
  status: StageStatus;
  itemsDone?: number;
  itemsTotal?: number;
}

export function StagePlaceholder({ project, stage, status, itemsDone, itemsTotal }: StagePlaceholderProps) {
  const { t } = useI18n();
  // Credit gate takes priority over every other placeholder state — a user
  // blocked on credits should never see "WAITING FOR PIPELINE" or a fake
  // running flash. Covers both the persisted credit-failure case (survives
  // reload) and the heuristic 0-credit-new-user case.
  const needsCredits = useNeedsCredits(project, stage);
  if (needsCredits.blocked) {
    return (
      <CreditsGate
        project={project}
        stage={stage}
        stageLabel={t(STAGE_META[stage].title)}
        balance={needsCredits.balance}
        required={needsCredits.required}
        shortfall={needsCredits.shortfall}
        reason={needsCredits.reason}
      />
    );
  }

  if (status === "running") {
    return <StageRunning stage={stage} itemsDone={itemsDone} itemsTotal={itemsTotal} />;
  }
  if (status === "pending") {
    return <StagePending stage={stage} />;
  }
  if (status === "failed") {
    return <StageFailed project={project} stage={stage} />;
  }
  // Stage completed but no data — shouldn't normally happen; show a minimal
  // state while the data loads.
  return (
    <StageDocket stage={stage} state="PROOF UNAVAILABLE" tone="muted">
        <p className="mt-5 font-body text-[0.86rem] font-semibold leading-6 text-ink-muted">
          {t("Data for this stage could not be loaded.")}
        </p>
    </StageDocket>
  );
}
