import { useEffect } from "react";
import { usePipelineStore } from "../store/pipeline";

export function useSSE(projectId: string | undefined, enabled: boolean) {
  const connect = usePipelineStore((state) => state.connect);
  const disconnect = usePipelineStore((state) => state.disconnect);

  useEffect(() => {
    if (!projectId || !enabled) {
      disconnect();
      return;
    }
    connect(projectId);
    return () => disconnect();
  }, [projectId, enabled, connect, disconnect]);
}
