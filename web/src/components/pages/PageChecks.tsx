import { ErrorNotice } from "../composites/ErrorNotice";
import { useState } from "react";
import { useI18n } from "../../i18n";
import { msg } from "../../locales/messages";
import { readableAnchor } from "../../lib/visualAnchor";
import type { CompletePageSummary, PageIssue } from "../../types/api";
import { referenceFileUrl } from "../../api/pages";
import { useAcceptPageIssue, useDismissPageIssue, useSecondLook } from "../../api/queries";
import { useCachedVisualReview, useReviewPageVisuals, useVisualReviewEstimate } from "../../api/pageRevisions";
import { Button } from "../ui/Button";
import { Surface } from "../ui/Surface";
import { SectionHeader } from "../composites";
import { TextCheckArtwork } from "./TextCheckArtwork";
import { LetteringIssueCard, ResolvedIssueHistory } from "./LetteringEvidence";
import { isOcrIssue } from "./lettering";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";

/** A finding sent to the revision draft; known issues are selected, never duplicated. */
export interface DraftSeed {
  key: string;
  instruction: string;
  issueId?: string;
}

const FINDING_LABELS: Record<string, string> = {
  visual_identity: msg("Character"),
  visual_appearance: msg("Appearance"),
  visual_prop: msg("Object"),
  visual_scene: msg("Setting"),
  visual_composition: msg("Composition"),
  manual_change: msg("Your request"),
  unexpected_generated_lettering: msg("Stray lettering"),
};

function isActive(issue: PageIssue) {
  return issue.status === "open" || issue.status === "revised";
}

/** Automated findings are cleared as "not a problem"; editorial ones are kept as they are. */
function isAutomated(issue: PageIssue) {
  return issue.id.startsWith("page-issue-draw-page-") || issue.id.startsWith("visual-review-");
}

/**
 * The page's automatic checks in one place. Every draw reads the page's text
 * and reviews the art against the approved cast and setting; this shows what
 * they found and the two choices for each finding: fix it in the next
 * revision, or mark it as not a problem.
 */
export function PageChecks({
  project,
  item,
  pageIsDrawing,
  onFix,
  onRetryText,
  retryingText,
  retryTextError,
}: {
  project: string;
  item: CompletePageSummary;
  pageIsDrawing: boolean;
  /** Opens the revision draft with these findings selected. */
  onFix: (seeds: DraftSeed[]) => void;
  onRetryText: () => void;
  retryingText: boolean;
  retryTextError?: string;
}) {
  const { t } = useI18n();
  const pageNumber = item.page.page_number;
  const accept = useAcceptPageIssue();
  const dismiss = useDismissPageIssue();
  const secondLook = useSecondLook();
  const [actionError, setActionError] = useState<{ issueId: string; error: Error } | null>(null);
  const textChecked = item.analysis_recovery?.status === "checked";
  const visualChecked = !!item.visual_reviewed;
  const active = item.issues.filter(isActive);
  const resolved = item.issues.filter((issue) => !isActive(issue));

  function decide(issue: PageIssue, notAProblem: boolean) {
    setActionError(null);
    const mutation = notAProblem && (isAutomated(issue) || issue.issue_type === "manual_change") ? dismiss : accept;
    mutation.mutate({ project, pageNumber, issueId: issue.id }, {
      onError: (error) => {
        // Already cleared by a newer check: the refreshed list drops it, nothing to report.
        if (/was not found/.test(error.message)) return;
        setActionError({ issueId: issue.id, error });
      },
    });
  }

  function fix(issue: PageIssue) {
    onFix([{ key: `issue:${issue.id}`, issueId: issue.id, instruction: issue.requested_correction }]);
  }

  const summary = pageIsDrawing
    ? t("Checks run automatically when the page finishes drawing.")
    : active.length > 0
      ? `${t("{count, plural, one {# thing to look at.} other {# things to look at.}}", { count: active.length })} ${t("Fix adds it to your next revision; Not a problem clears it.")}`
      : textChecked && visualChecked
        ? t("Checked. Nothing to fix: the text matches the script and the artwork matches your cast and setting.")
        : t("Some checks didn't finish. Run them again below; this never redraws the page.");

  return (
    <section aria-label={t("Checks")} className="space-y-4">
      <SectionHeader variant="underline" title={t("CHECKS")} />
      <p role="status" className="font-body text-sm leading-6">{summary}</p>

      {active.length > 0 && (
        <ol className="space-y-3">
          {active.map((issue) => {
            const label = FINDING_LABELS[issue.issue_type] ?? (isOcrIssue(issue) ? msg("Text") : msg("Finding"));
            const busy = accept.isPending || dismiss.isPending;
            return (
              <li key={issue.id}>
                <Surface tone="bristol" border="soft" shadow="none" padding="md">
                  <div className="space-y-3">
                    <p className="font-meta text-xs font-bold uppercase tracking-wider text-ink-muted">
                      {t(label)}
                      {!pageIsDrawing && issue.status === "revised" && ` · ${t("Redrawn — does it look fixed?")}`}
                    </p>
                    {isOcrIssue(issue) ? (
                      <><TextCheckArtwork project={project} issue={issue} /><LetteringIssueCard issue={issue} secondLook={pageIsDrawing ? undefined : {
                        onRetry: () => secondLook.mutate({ project, pageNumber }),
                        busy: secondLook.isPending,
                        error: secondLook.error?.message,
                      }} /></>
                    ) : (
                      <>
                        {issue.evidence.length > 0 && (
                          <ul className="space-y-1 font-body text-sm leading-6">
                            {issue.evidence.map((line, index) => <li key={`${issue.id}:${index}`}>{line}</li>)}
                          </ul>
                        )}
                        <p className="font-body text-sm leading-6">
                          <span className="font-bold">{t("Suggested fix:")} </span>{issue.requested_correction}
                        </p>
                      </>
                    )}
                    {!pageIsDrawing && <div className="flex flex-wrap justify-end gap-2">
                      {issue.status === "revised" ? (
                        <>
                          <Button size="xs" variant="outline" disabled={busy} onClick={() => fix(issue)}>
                            {t("STILL WRONG")}
                          </Button>
                          <Button size="xs" disabled={busy} onClick={() => decide(issue, false)}>
                            {t("LOOKS FIXED")}
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button size="xs" variant="outline" disabled={busy} onClick={() => decide(issue, true)}>
                            {t(issue.issue_type === "manual_change" ? "WITHDRAW REQUEST" : "NOT A PROBLEM")}
                          </Button>
                          {issue.correction_owner === "draw" && issue.issue_type !== "manual_change" && (
                            <Button size="xs" onClick={() => fix(issue)}>
                              {t("FIX")}
                            </Button>
                          )}
                        </>
                      )}
                    </div>}
                    {actionError?.issueId === issue.id && (
                      <ErrorNotice error={actionError.error} operation="save" />
                    )}
                  </div>
                </Surface>
              </li>
            );
          })}
        </ol>
      )}

      {!pageIsDrawing && (!textChecked || !visualChecked) && (
        <div className="space-y-2 border-l-[3px] border-narrator-gold bg-bristol px-3 py-2">
          {!textChecked && (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-body text-sm">{t("The text check didn't finish.")}</p>
              <Button size="xs" variant="outline" disabled={retryingText} onClick={onRetryText}>
                {t(retryingText ? "CHECKING TEXT…" : "CHECK TEXT AGAIN")}
              </Button>
            </div>
          )}
          {retryTextError && <p role="alert" className="text-sm text-hero-red">{retryTextError}</p>}
          {!visualChecked && <VisualRetry project={project} pageNumber={pageNumber} />}
        </div>
      )}

      {visualChecked && <ComparedWith project={project} pageNumber={pageNumber} />}
      <ResolvedIssueHistory issues={resolved} />
    </section>
  );
}

function VisualRetry({ project, pageNumber }: { project: string; pageNumber: number }) {
  const { t } = useI18n();
  const estimate = useVisualReviewEstimate(project, pageNumber, true);
  const review = useReviewPageVisuals();
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-body text-sm">{t("The artwork check didn't finish.")}</p>
        <Button size="xs" variant="outline"
          disabled={review.isPending || !estimate.data || !!estimate.error}
          onClick={() => review.mutate({ project, pageNumber }, {
            onError: (error) => maybeShowInsufficientCredits(error, { actionLabel: t("CHECK ARTWORK AGAIN") }),
          })}>
          {t(review.isPending ? "CHECKING THE ARTWORK…" : "CHECK ARTWORK AGAIN")}
          {estimate.data ? ` · ~${estimate.data.estimate_credits} ${t("credits")}` : ""}
        </Button>
      </div>
      {estimate.error && <ErrorNotice error={(estimate.error as Error)} operation="estimate" />}
      {review.error && <ErrorNotice error={(review.error as Error)} operation="generate" />}
    </div>
  );
}

/** What the artwork was compared with, and what the review could not judge. */
function ComparedWith({ project, pageNumber }: { project: string; pageNumber: number }) {
  const { t } = useI18n();
  const cached = useCachedVisualReview(project, pageNumber);
  const references = cached.data?.references ?? [];
  const uncertain = cached.data?.report?.uncertain ?? [];
  if (references.length === 0 && uncertain.length === 0) return null;
  return (
    <details className="border border-ink-black/20 px-3 py-2">
      <summary className="cursor-pointer font-meta text-xs font-bold text-ink-muted">
        {t("What the artwork was compared with")} · {references.length}
      </summary>
      {references.length > 0 && (
        <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {references.map((reference) => {
            const label = reference.display_label ?? reference.label;
            return (
              <li key={reference.id} className="flex min-w-0 items-center gap-3 border border-ink-black/20 bg-bristol p-2">
                {reference.image_path ? (
                  <img src={referenceFileUrl(project, reference.image_path)} alt={label} loading="lazy" decoding="async"
                    className="h-20 w-20 shrink-0 border border-ink-black/30 object-contain" />
                ) : (
                  <span aria-hidden="true" className="flex h-20 w-20 shrink-0 items-center justify-center bg-surface-container font-display text-lg font-black text-ink-muted">
                    {label.slice(0, 1).toUpperCase()}
                  </span>
                )}
                <span className="min-w-0">
                  <span className="block truncate font-body text-xs font-bold">{label}</span>
                  {reference.visual_anchor && (
                    <span className="block font-body text-xs text-ink-muted">{readableAnchor(reference.visual_anchor)}</span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {uncertain.length > 0 && (
        <div className="mt-3">
          <p className="font-meta text-xs font-bold text-ink-muted">{t("COULDN'T TELL")}</p>
          <ul className="mt-1 space-y-1 font-body text-xs leading-5">
            {uncertain.map((note, index) => <li key={`uncertain:${index}`}>{note}</li>)}
          </ul>
        </div>
      )}
    </details>
  );
}
