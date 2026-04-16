import { useParams } from "react-router-dom";
import { Outlet } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { useSSE } from "../hooks/useSSE";
import { usePipelineStore } from "../store/pipeline";

export function ProjectRooms() {
  const { name } = useParams<{ name: string }>();
  const { data: status } = useProjectStatus(name);
  const connected = usePipelineStore((state) => state.connected);
  const connect = usePipelineStore((state) => state.connect);

  const shouldStream = !!name && (connected || status?.is_running === true);
  useSSE(name, shouldStream);

  // Auto-connect SSE when project starts running
  if (name && status?.is_running && !connected) {
    connect(name);
  }

  return (
    <div className="min-h-full">
      <Outlet />
    </div>
  );
}
