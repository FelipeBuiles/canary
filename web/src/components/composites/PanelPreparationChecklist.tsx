import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import type {
  PanelPreparationStage,
  PanelPreparationState,
  PanelPreparationStepState,
} from "../../lib/panelPreparation";
import { Icon } from "../ui/Icon";
import { Surface } from "../ui/Surface";

interface StepCopy {
  title: string;
  description: string;
  unit: "SCENES" | "PANELS";
}

const STEP_COPY: Record<PanelPreparationStage, StepCopy> = {
  adapt: {
    title: "Adapt the story",
    description: "Turn prose into screen-ready scenes.",
    unit: "SCENES",
  },
  plan: {
    title: "Plan pages and panels",
    description: "Decide page rhythm and panel placement.",
    unit: "SCENES",
  },
  storyboard: {
    title: "Block each shot",
    description: "Set framing, action, expression, and mood.",
    unit: "SCENES",
  },
  direct: {
    title: "Prepare image instructions",
    description: "Assemble everything needed to draw consistently.",
    unit: "PANELS",
  },
};

const STATE_LABEL: Record<PanelPreparationStepState, string> = {
  done: "DONE",
  running: "RUNNING",
  waiting: "WAITING",
  failed: "STOPPED",
};

interface PanelPreparationChecklistProps {
  preparation: PanelPreparationState;
}

function PressRelay() {
  return (
    <span aria-hidden="true" className="flex items-center gap-1">
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          className="animate-press-blink h-2.5 w-2.5 bg-hero-red"
          style={{ animationDelay: `${index * 180}ms` }}
        />
      ))}
    </span>
  );
}

export function PanelPreparationChecklist({
  preparation,
}: PanelPreparationChecklistProps) {
  const { t } = useI18n();
  const { steps, completedCount, isReady, failedStage, runningStage } = preparation;
  const failed = failedStage !== null;

  const kicker = isReady
    ? "PANEL PREPARATION COMPLETE"
    : failed
      ? "PREPARATION STOPPED"
      : "PRESS RUNNING";
  const title = isReady
    ? "READY TO DRAW"
    : failed
      ? "PANEL PREPARATION NEEDS ATTENTION"
      : "PREPARING YOUR PANELS";
  const description = isReady
    ? "Your panel plan and image instructions are ready. Start drawing when you are ready."
    : failed
      ? "One preparation step did not finish. Retry it to continue from where the press stopped."
      : "Scenewright is planning how your story becomes comic panels. This usually takes a few minutes.";
  const liveSummary = isReady
    ? t("Panel preparation complete. Ready to draw.")
    : failedStage
      ? `${t(STEP_COPY[failedStage].title)} — ${t("STOPPED")}`
      : runningStage
        ? `${t(STEP_COPY[runningStage].title)} — ${t("RUNNING")}`
        : t("Panel preparation is starting.");

  return (
    <section
      aria-labelledby="panel-preparation-title"
      className="flex min-h-[50vh] items-center justify-center px-2 py-8 sm:px-6"
    >
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {liveSummary}
      </span>

      <Surface
        tone="bristol"
        shadow="paper"
        padding="none"
        className="w-full max-w-[820px] overflow-hidden border-[3px]"
      >
        <header className="border-b-[3px] border-ink-black bg-pulp-paper px-5 py-5 sm:px-7 sm:py-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className={cn(
                "flex items-center gap-2 font-meta text-[0.58rem] font-bold uppercase tracking-[0.12em]",
                failed ? "text-hero-red" : isReady ? "text-archive-sage" : "text-ink-muted",
              )}>
                {!isReady && !failed ? <PressRelay /> : null}
                {isReady ? <Icon name="check" size={14} /> : null}
                {failed ? <Icon name="alert" size={14} /> : null}
                <span>{t(kicker)}</span>
              </div>
              <h2
                id="panel-preparation-title"
                className="mt-2 font-display text-[1.9rem] font-black uppercase leading-[0.94] tracking-[-0.035em] text-ink-black sm:text-[2.35rem]"
              >
                {t(title)}
              </h2>
            </div>

            <div className="shrink-0 bg-ink-black px-3 py-2 font-meta text-[0.58rem] font-bold tracking-[0.1em] text-bristol">
              {completedCount} {t("OF")} {steps.length} {t("STEPS COMPLETE")}
            </div>
          </div>

          <p className="mt-4 max-w-[65ch] font-body text-[0.88rem] font-semibold leading-6 text-ink-muted">
            {t(description)}
          </p>
        </header>

        <ol className="space-y-2 bg-surface-container p-3 sm:p-4">
          {steps.map((step, index) => {
            const copy = STEP_COPY[step.stage];
            const isRunning = step.state === "running";
            const isDone = step.state === "done";
            const isFailed = step.state === "failed";
            const hasLocalProgress = isRunning && step.itemsTotal > 0;

            return (
              <li
                key={step.stage}
                className={cn(
                  "grid min-h-[76px] grid-cols-[42px_minmax(0,1fr)] items-center gap-x-3 gap-y-1 px-3 py-3 transition-colors duration-200 sm:grid-cols-[42px_minmax(0,1fr)_auto] sm:px-4",
                  isRunning && "bg-narrator-gold",
                  isDone && "bg-bristol",
                  step.state === "waiting" && "bg-sidebar-tint",
                  isFailed && "bg-chip-red text-ink-black",
                )}
              >
                <span
                  className={cn(
                    "row-span-2 flex h-9 w-9 items-center justify-center border-[2px] font-meta text-[0.68rem] font-bold",
                    isDone && "animate-register-stamp border-archive-sage bg-chip-sage text-archive-sage",
                    isRunning && "border-ink-black bg-ink-black text-narrator-gold",
                    step.state === "waiting" && "border-ink-black/20 bg-bristol text-ink-muted",
                    isFailed && "border-hero-red bg-hero-red text-bristol",
                  )}
                >
                  {isDone ? (
                    <Icon name="check" size={18} />
                  ) : isFailed ? (
                    <Icon name="alert" size={17} />
                  ) : isRunning ? (
                    <span aria-hidden="true" className="animate-press-blink h-3 w-3 bg-hero-red" />
                  ) : (
                    String(index + 1).padStart(2, "0")
                  )}
                </span>

                <div className="min-w-0">
                  <div className="font-body text-[0.88rem] font-bold leading-5 text-ink-black">
                    {t(copy.title)}
                  </div>
                  <div className="mt-0.5 font-body text-[0.74rem] font-semibold leading-5 text-ink-muted">
                    {t(copy.description)}
                  </div>
                </div>

                <div className="col-start-2 flex flex-wrap items-center gap-2 sm:col-start-3 sm:row-span-2 sm:row-start-1 sm:justify-end">
                  {hasLocalProgress ? (
                    <span className="font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-black/70 tabular-nums">
                      {step.itemsDone} / {step.itemsTotal} {t(copy.unit)}
                    </span>
                  ) : null}
                  <span className={cn(
                    "font-meta text-[0.54rem] font-bold tracking-[0.1em]",
                    isDone && "text-archive-sage",
                    isRunning && "text-ink-black",
                    step.state === "waiting" && "text-ink-muted",
                    isFailed && "text-hero-red",
                  )}>
                    {t(STATE_LABEL[step.state])}
                  </span>
                </div>
              </li>
            );
          })}
        </ol>

        {!isReady && !failed ? (
          <div className="flex items-start gap-3 bg-ink-black px-5 py-4 text-bristol sm:px-7">
            <Icon name="arrow-right" size={15} className="mt-0.5 text-narrator-gold" />
            <p className="font-body text-[0.78rem] font-semibold leading-5 text-bristol/90">
              {t("You can leave this page — preparation continues in the background.")}
            </p>
          </div>
        ) : null}
      </Surface>
    </section>
  );
}
