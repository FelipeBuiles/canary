import { useRunPipeline } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { maybeShowInsufficientCredits } from "../store/insufficientCredits";
import { STAGE_DISPLAY_NAMES, type StageName } from "../types/api";

function actionLabelForStage(stage?: string) {
  if (!stage) return "Run pipeline";
  const display = STAGE_DISPLAY_NAMES[stage as StageName];
  return display ? `Run ${display}` : `Run ${stage}`;
}

export interface RunStageOptions {
  rerun?: boolean;
  confirmedArchivePages?: number;
  retryFailed?: boolean;
  /** Cast only: approve and continue to Adapt if the run leaves nothing to review. */
  thenApprove?: boolean;
  /** Overrides the label shown in the buy-credits dialog. */
  actionLabel?: string;
  onSuccess?: () => void;
  onError?: (err: Error) => void;
}

/**
 * The one way to start a stage run from the UI: clears the event log, runs
 * the stage, connects SSE on success, and surfaces the buy-credits dialog
 * (with a retry that re-runs just the stage) on a 402.
 */
export function useRunAction() {
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);

  function handleRun(project: string, stage?: string, options: RunStageOptions = {}) {
    const { rerun = false, retryFailed, confirmedArchivePages, thenApprove, actionLabel, onSuccess, onError } = options;
    clearEvents();
    runPipeline.mutate(
      { project, stage, rerun, retryFailed, confirmedArchivePages, thenApprove },
      {
        onSuccess: () => {
          connect(project);
          onSuccess?.();
        },
        onError: (err) => {
          onError?.(err);
          maybeShowInsufficientCredits(err, {
            actionLabel: actionLabel ?? actionLabelForStage(stage),
            onRetry: () => handleRun(project, stage, options),
          });
        },
      },
    );
  }

  return { handleRun, isPending: runPipeline.isPending };
}
