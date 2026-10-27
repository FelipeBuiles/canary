import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../../i18n";
import {
  checkPageChanges,
  getChangeCheckEstimate,
  getPageReplanEstimate,
  replanPage,
  type ChangeReading,
  type ChangeReadings,
  type PageCorrectionBody,
} from "../../api/pages";
import { invalidateProject } from "../../api/projectScope";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { ConfirmDrawer } from "../composites";
import { ErrorNotice } from "../composites/ErrorNotice";
import { Button } from "../ui/Button";
import { CarryThrough } from "./CarryThrough";

/**
 * One paid read of the draft against the current render: each change comes
 * back as a precise edit, or as a change for the page plan or the script,
 * which an image edit cannot make. Advice only; the author applies it.
 */
export function ChangeCheckAction({ project, pageNumber, prepare, disabled, onReadings }: {
  project: string;
  pageNumber: number;
  /** The exact draft to check, or a problem that blocks checking it. */
  prepare: () => { body: PageCorrectionBody; problem: string | null };
  disabled?: boolean;
  onReadings: (body: PageCorrectionBody, readings: ChangeReadings) => void;
}) {
  const { t } = useI18n();
  const [body, setBody] = useState<PageCorrectionBody | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const estimate = useQuery({
    queryKey: ["project", project, "change-check-estimate", pageNumber, body],
    queryFn: () => getChangeCheckEstimate(project, pageNumber, body!),
    enabled: body != null,
    retry: false,
  });
  const check = useMutation({
    mutationFn: (draft: PageCorrectionBody) => checkPageChanges(project, pageNumber, draft),
    onSuccess: (readings, draft) => { setBody(null); onReadings(draft, readings); },
    onError: (error, draft) => maybeShowInsufficientCredits(error, {
      actionLabel: t("CHECK CHANGES"), onRetry: () => check.mutate(draft),
    }),
  });
  const label = t("CHECK CHANGES");
  return (
    <div className="space-y-2">
      <Button className="w-full" size="sm" variant="outline" disabled={disabled || check.isPending}
        onClick={() => {
          check.reset();
          const prepared = prepare();
          setProblem(prepared.problem);
          if (!prepared.problem) setBody(prepared.body);
        }}>
        {check.isPending ? t("Checking…") : label}
      </Button>
      <p className="font-body text-xs leading-5 text-ink-muted">
        {t("Reads your changes against this page: suggests precise wording, and flags changes the artwork can’t make.")}
      </p>
      {problem && <p role="alert" className="font-body text-xs text-hero-red">{problem}</p>}
      {check.error && <ErrorNotice error={check.error} operation="generate" />}
      <ConfirmDrawer
        open={body != null}
        title={label}
        body={t("Reads each change against the current page. Nothing is redrawn and your draft stays as it is until you apply a suggestion.")}
        cost={estimate.data}
        extraBody={estimate.error ? <ErrorNotice error={estimate.error} operation="estimate" /> : undefined}
        confirmLabel={label}
        busy={check.isPending}
        disabled={!estimate.data}
        onClose={() => setBody(null)}
        onConfirm={() => body && check.mutate(body)}
      />
    </div>
  );
}

/** What the check said about one change, with the action that fits its route. */
export function ChangeReadingNote({ project, pageNumber, reading, current, locked, onUse, onReplanned }: {
  project: string;
  pageNumber: number;
  reading: ChangeReading;
  /** The change's wording now; a draw suggestion already in use needs no button. */
  current: string;
  locked: boolean;
  onUse: (instruction: string) => void;
  onReplanned: () => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const estimate = useQuery({
    queryKey: ["project", project, "page-replan-estimate", pageNumber, "with-request"],
    queryFn: () => getPageReplanEstimate(project, pageNumber, true),
    enabled: confirming,
    retry: false,
  });
  const replan = useMutation({
    mutationFn: () => replanPage(project, pageNumber, reading.instruction),
    onSuccess: () => {
      setConfirming(false);
      onReplanned();
      void invalidateProject(queryClient, project);
    },
  });
  const applied = reading.route === "draw" && current.trim() === reading.instruction.trim();
  const tone = reading.route === "draw" ? "border-ink-black/25" : "border-hero-red";
  return (
    <div className={`ml-8 space-y-2 border-l-2 pl-3 ${tone}`} role="status">
      <p className="font-meta text-xs font-bold text-ink-muted">
        {reading.route === "draw"
          ? t(applied ? "READY TO DRAW" : "SUGGESTED WORDING")
          : t(reading.route === "plan" ? "BELONGS TO THE PAGE PLAN" : "BELONGS TO THE SCRIPT")}
      </p>
      <p className="font-body text-xs leading-5 text-ink-muted">{reading.reason}</p>
      {!applied && <p className="font-body text-xs font-bold leading-5">{reading.instruction}</p>}
      {reading.route === "draw" && !applied && !locked && (
        <Button size="xs" variant="outline" onClick={() => onUse(reading.instruction)}>{t("USE THIS WORDING")}</Button>
      )}
      {reading.route === "plan" && !locked && (
        <Button size="xs" disabled={replan.isPending} onClick={() => { replan.reset(); setConfirming(true); }}>
          {replan.isPending ? t("Re-planning…") : t("RE-PLAN THIS PAGE")}
        </Button>
      )}
      {reading.claim && (
        <CarryThrough project={project} pageNumber={pageNumber} note={reading.instruction} claim={reading.claim} />
      )}
      {replan.error && <ErrorNotice error={replan.error} operation="generate" />}
      <ConfirmDrawer
        open={confirming}
        title={t("RE-PLAN THIS PAGE")}
        body={t("Rewrites this page’s panels to make this change. Its beats and the wording of every line stay the same. The current artwork is kept until you redraw the page.")}
        cost={estimate.data}
        extraBody={estimate.error ? <ErrorNotice error={estimate.error} operation="estimate" /> : undefined}
        confirmLabel={t("RE-PLAN THIS PAGE")}
        busy={replan.isPending}
        disabled={!estimate.data}
        onClose={() => setConfirming(false)}
        onConfirm={() => replan.mutate()}
      />
    </div>
  );
}
