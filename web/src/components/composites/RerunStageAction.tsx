import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useStageEstimate } from "../../api/queries";
import { useRunAction } from "../../hooks/useRunAction";
import { useI18n } from "../../i18n";
import { RERUN_IMPACT } from "../../lib/rerunImpact";
import { RerunDrawer } from "./RerunDrawer";
import { AdaptRestartDrawer } from "./AdaptRestartDrawer";
import { DestructiveButton } from "../ui/DestructiveButton";
import type { StageName } from "../../types/api";
import { Button } from "../ui/Button";
import { invalidateProject } from "../../api/projectScope";

interface RerunStageActionProps {
  project: string;
  stage: StageName;
  label: string;
  disabled?: boolean;
  itemsAtRisk?: string;
  description?: string;
  className?: string;
}

export function RerunStageAction({
  project,
  stage,
  label,
  disabled = false,
  itemsAtRisk,
  description,
  className,
}: RerunStageActionProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { handleRun, isPending } = useRunAction();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const estimate = useStageEstimate(project, stage, open, true);
  const actionLabel = stage === "adapt" ? t("Start adaptation over") : t(`Rerun ${label}`);
  const unavailable = disabled || isPending || !estimate.data || !!estimate.error || estimate.isFetching;

  function confirm() {
    if (unavailable) return;
    setError(null);
    handleRun(project, stage, {
      rerun: true,
      confirmedArchivePages: estimate.data?.archived_page_count,
      actionLabel,
      onSuccess: () => {
        setOpen(false);
        void invalidateProject(queryClient, project);
      },
      onError: (failure) => setError(failure.message),
    });
  }

  const recoveryDetails = (
    <div className="space-y-3 text-sm leading-6">
      {description && <p>{description}</p>}
      {disabled && <p role="status">{t("Wait for current project work to finish before restarting this step.")}</p>}
      {estimate.isFetching && <p role="status">{t("Loading estimate…")}</p>}
      {estimate.error && (
        <div role="alert">
          <p>{t("The estimate could not be loaded. No work has started.")}</p>
          <Button variant="outline" size="sm" onClick={() => void estimate.refetch()} disabled={estimate.isFetching}>
            {t("Retry estimate")}
          </Button>
        </div>
      )}
      {error && <p role="alert" className="text-hero-red">{error}</p>}
    </div>
  );

  return (
    <>
      <DestructiveButton
        size="sm"
        className={className}
        disabled={disabled || isPending}
        onClick={() => { setError(null); setOpen(true); }}
      >
        {isPending ? "Rerunning…" : `↺ ${actionLabel}`}
      </DestructiveButton>
      {stage === "adapt" ? <AdaptRestartDrawer
        open={open}
        cost={estimate.error ? undefined : estimate.data}
        busy={isPending}
        disabled={unavailable}
        onConfirm={confirm}
        onClose={() => { if (!isPending) setOpen(false); }}
        extraBody={recoveryDetails}
      /> : <RerunDrawer
        open={open}
        stageName={t(label)}
        impactStages={RERUN_IMPACT[stage].downstream}
        itemsAtRisk={itemsAtRisk}
        cost={estimate.error ? undefined : estimate.data}
        confirmLabel={t(`Rerun ${label}`)}
        busy={isPending}
        disabled={unavailable}
        onConfirm={confirm}
        onClose={() => { if (!isPending) setOpen(false); }}
        extraBody={recoveryDetails}
      />}
    </>
  );
}
