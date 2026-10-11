import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getReviewRecheckEstimate, recheckReviews } from "../../api/pages";
import { invalidateProject } from "../../api/projectScope";
import { useI18n } from "../../i18n";
import { ConfirmDrawer } from "../composites";
import { Button } from "../ui/Button";
import { RedrawEstimateStatus } from "./RedrawEstimateStatus";

/**
 * Drawing waits while the script and plan reviews predate the current review
 * rules. Adapt and Plan are finished, so this re-check is the way back: it
 * reads the saved script and plan again without rewriting either.
 */
export function ReviewRecheck({ project, disabled }: { project: string; disabled?: boolean }) {
  const { t } = useI18n();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const estimate = useQuery({
    queryKey: ["project", project, "review-recheck-estimate"],
    queryFn: () => getReviewRecheckEstimate(project),
    enabled: open,
    retry: false,
  });
  const recheck = useMutation({
    mutationFn: () => recheckReviews(project),
    onSuccess: () => setOpen(false),
    onSettled: () => invalidateProject(client, project),
  });
  const label = t("Re-check script and plan");

  return (
    <section role="region" aria-label={t("Drawing paused")} className="border-l-[4px] border-narrator-gold bg-bristol px-4 py-4 md:px-5">
      <p className="font-meta text-xs font-bold uppercase tracking-[0.1em]">{t("Drawing paused")}</p>
      <p className="mt-2 font-body text-sm leading-6">
        {t("The story checks changed since this script and plan were reviewed. Re-check them to keep drawing; nothing is rewritten.")}
      </p>
      <Button className="mt-3" size="sm" disabled={disabled || recheck.isPending}
        onClick={() => { recheck.reset(); setOpen(true); }}>
        {recheck.isPending ? t("Re-checking…") : label}
      </Button>
      <ConfirmDrawer
        open={open}
        title={label}
        body={t("Reads the saved script and plan again under the current review. Pages and art stay as they are.")}
        cost={estimate.data}
        extraBody={<RedrawEstimateStatus estimate={estimate} error={recheck.error} />}
        confirmLabel={label}
        busy={recheck.isPending}
        disabled={!estimate.data}
        onClose={() => setOpen(false)}
        onConfirm={() => recheck.mutate()}
      />
    </section>
  );
}
