import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { getPageRedrawEstimate, redrawOutOfDatePages } from "../../api/pages";
import { invalidateProject } from "../../api/projectScope";
import type { CompletePagesResponse, GenerationJob } from "../../types/api";
import { useI18n } from "../../i18n";
import { ConfirmDrawer } from "../composites";
import { describeRedrawChanges } from "./redrawChanges";
import { Button } from "../ui/Button";
import { RedrawEstimateStatus } from "./RedrawEstimateStatus";

type Redraws = NonNullable<CompletePagesResponse["redraws"]>;

/**
 * Drawn pages whose art no longer matches their inputs: a Story Bible entry or
 * Cast reference they were drawn from changed, or their plan did. This is the
 * one place the room reports out-of-date pages. Only those pages are offered for
 * a fresh drawing, in one confirmed batch; old art stays in each page's history.
 */
export function OutOfDatePages({ project, redraws, disabled, onQueued }: {
  project: string;
  redraws: Redraws;
  disabled?: boolean;
  onQueued: (jobs: Array<{ page_number: number; job: GenerationJob }>) => void;
}) {
  const { t } = useI18n();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const estimate = useQuery({
    queryKey: ["project", project, "page-redraws-estimate", redraws.map((page) => page.page_number).join(",")],
    queryFn: () => getPageRedrawEstimate(project),
    enabled: open,
    retry: false,
  });
  if (redraws.length === 0) return null;

  const looks = describeRedrawChanges(redraws.flatMap((page) => page.changed_references), t);
  const replanned = redraws.filter((page) => page.plan_changed).length;
  const pages = redraws.map((page) => page.page_number).join(", ");
  const label = `${t("Redraw")} ${redraws.length} ${redraws.length === 1 ? t("page") : t("pages")}`;
  const why = [
    looks.length > 0 ? `${t("Drawn before these Story Bible or Cast entries changed:")} ${looks.join("; ")}.` : "",
    replanned > 0 ? `${replanned} ${t("re-planned after drawing.")}` : "",
  ].filter(Boolean).join(" ");

  async function confirm() {
    if (!estimate.data) return;
    setBusy(true);
    setError(null);
    try {
      const result = await redrawOutOfDatePages(project, estimate.data.pages);
      setOpen(false);
      onQueued(result.jobs);
      await invalidateProject(client, project);
    } catch (cause) {
      setError(cause);
      await invalidateProject(client, project);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section role="region" aria-label={t("Pages out of date")} className="border-l-[4px] border-narrator-gold bg-bristol px-4 py-4 md:px-5">
      <p className="font-meta text-xs font-bold uppercase tracking-[0.1em]">
        {t("Pages out of date")} · {t("Pages")} {pages}
      </p>
      <p className="mt-2 font-body text-sm leading-6">
        {why} {t("Only these pages are drawn again, from their current plan and references; their current art stays in history.")}
      </p>
      <Button className="mt-3" size="sm" disabled={disabled || busy}
        onClick={() => { setError(null); setOpen(true); }}>
        <RotateCcw size={14} aria-hidden="true" />
        {busy ? t("Queuing redraw…") : label}
      </Button>
      <ConfirmDrawer
        open={open}
        title={label}
        body={t("Draws these pages again from their current plan and references. Each current version stays in its page’s history; lettering is rebuilt for the new art afterwards.")}
        cost={estimate.data}
        extraBody={<RedrawEstimateStatus estimate={estimate} error={error} />}
        confirmLabel={label}
        busy={busy}
        disabled={!estimate.data}
        onClose={() => setOpen(false)}
        onConfirm={() => void confirm()}
      />
    </section>
  );
}
