import { useNow } from "../../hooks/useNow";
import { Link } from "react-router-dom";
import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { type GenerationJob, type StageName, type StageSnapshot, type StageStatus } from "../../types/api";
import { getStageQueue, type StageQueue } from "../../lib/stageQueue";
import { Clock3, LoaderCircle } from "lucide-react";
import { PlanProgressBoard } from "./PlanProgressBoard";
import { AdaptProgressBoard } from "./AdaptProgressBoard";
import { useProjectConfig, useUpdateProjectConfig, useStageEstimate } from "../../api/queries";
import { STATIONS } from "../../lib/stations";
import { CreditAmount } from "../ui/CreditAmount";
import { ConfirmDrawer } from "./ConfirmDrawer";
import { AdaptRestartDrawer } from "./AdaptRestartDrawer";
import { RerunDrawer } from "./RerunDrawer";
import { RERUN_IMPACT } from "../../lib/rerunImpact";
import { usePipelineStore } from "../../store/pipeline";
import { useNeedsCredits } from "../../hooks/useNeedsCredits";
import { useRunAction } from "../../hooks/useRunAction";
import { Icon } from "../ui/Icon";
import { Button } from "../ui/Button";
import { CreditsGate } from "./CreditsGate";
import { useI18n } from "../../i18n";

const ProjectModelControls = import.meta.env.DEV ? lazy(() => import("../wizard/ProjectModelControls")) : null;

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
  failureTitle,
}: {
  failureTitle?: string;
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
      ? "bg-surface-container text-ink-black"
      : "bg-ink-black text-bristol";

  return (
    <div className="flex min-h-[50vh] items-center justify-center px-2 py-8 sm:px-6">
      <article className="grid w-full max-w-[760px] overflow-hidden border-[3px] border-ink-black bg-bristol shadow-paper md:grid-cols-[150px_minmax(0,1fr)]">
        <div className={`relative flex min-h-32 flex-col items-center justify-center px-5 py-6 text-center md:min-h-full ${plateClass}`}>
          <div className="font-meta text-[0.54rem] font-bold uppercase leading-none tracking-[0.14em] opacity-70">
            {t("Station")}
          </div>
          <div className="mt-1.5 font-display text-[2.5rem] font-black leading-none tracking-[-0.03em]">
            {station.number}
          </div>
          <div className="mt-2 font-meta text-xs font-bold uppercase leading-none tracking-[0.08em]">
            {t(station.label)}
          </div>
        </div>

        <div className="min-w-0 p-6 sm:p-8">
          {tone !== "failed" && <div className="font-meta text-xs font-bold uppercase tracking-[0.08em] text-hero-red">
            {t(state)}
          </div>}
          <h2 className="mt-2 font-display text-[2rem] font-black uppercase leading-[0.92] tracking-[-0.035em] text-ink-black">
            {failureTitle ?? t(meta.title)}
          </h2>
          <p className="mt-4 font-body text-[0.9rem] font-semibold leading-7 text-ink-muted">
            {t(meta.description)}
          </p>
          {children}
          {tone !== "failed" && <p className="mt-5 font-body text-sm font-semibold leading-6 text-ink-black">
            {t(meta.nextDecision)}
          </p>}
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

export function StageStartAction({
  project,
  stage,
  retry = false,
  rerun = false,
  disabled = false,
  allowRestart = true,
  layout = "card",
  secondaryAction,
}: {
  project: string;
  stage: StageName;
  retry?: boolean;
  rerun?: boolean;
  disabled?: boolean;
  allowRestart?: boolean;
  layout?: "card" | "footer";
  secondaryAction?: ReactNode;
}) {
  const { t } = useI18n();
  const { handleRun, isPending } = useRunAction();
  const [restartOpen, setRestartOpen] = useState(false);
  const freshStart = stage === "adapt" && (rerun || restartOpen);
  const estimate = useStageEstimate(project, stage, true, freshStart);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const actionLabel = freshStart ? t("Start adaptation over") : rerun
    ? t("Restart this step")
    : retry
      ? stage === "adapt" ? t("Resume adaptation") : t("Retry stage")
      : stage === "extract" ? t("Start Story analysis") : t("Start this step");
  const unavailable = disabled || isPending || !estimate.data || estimate.isError || estimate.isFetching;

  function closeConfirmation() {
    if (isPending) return;
    setConfirmOpen(false);
    setRestartOpen(false);
  }

  function confirmStart() {
    if (unavailable) return;
    setStartError(null);
    handleRun(project, stage, {
      rerun: rerun || freshStart,
      actionLabel,
      onSuccess: () => { setConfirmOpen(false); setRestartOpen(false); },
      onError: (error) => {
        setStartError(error.message);
        setConfirmOpen(false);
        setRestartOpen(false);
      },
    });
  }

  return (
    <div className={layout === "footer" ? "flex min-w-0 w-full flex-wrap items-center gap-3" : "mt-5 space-y-3"}>
      <div className={layout === "footer" ? "min-w-0 flex-1 basis-full sm:basis-64 [overflow-wrap:anywhere]" : undefined}>
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
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <Button size={layout === "footer" ? "sm" : "md"} disabled={unavailable} onClick={() => setConfirmOpen(true)}>
          {isPending ? t("Starting…") : restartOpen ? t("Resume adaptation") : actionLabel}
        </Button>
        {secondaryAction}
      </div>
      {retry && stage === "adapt" && !rerun && allowRestart && (
        <div className="border-t border-ink-black/20 pt-4">
          <p className="mb-3 font-body text-sm text-ink-muted">{t("Prefer a fresh script? Start over from your approved inputs.")}</p>
          <Button variant="outline" disabled={disabled || isPending} onClick={() => { setRestartOpen(true); setConfirmOpen(true); }}>
            {t("Start adaptation over")}
          </Button>
        </div>
      )}
      {startError && <p role="alert" className="w-full font-body text-sm text-hero-red">{startError}</p>}
      {freshStart ? (
        <AdaptRestartDrawer
          open={confirmOpen}
          cost={estimate.isError ? undefined : estimate.data}
          busy={isPending}
          disabled={unavailable}
          onClose={closeConfirmation}
          onConfirm={confirmStart}
          extraBody={estimate.isError ? <div role="alert">
            <p>{t("The estimate could not be loaded. No work has started.")}</p>
            <Button variant="outline" onClick={() => void estimate.refetch()} disabled={estimate.isFetching}>{t("Retry estimate")}</Button>
          </div> : (!estimate.data || estimate.isFetching) && <p role="status">{t("Loading estimate…")}</p>}
        />
      ) : rerun ? (
        <RerunDrawer
          open={confirmOpen}
          stageName={t(STAGE_META[stage].title)}
          impactStages={RERUN_IMPACT[stage].downstream}
          cost={estimate.data}
          confirmLabel={actionLabel}
          busy={unavailable}
          onClose={closeConfirmation}
          onConfirm={confirmStart}
        />
      ) : (
        <ConfirmDrawer
          open={confirmOpen}
          title={actionLabel}
          body={stage === "extract"
            ? t("Analyze your manuscript and prepare a story brief. You will review it before choosing a style or drawing pages.")
            : retry && stage === "adapt"
              ? t("Resume using saved work where possible, then check the script again before page planning continues.")
              : t(STAGE_META[stage].description)}
          cost={estimate.data}
          confirmLabel={actionLabel}
          busy={unavailable}
          onClose={closeConfirmation}
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

export function StageQueued({ stage, queue }: { stage: StageName; queue: StageQueue }) {
  const { t } = useI18n();
  const starting = queue.state === "starting";
  return <StageDocket stage={stage} state={starting ? "STARTING…" : "QUEUED"} tone="running">
    <div role="status" className="mt-6 bg-surface-container p-4 sm:p-5">
      <div className="flex items-start gap-3">
        {starting ? <LoaderCircle size={20} className="mt-0.5 shrink-0 motion-safe:animate-spin" aria-hidden="true" />
          : <Clock3 size={20} className="mt-0.5 shrink-0" aria-hidden="true" />}
        <div>
          <p className="font-body text-base font-bold leading-6">
            {starting ? t("Preparing to start") : queue.waitingFor === "cover" ? t("Your cover is being drawn")
              : queue.waitingFor === "other-project" ? t("Waiting for your other project") : t("Your work is queued")}
          </p>
          <p className="mt-2 font-body text-sm leading-6 text-ink-muted">
            {starting ? t("Your request has been picked up. Progress will appear here when generation begins.")
              : queue.waitingFor === "cover" ? t("This step is already queued and will start after the cover finishes. No action is needed.")
                : queue.waitingFor === "other-project" ? t("This step will start when your account's current work finishes. No action is needed.")
                  : t("This step will start automatically when a generation slot is available. No action is needed.")}
          </p>
        </div>
      </div>
    </div>
  </StageDocket>;
}

interface StageRunningProps {
  stage: StageName;
  itemsDone?: number;
  itemsTotal?: number;
  startedAt?: string | null;
  snapshot?: StageSnapshot | null;
}

export function StageRunning({ stage, itemsDone = 0, itemsTotal = 0, startedAt, snapshot }: StageRunningProps) {
  const { t } = useI18n();
  const meta = STAGE_META[stage];
  const textWork = ["extract", "brief", "adapt", "plan"].includes(stage);
  const hasProgress = !textWork && itemsTotal > 0;
  const now = useNow(1000, Boolean(startedAt));
  const started = startedAt ? Date.parse(startedAt) : NaN;
  const seconds = Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 1000)) : null;
  const elapsed = seconds === null ? null : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  const steps: StageName[] = stage === "extract" || stage === "brief"
    ? ["extract", "brief"] : ["adapt", "plan", "draw"];
  const currentStep = steps.indexOf(stage);
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
          <div role="status" className="flex items-center gap-3 font-body text-sm font-semibold">
            <Icon name="loader" size={20} className="shrink-0 motion-safe:animate-spin" />
            <span>{t("Work in progress")}</span>
            {elapsed && <span aria-live="off" className="ml-auto font-meta tabular-nums text-ink-muted">{t("Elapsed {time}", { time: elapsed })}</span>}
          </div>
          {stage === "plan" && snapshot?.kind === "plan" ? (
            <PlanProgressBoard snapshot={snapshot} />
          ) : stage === "adapt" && snapshot?.kind === "adapt" ? (
            <AdaptProgressBoard snapshot={snapshot} />
          ) : textWork ? (
            <>
              <p className="mt-3 font-body text-sm leading-6 text-ink-muted">{t("This step can take several minutes. Results appear when the step finishes.")}</p>
              <ol aria-label={t("Production steps")} className="mt-5 space-y-3">
                {steps.map((step, index) => (
                  <li key={step} aria-current={index === currentStep ? "step" : undefined}
                    className={`flex items-center gap-3 font-body text-sm ${index === currentStep ? "font-bold text-ink-black" : "text-ink-muted"}`}>
                    <Icon name={index < currentStep ? "check" : index === currentStep ? "loader" : "circle"} size={16} />
                    <span>{t(STAGE_META[step].title)}</span>
                    <span className="ml-auto font-meta text-xs">{t(index < currentStep ? "Done" : index === currentStep ? "In progress" : "Next")}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between font-meta text-xs font-bold text-ink-muted">
                <span>{hasProgress ? `${Math.min(itemsDone, itemsTotal)} / ${itemsTotal}` : t("Working; no completed count yet.")}</span>
                {hasProgress && <span>{pct}%</span>}
              </div>
              <progress aria-label={`${t(meta.title)} ${t("progress")}`} max={100} value={hasProgress ? pct : undefined}
                className="h-3 w-full overflow-hidden border-[2px] border-ink-black bg-pulp-paper [&::-webkit-progress-bar]:bg-pulp-paper [&::-webkit-progress-value]:bg-hero-red [&::-moz-progress-bar]:bg-hero-red" />
            </div>
          )}
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

function ExtractionRetry({ project, rerun }: { project: string; rerun: boolean }) {
  const { t } = useI18n();
  const config = useProjectConfig(project);
  const update = useUpdateProjectConfig();
  return <div className="mt-5">
    {config.isPending && <p role="status">{t("Loading model settings…")}</p>}
    {config.isError && <div role="alert">
      <p className="font-body text-sm text-hero-red">{config.error.message}</p>
      <Button variant="outline" onClick={() => void config.refetch()} disabled={config.isFetching}>{t("Try again")}</Button>
    </div>}
    {config.data && ProjectModelControls && <Suspense fallback={<p role="status">{t("Loading model settings…")}</p>}>
      <ProjectModelControls
        stageIds={["extract"]}
        selections={config.data.dev_model_selections ?? {}}
        disabled={update.isPending}
        onChange={(selections) => update.mutate({ project, data: { dev_model_selections: selections } })}
      />
    </Suspense>}
    {update.isPending && <p role="status">{t("Saving…")}</p>}
    {update.isError && <p role="alert" className="font-body text-sm text-hero-red">{update.error.message}</p>}
    {update.isSuccess && <p role="status">{t("Settings saved.")}</p>}
    <StageStartAction project={project} stage="extract" retry rerun={rerun} disabled={!config.data || config.isError || update.isPending || update.isError} />
  </div>;
}

interface StageFailedProps {
  project: string;
  stage: StageName;
  rerun: boolean;
  error?: string | null;
  errorDetail?: string | null;
  errorCode?: string | null;
}

function StageFailed({ project, stage, rerun, error, errorDetail, errorCode }: StageFailedProps) {
  const { t } = useI18n();
  const refused = errorCode === "model_refusal" || /^runtime_turn_error: stream disconnected before completion: Incomplete response returned, reason: content_filter$/.test(error ?? "") || /^AI (?:image )?request was refused by gateway\/provider/.test(error ?? "");
  const creditBlocked = errorCode === "credit_reservation_reconciliation" || /Expired credit reservation requires reconciliation|An earlier credit hold is blocking new work/.test(error ?? "");
  const validationFailure = /invariant|validation/i.test(error ?? "");
  const summary = creditBlocked
    ? t("An earlier credit hold is blocking new work. No model request was started.")
    : refused
    ? t("The model provider declined this request under its content rules. This step could not finish.")
    : stage === "adapt" && validationFailure
    ? t("The comic script needs a few corrections before page planning can continue.")
    : t("This step stopped before it could finish. You can try it again below.");
  const hasDetails = Boolean(error || errorDetail);
  const canChangeExtractionModel = stage === "extract" && !!ProjectModelControls;
  return (
    <StageDocket stage={stage} state={refused ? "MODEL REFUSAL" : "PRESS STOPPED"} tone="failed" failureTitle={creditBlocked ? t("Credit hold needs attention") : refused ? t("Model declined this content") : stage === "adapt" ? t("Adaptation paused") : t(STAGE_META[stage].title)}>
      <div role="status" className="mt-5 font-body text-base leading-7 text-ink-black">
        <p>{summary}</p>
        <p className="mt-3 text-sm leading-6 text-ink-muted">
          {creditBlocked
            ? t("The credit database needs maintenance. Changing models or recreating the project will not fix this.")
            : refused
            ? canChangeExtractionModel
              ? t("Choose a different extraction model below, then review the updated estimate and retry.")
              : stage === "adapt"
              ? t("Retry the adaptation with the current settings after reviewing the estimate. The provider may decline the same input again.")
              : t("An unchanged retry may be refused again. To continue, start a new project with a different model or revised source.")
            : stage === "adapt" && !rerun
            ? t("Resume using saved work where possible. Review the estimate before continuing.")
            : t("Review the estimate, then try again. If it stops again, open the technical details to help investigate.")}
        </p>
      </div>
      {canChangeExtractionModel ? <ExtractionRetry project={project} rerun={rerun} /> : refused && stage !== "adapt" ? (
        <Link to="/" className="mt-6 inline-flex min-h-11 items-center font-body text-sm font-semibold underline underline-offset-4">
          {t("Back to projects")}
        </Link>
      ) : <StageStartAction project={project} stage={stage} retry rerun={rerun} />}
      {hasDetails && (
        <details className="mt-6 bg-surface-container px-4 pb-1">
          <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm font-semibold">
            {t("Technical details")}
          </summary>
          {error && <p className="mb-3 font-body text-sm leading-6 text-ink-muted [overflow-wrap:anywhere]">{error}</p>}
          {errorDetail && <pre className="mb-3 max-h-64 overflow-y-auto whitespace-pre-wrap [overflow-wrap:anywhere] font-mono text-xs leading-5 text-ink-muted" tabIndex={0}>
            {errorDetail}
          </pre>}
        </details>
      )}
    </StageDocket>
  );
}

function StageLoadError({ stage, message }: { stage: StageName; message: string }) {
  const { t } = useI18n();
  return (
    <StageDocket stage={stage} state="COULD NOT LOAD" tone="failed" failureTitle={t("COULD NOT LOAD")}>
      <p className="mt-5 font-body text-[0.86rem] font-semibold leading-6 text-ink-muted">
        {t("This step could not be loaded. Your saved work has not been changed.")}
      </p>
      <details className="mt-4 border-[2px] border-ink-black/15 bg-surface-container p-3">
        <summary className="cursor-pointer font-meta text-[0.62rem] font-bold tracking-[0.08em]">
          {t("ERROR DETAILS")}
        </summary>
        <pre className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap [overflow-wrap:anywhere] font-mono text-[0.7rem] leading-5 text-ink-black/80">
          {message}
        </pre>
      </details>
    </StageDocket>
  );
}

// ── Combined switcher ─────────────────────────────────────────────────────────

interface StagePlaceholderProps {
  activeJobs?: GenerationJob[];
  project: string;
  stage: StageName;
  status: StageStatus;
  stale?: boolean;
  itemsDone?: number;
  itemsTotal?: number;
  startedAt?: string | null;
  snapshot?: StageSnapshot | null;
  retryAsRerun?: boolean;
  allowPendingStart?: boolean;
  error?: string | null;
  errorDetail?: string | null;
  errorCode?: string | null;
  loadError?: string | null;
}

export function StagePlaceholder(props: StagePlaceholderProps) {
  const queue = getStageQueue(props.stage, props.activeJobs);
  // Do not mount credit estimates or start/retry controls for work already
  // admitted to the queue, including a retry of a previously failed stage.
  if (queue && (props.status !== "running" || props.stale)) return <StageQueued stage={props.stage} queue={queue} />;
  return <StagePlaceholderContent {...props} />;
}

function StagePlaceholderContent({
  project,
  stage,
  status,
  stale = false,
  itemsDone,
  itemsTotal,
  startedAt,
  snapshot,
  retryAsRerun = false,
  allowPendingStart = false,
  error,
  errorDetail,
  errorCode,
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
        errorCode={errorCode}
      />
    );
  }
  if (loadError) {
    return <StageLoadError stage={stage} message={loadError} />;
  }
  if (status === "running" && !stale) {
    return <StageRunning stage={stage} itemsDone={itemsDone} itemsTotal={itemsTotal} startedAt={startedAt} snapshot={snapshot} />;
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
