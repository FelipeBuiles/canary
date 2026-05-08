import { useRunPipeline } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { maybeShowInsufficientCredits } from "../store/insufficientCredits";
import { STAGE_DISPLAY_NAMES, type StageName } from "../types/api";

function actionLabelForStage(stage?: string) {
  if (!stage) return "Run pipeline";
  const display = STAGE_DISPLAY_NAMES[stage as StageName];
  return display ? `Run ${display}` : `Run ${stage}`;
}

export function useRunAction() {
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);

  function handleRun(project: string, stage?: string, rerun = false) {
    clearEvents();
    runPipeline.mutate(
      { project, stage, rerun },
      {
        onSuccess: () => connect(project),
        onError: (err) => {
          maybeShowInsufficientCredits(err, {
            actionLabel: actionLabelForStage(stage),
            onRetry: () => handleRun(project, stage, rerun),
          });
        },
      },
    );
  }

  return { handleRun, isPending: runPipeline.isPending };
}
