import { useMemo } from "react";
import { Navigate, useParams } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { BACKEND_STAGE_TO_UI_ROUTE } from "../lib/uiStages";
import { STAGE_ORDER } from "../types/api";

export function NavigateToRoom() {
  const { id } = useParams<{ id: string }>();
  const { data: status, isLoading, error } = useProjectStatus(id);

  const activeStage = useMemo(() => {
    if (!status) return null;
    const extractDone = status.stages.extract?.status === "complete"
      || status.stages.extract?.status === "awaiting_review";
    if (extractDone && !status.style_selected) {
      return "styles";
    }
    const stage =
      STAGE_ORDER.find((s) => status.stages[s]?.status === "running") ??
      STAGE_ORDER.find((s) => status.stages[s]?.status === "awaiting_review") ??
      STAGE_ORDER.find((s) => status.stages[s]?.status === "failed") ??
      STAGE_ORDER.find((s) => status.stages[s]?.status === "pending") ??
      STAGE_ORDER[STAGE_ORDER.length - 1];
    return BACKEND_STAGE_TO_UI_ROUTE[stage];
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
