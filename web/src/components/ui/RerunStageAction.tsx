import { useState } from "react";
import { useRunAction } from "../../hooks/useRunAction";
import { useStageEstimate } from "../../api/queries";
import { RERUN_IMPACT } from "../../lib/rerunImpact";
import type { StageName } from "../../types/api";
import { STAGE_DISPLAY_NAMES } from "../../types/api";
import { DestructiveButton } from "./DestructiveButton";
import { RerunDrawer } from "./RerunDrawer";

interface RerunStageActionProps {
  project: string;
  stage: StageName;
  label: string;
  disabled?: boolean;
  itemsAtRisk?: string;
  className?: string;
}

export function RerunStageAction({
  project,
  stage,
  label,
  disabled = false,
  itemsAtRisk,
  className,
}: RerunStageActionProps) {
  const [open, setOpen] = useState(false);
  const { handleRun, isPending } = useRunAction();
  const impact = RERUN_IMPACT[stage];
  const busy = disabled || isPending;

  const estimate = useStageEstimate(project, stage, open);
  const estimatedCredits = estimate.isLoading
    ? "…"
    : estimate.data
      ? `${estimate.data.credits.toLocaleString()} credits`
      : impact.credits;

  function confirmRerun() {
    handleRun(project, stage, true);
    setOpen(false);
  }

  return (
    <>
      <DestructiveButton
        size="sm"
        onClick={() => setOpen(true)}
        disabled={busy}
        className={className}
      >
        {busy ? "Rerunning…" : `↺ Rerun ${label}`}
      </DestructiveButton>
      <RerunDrawer
        open={open}
        stageName={label}
        impactStages={impact.downstream}
        estimatedCredits={estimatedCredits}
        creditsAreEstimated={!estimate.data}
        itemsAtRisk={itemsAtRisk}
        confirmLabel={`Rerun ${STAGE_DISPLAY_NAMES[stage]}`}
        busy={busy}
        onConfirm={confirmRerun}
        onClose={() => setOpen(false)}
      />
    </>
  );
}
