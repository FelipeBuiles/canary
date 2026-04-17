import { useEffect } from "react";
import { usePipelineStore } from "../store/pipeline";

export function useSSE(projectName: string | undefined, enabled: boolean) {
  const connect = usePipelineStore((state) => state.connect);
  const disconnect = usePipelineStore((state) => state.disconnect);

  useEffect(() => {
    if (!projectName || !enabled) {
      disconnect();
      return;
    }
    connect(projectName);
    return () => disconnect();
  }, [projectName, enabled, connect, disconnect]);
}
