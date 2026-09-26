import { useMemo } from "react";
import { Navigate, useParams } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { BACKEND_STAGE_TO_STATION_ROUTE } from "../lib/stations";
import { STAGE_ORDER } from "../types/api";
import { accessibleRoom } from "../lib/stationAccess";

export function NavigateToRoom() {
  const { id } = useParams<{ id: string }>();
  const { data: status, isLoading, error } = useProjectStatus(id);

  const activeStage = useMemo(() => {
    if (!status) return null;
    const stage =
      STAGE_ORDER.find((s) => status.stages[s]?.status === "running") ??
      STAGE_ORDER.find((s) => status.stages[s]?.status === "awaiting_review") ??
      STAGE_ORDER.find((s) => status.stages[s]?.status === "failed") ??
      STAGE_ORDER.find((s) => status.stages[s]?.status === "pending") ??
      STAGE_ORDER[STAGE_ORDER.length - 1];
    return accessibleRoom(BACKEND_STAGE_TO_STATION_ROUTE[stage], status);
  }, [status]);

  if (!id) return null;
  if (isLoading || !activeStage) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
          OPENING PROJECT…
        </p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-hero-red">
          ERROR: {error.message}
        </p>
      </div>
    );
  }
  return <Navigate to={`/project/${encodeURIComponent(id)}/${activeStage}`} replace />;
}
