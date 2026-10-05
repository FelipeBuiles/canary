import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { getCompletePageEstimate } from "../../api/pages";
import { useGenerateCompletePage } from "../../api/queries";
import { useI18n } from "../../i18n";
import { ConfirmDrawer } from "../composites";
import { Button } from "../ui/Button";

/**
 * A page re-planned after it was drawn: its art belongs to an earlier plan
 * revision, so lettering, checks and export wait for new art. A correction
 * only edits art of the same plan revision, so the page is drawn fresh from
 * its current plan; the old art stays in the page's history.
 */
export function StaleRenderRedraw({ project, pageNumber, disabled, onJobQueued, changedLooks }: {
  project: string;
  pageNumber: number;
  disabled?: boolean;
  onJobQueued: (jobId: string) => void;
  /** Set when the plan is current but Cast references the page used changed. */
  changedLooks?: string[];
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const estimate = useQuery({
    queryKey: ["project", project, "page-redraw-estimate", pageNumber],
    queryFn: () => getCompletePageEstimate(project, pageNumber),
    enabled: open,
    retry: false,
  });
  const generate = useGenerateCompletePage();
  const label = `${t("Redraw page")} ${pageNumber}`;
  const error = estimate.error ?? generate.error;

  return (
    <section role="region" aria-label={t("Redraw needed")} className={`border-l-[4px] ${changedLooks ? "border-narrator-gold" : "border-hero-red"} bg-bristol px-4 py-4 md:px-5`}>
      {changedLooks ? <>
        <p className="font-meta text-xs font-bold uppercase tracking-[0.1em]">{t("Drawn with an earlier look")}</p>
        <p className="mt-2 font-body text-sm leading-6">
          {t("These Story Bible or Cast entries changed after this page was drawn:")} {changedLooks.join("; ")}. {t("Redraw it to match them, or keep this art; the current art stays in the page’s history.")}
        </p>
      </> : <>
        <p className="font-meta text-xs font-bold uppercase tracking-[0.1em] text-hero-red">{t("Page re-planned — redraw needed")}</p>
        <p className="mt-2 font-body text-sm leading-6">
          {t("This page’s plan changed after it was drawn, so its lettering, checks and export wait for new art. Redraw it from the revised plan; the current art stays in the page’s history.")}
        </p>
      </>}
      <Button className="mt-3" size="sm" disabled={disabled || generate.isPending}
        onClick={() => { generate.reset(); setOpen(true); }}>
        <RotateCcw size={14} aria-hidden="true" />
        {generate.isPending ? t("Queuing redraw…") : label}
      </Button>
      {error && <p role="alert" className="mt-2 font-body text-sm text-hero-red">{error.message}</p>}
      <ConfirmDrawer
        open={open}
        title={label}
        body={changedLooks
          ? t("Draws this page again with the current references. The current version stays in the page’s history; lettering is rebuilt for the new art afterwards.")
          : t("Draws this page again from its revised plan. The current version stays in the page’s history; lettering is rebuilt for the new art afterwards.")}
        cost={estimate.data}
        confirmLabel={label}
        busy={generate.isPending}
        disabled={!estimate.data}
        onClose={() => setOpen(false)}
        onConfirm={() => generate.mutate({ project, pageNumber }, {
          onSuccess: ({ job }) => { setOpen(false); onJobQueued(job.id); },
        })}
      />
    </section>
  );
}
