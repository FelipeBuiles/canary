import { useRunPipeline } from "../api/queries";
import { usePipelineStore } from "../store/pipeline";

export function useRunAction() {
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);

  function handleRun(project: string) {
    clearEvents();
    runPipeline.mutate(
      { project },
      { onSuccess: () => connect(project) },
    );
  }

  return { handleRun, isPending: runPipeline.isPending };
}
