import { useMemo, useState, type ReactNode } from "react";
import { type StageName, type StageStatus } from "../../types/api";
import { useStageEstimate } from "../../api/queries";
import { STATIONS } from "../../lib/stations";
import { CreditAmount } from "../ui/CreditAmount";
import { ConfirmDrawer } from "./ConfirmDrawer";
import { RerunDrawer } from "./RerunDrawer";
import { RERUN_IMPACT } from "../../lib/rerunImpact";
import { usePipelineStore } from "../../store/pipeline";
import { useNeedsCredits } from "../../hooks/useNeedsCredits";
import { useRunAction } from "../../hooks/useRunAction";
import { Icon } from "../ui/Icon";
import { Button } from "../ui/Button";
import { CreditsGate } from "./CreditsGate";
import { useI18n } from "../../i18n";

// ── Stage metadata ────────────────────────────────────────────────────────────

interface StageMeta {
  nextDecision: string;
  title: string;
  description: string;
  inputs: string[];
  outputs: string[];
}

const STAGE_META: Record<StageName, StageMeta> = {
  extract: {
    nextDecision: "Next, review the story outline and decide what your adaptation must preserve.",
    title: "Reading your story",
    description: "Finds the characters, places, and key scenes in your manuscript.",
    inputs: ["Source text"],
    outputs: ["Characters", "Places", "Story outline"],
  },
  brief: {
    nextDecision: "Next, approve the story brief before choosing the look of your book.",
    title: "Preparing your story brief",
    description: "Sets out the tone, essential moments, and suggested page range for your review.",
    inputs: ["Story outline", "Source text"],
    outputs: ["Story brief to review"],
  },
  style: {
    nextDecision: "Next, compare the visual proofs and choose your style. Drawing waits for your approval.",
    title: "Making visual proofs",
    description: "Creates sample artwork from your story so you can choose a consistent look.",
    inputs: ["Story brief"],
    outputs: ["Style options", "Sample art"],
  },
  cast: {
    nextDecision: "Next, review your characters and places before the book is planned.",
    title: "Drawing characters and places",
    description: "Creates reference artwork to keep characters and places recognizable throughout your book.",
    inputs: ["Story outline", "Selected style"],
    outputs: ["Character references", "Place references"],
  },
  adapt: {
    nextDecision: "Page planning follows automatically. You will choose when to start drawing.",
    title: "Adapting your story",
    description: "Shapes your approved story into comic scenes, dialogue, and captions.",
    inputs: ["Approved brief", "Story outline"],
    outputs: ["Comic script"],
  },
  plan: {
    nextDecision: "Next, review the page plan and choose how to draw your pages.",
    title: "Planning your pages",
    description: "Arranges scenes, dialogue, spreads, and page turns into your book's reading order.",
    inputs: ["Comic script", "Approved references"],
    outputs: ["Page plan"],
  },
  draw: {
    nextDecision: "Next, review the artwork and flagged issues. A new revision still needs your review.",
    title: "Drawing your pages",
    description: "Draws complete comic pages with dialogue and captions, then checks the lettering.",
    inputs: ["Page plan", "Approved references"],
    outputs: ["Lettered pages", "Issues to review"],
  },
  finish: {
    nextDecision: "Next, read your book, resolve any remaining decisions, and create a PDF or CBZ.",
    title: "Checking your edition",
    description: "Checks page files, lettering, and reading order before packaging. Artwork is never changed here.",
    inputs: ["Lettered pages", "Review decisions"],
    outputs: ["Edition checks", "Downloadable book"],
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
  const station = STATIONS.find((item) => item.substeps.some((step) => step.backendStages.includes(stage)))!;
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
            {station.number}
          </div>
          <div className="mt-3 font-meta text-xs font-bold uppercase tracking-[0.08em]">
            {t("Station")} · {t(station.label)}
          </div>
        </div>

        <div className="p-6 sm:p-8">
          <div className="font-meta text-xs font-bold uppercase tracking-[0.08em] text-hero-red">
            {t(state)}
          </div>
          <h2 className="mt-2 font-display text-[2rem] font-black uppercase leading-[0.92] tracking-[-0.035em] text-ink-black">
            {t(meta.title)}
          </h2>
          <p className="mt-4 max-w-[58ch] font-body text-[0.9rem] font-semibold leading-7 text-ink-muted">
            {t(meta.description)}
          </p>
          {children}
          <p className="mt-5 font-body text-sm font-semibold leading-6 text-ink-black">
            {t(meta.nextDecision)}
          </p>
        </div>
      </article>
    </div>
  );
}

// ── Pending state ─────────────────────────────────────────────────────────────

interface StagePendingProps {
  project: string;
  stage: StageName;
  allowStart: boolean;
}

function StageStartAction({
  project,
  stage,
  retry = false,
  rerun = false,
}: {
  project: string;
  stage: StageName;
  retry?: boolean;
  rerun?: boolean;
}) {
  const { t } = useI18n();
  const { handleRun, isPending } = useRunAction();
  const estimate = useStageEstimate(project, stage);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const actionLabel = rerun
    ? t("Restart this step")
    : retry
      ? t("Retry stage")
      : stage === "extract" ? t("Start Story analysis") : t("Start this step");
  const unavailable = isPending || !estimate.data || estimate.isError || estimate.isFetching;

  function confirmStart() {
    if (unavailable) return;
    setStartError(null);
    handleRun(project, stage, {
      rerun,
      actionLabel,
      onSuccess: () => setConfirmOpen(false),
      onError: (error) => {
        setStartError(error.message);
        setConfirmOpen(false);
      },
    });
  }

  return (
    <div className="mt-5 space-y-3">
      {estimate.isError ? (
        <div role="alert" className="font-body text-sm">
          <p>{t("The estimate could not be loaded. No work has started.")}</p>
          <Button className="mt-2" variant="outline" disabled={estimate.isFetching} onClick={() => void estimate.refetch()}>
            {estimate.isFetching ? t("Loading estimate…") : t("Retry estimate")}
          </Button>
        </div>
      ) : estimate.data ? (
        <p className="font-body text-sm">
          <CreditAmount value={estimate.data.estimate_credits} approximate label={t("credits")} />
          {estimate.data.reserved_credits != null && (
            <> · {t("Temporary hold")}: <CreditAmount value={estimate.data.reserved_credits} label={t("credits")} /></>
          )}
        </p>
      ) : <p role="status" className="font-body text-sm">{t("Loading estimate…")}</p>}
      <Button disabled={unavailable} onClick={() => setConfirmOpen(true)}>
        {isPending ? t("Starting…") : actionLabel}
      </Button>
      {startError && <p role="alert" className="font-body text-sm text-hero-red">{startError}</p>}
      {rerun ? (
        <RerunDrawer
          open={confirmOpen}
          stageName={t(STAGE_META[stage].title)}
          impactStages={RERUN_IMPACT[stage].downstream}
          cost={estimate.data}
          confirmLabel={actionLabel}
          busy={unavailable}
          onClose={() => setConfirmOpen(false)}
          onConfirm={confirmStart}
        />
      ) : (
        <ConfirmDrawer
          open={confirmOpen}
          title={actionLabel}
          body={stage === "extract"
            ? t("Analyze your manuscript and prepare a story brief. You will review it before choosing a style or drawing pages.")
            : t(STAGE_META[stage].description)}
          cost={estimate.data}
          confirmLabel={actionLabel}
          busy={unavailable}
          onClose={() => setConfirmOpen(false)}
          onConfirm={confirmStart}
        />
      )}
    </div>
  );
}

export function StagePending({ project, stage, allowStart }: StagePendingProps) {
  const { t } = useI18n();
  const meta = STAGE_META[stage];
  return (
    <StageDocket stage={stage} state="WAITING IN THE PRODUCTION LINE" tone="muted">
      <div className="mt-6 grid gap-3 bg-surface-container p-4 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
        <div>
          <div className="mb-2 font-meta text-xs font-bold uppercase text-ink-muted">{t("Starts with")}</div>
          {meta.inputs.map((input) => (
            <div key={input} className="font-body text-[0.8rem] font-bold text-ink-black">{t(input)}</div>
          ))}
        </div>
        <div className="hidden h-9 w-9 items-center justify-center bg-narrator-gold sm:flex">
          <Icon name="arrow-right" size={16} className="text-ink-black" />
        </div>
        <div>
          <div className="mb-2 font-meta text-xs font-bold uppercase text-ink-muted">{t("You will receive")}</div>
          {meta.outputs.map((output) => (
            <div key={output} className="font-body text-[0.8rem] font-bold text-ink-black">{t(output)}</div>
          ))}
        </div>
      </div>
      {allowStart && <StageStartAction project={project} stage={stage} />}
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
  const pct = hasProgress
    ? Math.min(100, Math.max(0, Math.round((itemsDone / itemsTotal) * 100)))
    : 0;

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
          <div className="mb-2 flex items-center justify-between font-meta text-xs font-bold text-ink-muted">
            <span>{hasProgress ? `${itemsDone} / ${itemsTotal}` : t("Working; no completed count yet.")}</span>
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
              className="h-full origin-left bg-hero-red transition-transform duration-[220ms]"
              style={{ transform: `scaleX(${hasProgress ? pct / 100 : 0})` }}
            />
          </div>
          {logLines.length > 0 && (
            <details className="mt-4">
              <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold">{t("Activity details")}</summary>
              <div className="space-y-1">
              {logLines.map((line, index) => (
                <div
                  key={line.key}
                  className={`break-words font-body text-xs font-semibold leading-5 ${
                    index === logLines.length - 1 ? "text-ink-black" : "text-ink-muted"
                  }`}
                >
                  {line.message}
                </div>
              ))}
              </div>
            </details>
          )}
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          {meta.outputs.map((output) => (
            <div
              key={output}
              className="bg-surface-container px-3 py-2 font-meta text-xs font-bold text-ink-muted"
            >
              {t(output).toUpperCase()}
            </div>
          ))}
        </div>
    </StageDocket>
  );
}

// ── Failed and unavailable states ────────────────────────────────────────────

interface StageFailedProps {
  project: string;
  stage: StageName;
  rerun: boolean;
  error?: string | null;
  errorDetail?: string | null;
}

function StageFailed({ project, stage, rerun, error, errorDetail }: StageFailedProps) {
  const { t } = useI18n();
  return (
    <StageDocket stage={stage} state="PRESS STOPPED" tone="failed">
      <p className="mt-5 font-body text-[0.86rem] font-semibold leading-6 text-ink-muted">
        {error || t("This stage didn't complete. Try running it again.")}
      </p>
      {errorDetail && (
        <details className="mt-4 border-[2px] border-ink-black/15 bg-surface-container p-3">
          <summary className="cursor-pointer font-meta text-[0.62rem] font-bold tracking-[0.08em]">
            {t("TECHNICAL DETAILS")}
          </summary>
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[0.7rem] leading-5 text-ink-black/80">
            {errorDetail}
          </pre>
        </details>
      )}
      <StageStartAction project={project} stage={stage} retry rerun={rerun} />
    </StageDocket>
  );
}

function StageLoadError({ stage, message }: { stage: StageName; message: string }) {
  const { t } = useI18n();
  return (
    <StageDocket stage={stage} state="COULD NOT LOAD" tone="failed">
      <p className="mt-5 font-body text-[0.86rem] font-semibold leading-6 text-ink-muted">
        {t("This step could not be loaded. Your saved work has not been changed.")}
      </p>
      <details className="mt-4 border-[2px] border-ink-black/15 bg-surface-container p-3">
        <summary className="cursor-pointer font-meta text-[0.62rem] font-bold tracking-[0.08em]">
          {t("ERROR DETAILS")}
        </summary>
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[0.7rem] leading-5 text-ink-black/80">
          {message}
        </pre>
      </details>
    </StageDocket>
  );
}

// ── Combined switcher ─────────────────────────────────────────────────────────

interface StagePlaceholderProps {
  project: string;
  stage: StageName;
  status: StageStatus;
  stale?: boolean;
  itemsDone?: number;
  itemsTotal?: number;
  retryAsRerun?: boolean;
  allowPendingStart?: boolean;
  error?: string | null;
  errorDetail?: string | null;
  loadError?: string | null;
}

export function StagePlaceholder({
  project,
  stage,
  status,
  stale = false,
  itemsDone,
  itemsTotal,
  retryAsRerun = false,
  allowPendingStart = false,
  error,
  errorDetail,
  loadError,
}: StagePlaceholderProps) {
  const { t } = useI18n();
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
  if (status === "failed" || stale) {
    return (
      <StageFailed
        project={project}
        stage={stage}
        rerun={retryAsRerun}
        error={error}
        errorDetail={errorDetail}
      />
    );
  }
  if (loadError) {
    return <StageLoadError stage={stage} message={loadError} />;
  }
  if (status === "running" && !stale) {
    return <StageRunning stage={stage} itemsDone={itemsDone} itemsTotal={itemsTotal} />;
  }
  if (status === "pending") {
    return (
      <StagePending
        project={project}
        stage={stage}
        allowStart={allowPendingStart}
      />
    );
  }
  if (status === "awaiting_review") {
    return (
      <StageDocket stage={stage} state="AWAITING REVIEW" tone="muted">
        <p className="mt-5 font-body text-[0.86rem] font-semibold leading-6 text-ink-muted">
          {t("This stage completed and is waiting for the next review step.")}
        </p>
      </StageDocket>
    );
  }
  return (
    <StageDocket stage={stage} state="PROOF UNAVAILABLE" tone="muted">
      <p className="mt-5 font-body text-[0.86rem] font-semibold leading-6 text-ink-muted">
        {t("Data for this stage could not be loaded.")}
      </p>
    </StageDocket>
  );
}
