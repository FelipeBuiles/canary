import { useState, useEffect } from "react";
import { useCreateProject, useRunPipeline, useApproveStage, useProjectStatus, useStoryBible, useRegenExtract } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { WizardShell } from "../components/wizard/WizardShell";
import { UploadStep } from "../components/wizard/UploadStep";
import { ProgressStep } from "../components/wizard/ProgressStep";
import { ReviewExtractStep } from "../components/wizard/ReviewExtractStep";
import { ReviewStyleStep } from "../components/wizard/ReviewStyleStep";
import { ReviewCastStep } from "../components/wizard/ReviewCastStep";
import { ReviewPromptStep } from "../components/wizard/ReviewPromptStep";
import { ReviewDrawStep } from "../components/wizard/ReviewDrawStep";
import { CompleteStep } from "../components/wizard/CompleteStep";
import { Button } from "../components/ui/Button";
import type { StageName, ConfigOverrides } from "../types/api";
import { STAGE_ORDER } from "../types/api";
import { useI18n } from "../i18n";

type WizardPhase = "upload" | "running" | "review" | "style" | "complete";

interface WizardState {
  phase: WizardPhase;
  currentStage: StageName;
  errorMessage: string | null;
}

const CHECKPOINT_STAGES = new Set<string>(["extract", "index", "prompts", "generate"]);

export function NewProject() {
  const { t } = useI18n();
  const [projectSlug, setProjectSlug] = useState<string | null>(null);
  const [state, setState] = useState<WizardState>({
    phase: "upload",
    currentStage: "extract",
    errorMessage: null,
  });

  const createProject = useCreateProject();
  const runPipeline = useRunPipeline();
  const approve = useApproveStage();
  const regenExtractMut = useRegenExtract();
  const { data: status } = useProjectStatus(state.phase !== "upload" ? projectSlug ?? undefined : undefined);
  const { data: storyBible } = useStoryBible(
    state.phase === "review" && state.currentStage === "extract" ? projectSlug ?? undefined : undefined,
  );
  const events = usePipelineStore((s) => s.events);
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);

  // Track progress from SSE events
  const progressMap = useProgressFromEvents(events, state.currentStage, state.phase);

  function advanceToNextStage(currentStage: StageName) {
    const idx = STAGE_ORDER.indexOf(currentStage);
    if (idx === -1 || idx === STAGE_ORDER.length - 1) {
      setState((s) => ({ ...s, phase: "complete" }));
      return;
    }
    const nextStage = STAGE_ORDER[idx + 1];
    setState((s) => ({ ...s, currentStage: nextStage as StageName, errorMessage: null }));
  }

  // Handle SSE events for stage transitions
  useEffect(() => {
    if (state.phase !== "running" || !projectSlug) return;

    // Find the latest relevant event
    for (let i = events.length - 1; i >= 0; i--) {
      const event = events[i];

      if (event.type === "stage_complete" && event.stage === state.currentStage) {
        if (CHECKPOINT_STAGES.has(state.currentStage)) {
          setState((s) => ({ ...s, phase: "review", errorMessage: null }));
        } else {
          advanceToNextStage(state.currentStage);
        }
        return;
      }

      if (event.type === "stage_fail" && event.stage === state.currentStage) {
        setState((s) => ({
          ...s,
          errorMessage: event.message ?? "Stage failed",
        }));
        return;
      }

      if (event.type === "pipeline_done") {
        // Pipeline finished — check if all stages are complete
        const lastStage = STAGE_ORDER[STAGE_ORDER.length - 1];
        if (state.currentStage === lastStage || state.currentStage === "assemble") {
          setState((s) => ({ ...s, phase: "complete", errorMessage: null }));
        }
        return;
      }
    }
  }, [events, state.phase, state.currentStage, projectSlug]);

  function handleCreate(file: File, name: string, configOverrides?: Partial<ConfigOverrides>) {
    createProject.mutate(
      { file, name, configOverrides },
      {
        onSuccess: (data) => {
          setProjectSlug(data.name);
          clearEvents();
          setState({ phase: "running", currentStage: "extract", errorMessage: null });
          // Start pipeline and connect SSE
          runPipeline.mutate(
            { project: data.name },
            {
              onSuccess: () => connect(data.name),
              onError: (err) => setState((s) => ({ ...s, errorMessage: err.message })),
            },
          );
        },
        onError: (err) => {
          setState((s) => ({ ...s, errorMessage: err.message }));
        },
      },
    );
  }

  function handleApprove(stage: StageName) {
    if (!projectSlug) return;
    approve.mutate(
      { project: projectSlug, stage },
      {
        onSuccess: () => {
          // After extract review, go to style pick step
          if (stage === "extract") {
            setState((s) => ({ ...s, phase: "style", errorMessage: null }));
            return;
          }
          // After approving, run the next batch of stages
          const idx = STAGE_ORDER.indexOf(stage);
          const nextStage = idx < STAGE_ORDER.length - 1 ? STAGE_ORDER[idx + 1] : null;
          if (!nextStage) {
            setState((s) => ({ ...s, phase: "complete" }));
            return;
          }
          clearEvents();
          setState({ phase: "running", currentStage: nextStage as StageName, errorMessage: null });
          runPipeline.mutate(
            { project: projectSlug },
            {
              onSuccess: () => connect(projectSlug),
              onError: (err) => setState((s) => ({ ...s, errorMessage: err.message })),
            },
          );
        },
        onError: (err) => setState((s) => ({ ...s, errorMessage: err.message })),
      },
    );
  }

  function handleStyleApprove() {
    if (!projectSlug) return;
    clearEvents();
    setState({ phase: "running", currentStage: "index", errorMessage: null });
    runPipeline.mutate(
      { project: projectSlug },
      {
        onSuccess: () => connect(projectSlug),
        onError: (err) => setState((s) => ({ ...s, errorMessage: err.message })),
      },
    );
  }

  function handleRetry() {
    if (!projectSlug) return;
    clearEvents();
    setState((s) => ({ ...s, phase: "running", errorMessage: null }));
    runPipeline.mutate(
      { project: projectSlug },
      {
        onSuccess: () => connect(projectSlug),
        onError: (err) => setState((s) => ({ ...s, errorMessage: err.message })),
      },
    );
  }

  function handleStartOver() {
    setProjectSlug(null);
    clearEvents();
    setState({ phase: "upload", currentStage: "extract", errorMessage: null });
  }

  function handleRegenExtract() {
    if (!projectSlug) return;
    clearEvents();
    setState({ phase: "running", currentStage: "extract", errorMessage: null });
    regenExtractMut.mutate(
      { project: projectSlug },
      {
        onSuccess: () => connect(projectSlug),
        onError: (err) => setState((s) => ({ ...s, errorMessage: err.message })),
      },
    );
  }

  // Build step states for WizardShell
  const stepStates = buildStepStates(state, status);

  return (
    <WizardShell steps={stepStates}>
      {state.phase === "upload" && (
        <UploadStep
          onSubmit={handleCreate}
          isPending={createProject.isPending}
          error={state.errorMessage}
        />
      )}

      {state.phase === "running" && projectSlug && (
        <div className="space-y-4">
          <ProgressStep
            stage={state.currentStage}
            done={progressMap.done}
            total={progressMap.total}
            events={events}
          />
          {state.errorMessage && (
            <div className="flex items-center gap-3">
              <div className="text-[0.88rem] text-hero-red">{state.errorMessage}</div>
              <Button size="sm" onClick={handleRetry}>{t("RETRY")}</Button>
              <Button size="sm" variant="outline" onClick={handleStartOver}>{t("START OVER")}</Button>
            </div>
          )}
        </div>
      )}

      {state.phase === "review" && projectSlug && state.currentStage === "extract" && (
        <ReviewExtractStep
          storyBible={storyBible}
          onApprove={() => handleApprove("extract")}
          isApproving={approve.isPending}
          onRegenExtract={handleRegenExtract}
          isRegenerating={regenExtractMut.isPending}
          project={projectSlug}
        />
      )}

      {state.phase === "style" && projectSlug && (
        <ReviewStyleStep
          project={projectSlug}
          onApprove={handleStyleApprove}
          isApproving={runPipeline.isPending}
        />
      )}

      {state.phase === "review" && projectSlug && state.currentStage === "index" && (
        <ReviewCastStep
          project={projectSlug}
          onApprove={() => handleApprove("index")}
          isApproving={approve.isPending}
        />
      )}

      {state.phase === "review" && projectSlug && state.currentStage === "prompts" && (
        <ReviewPromptStep
          project={projectSlug}
          onApprove={() => handleApprove("prompts")}
          isApproving={approve.isPending}
        />
      )}

      {state.phase === "review" && projectSlug && state.currentStage === "generate" && (
        <ReviewDrawStep
          project={projectSlug}
          onApprove={() => handleApprove("generate")}
          isApproving={approve.isPending}
        />
      )}

      {state.phase === "complete" && projectSlug && (
        <CompleteStep
          project={projectSlug}
          totalCost={status?.total_cost_usd ?? 0}
          panelCount={status?.stages?.generate?.items_done ?? 0}
        />
      )}
    </WizardShell>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function useProgressFromEvents(events: { type: string; stage?: string; done?: number; total?: number }[], currentStage: StageName, phase: string) {
  if (phase !== "running") {
    return { done: 0, total: 0 };
  }
  // Scan events for the latest progress update for the current stage
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if ((e.type === "stage_progress" || e.type === "stage_begin" || e.type === "stage_complete") && e.stage === currentStage) {
      return {
        done: e.done ?? 0,
        total: e.total ?? 0,
      };
    }
  }
  return { done: 0, total: 0 };
}

type StepState = "pending" | "running" | "review" | "done";

function buildStepStates(
  wizardState: WizardState,
  status: { stages?: Record<string, { status: string }> } | undefined,
): Partial<Record<StageName, StepState>> {
  const result: Partial<Record<StageName, StepState>> = {};
  const currentIdx = STAGE_ORDER.indexOf(wizardState.currentStage);

  for (let i = 0; i < STAGE_ORDER.length; i++) {
    const stage = STAGE_ORDER[i];
    const stageStatus = status?.stages?.[stage]?.status;

    if (stageStatus === "complete") {
      result[stage] = "done";
    } else if (stageStatus === "awaiting_review") {
      result[stage] = "done"; // approved-but-not-yet in our flow counts as done
    } else if (i < currentIdx) {
      result[stage] = "done";
    } else if (i === currentIdx) {
      if (wizardState.phase === "running") result[stage] = "running";
      else if (wizardState.phase === "review") result[stage] = "review";
      else if (wizardState.phase === "complete") result[stage] = "done";
    } else {
      result[stage] = "pending";
    }
  }

  return result;
}
