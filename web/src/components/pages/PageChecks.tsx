import { ErrorNotice } from "../composites/ErrorNotice";
import { useState } from "react";
import { useI18n } from "../../i18n";
import { msg } from "../../locales/messages";
import { readableAnchor } from "../../lib/visualAnchor";
import type { CompletePageSummary, PageIssue } from "../../types/api";
import { referenceFileUrl, type ReferenceKind, type VisualReviewReference } from "../../api/pages";
import { useImageViewer } from "../../hooks/useImageViewer";
import { Check, CircleAlert, Image as ImageIcon, MapPin, Package, Palette, Plus, User, type LucideIcon } from "lucide-react";
import { cn } from "../../lib/cn";
import { StatusPill } from "../ui/StatusPill";
import { useAcceptPageIssue, useDismissPageIssue, useSecondLook } from "../../api/queries";
import { useCachedVisualReview, useReviewPageVisuals, useVisualReviewEstimate } from "../../api/pageRevisions";
import { Button } from "../ui/Button";
import { TextCheckArtwork } from "./TextCheckArtwork";
import { LetteringIssueCard, ResolvedIssueHistory } from "./LetteringEvidence";
import { isOcrIssue } from "./lettering";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import type { DraftControls } from "./RevisionDraft";

const FINDING_LABELS: Record<string, string> = {
  visual_identity: msg("Character"),
  visual_appearance: msg("Appearance"),
  visual_prop: msg("Object"),
  visual_scene: msg("Setting"),
  visual_speaker: msg("Speaker"),
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
 * revision, or mark it as not a problem. A finding being fixed shows its
 * editable change in place.
 */
export function PageChecks({
  project,
  item,
  pageIsDrawing,
  draft,
  onRetryText,
  retryingText,
  retryTextError,
}: {
  project: string;
  item: CompletePageSummary;
  pageIsDrawing: boolean;
  /** The next revision: Fix adds a finding to it. */
  draft: DraftControls;
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

  const summary = pageIsDrawing
    ? t("Checks run when the page finishes drawing.")
    : active.length > 0
      ? t("{count, plural, one {# thing to look at.} other {# things to look at.}}", { count: active.length })
      : textChecked && visualChecked
        ? t("Nothing to fix.")
        : t("Some checks didn't finish.");

  return (
    <section aria-label={t("Checks")} className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-display text-[1.0625rem] font-extrabold tracking-[-0.01em] text-ink-black">{t("Checks")}</h3>
        <p role="status" className="font-meta text-xs text-ink-soft">{summary}</p>
      </div>

      {active.length > 0 && (
        <ol className="space-y-3">
          {active.map((issue) => {
            const label = FINDING_LABELS[issue.issue_type] ?? (isOcrIssue(issue) ? msg("Text") : msg("Finding"));
            const busy = accept.isPending || dismiss.isPending || draft.locked;
            const included = draft.included(issue.id);
            const [problem, ...details] = issue.evidence;
            return (
              <li key={issue.id}>
                <div className={cn("border bg-bristol p-4", included ? "border-ink-black" : "border-ink-black/12")}>
                  <div className="space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-ink-soft">{t(label)}</p>
                      {included
                        ? <StatusPill tone="ink">{t("In your changes")}</StatusPill>
                        : !pageIsDrawing && issue.status === "revised" && <StatusPill tone="gold">{t("Redrawn")}</StatusPill>}
                    </div>
                    {included ?? (isOcrIssue(issue) ? (
                      <><TextCheckArtwork project={project} issue={issue} /><LetteringIssueCard issue={issue} secondLook={pageIsDrawing ? undefined : {
                        onRetry: () => secondLook.mutate({ project, pageNumber }),
                        busy: secondLook.isPending,
                        error: secondLook.error?.message,
                      }} /></>
                    ) : (
                      <>
                        <p className="font-body text-sm leading-[21px] text-ink-black">{problem ?? issue.requested_correction}</p>
                        {(details.length > 0 || problem) && (
                          <details className="font-body text-sm leading-6">
                            <summary className="cursor-pointer font-meta text-xs font-medium text-ink-muted hover:text-ink-black">{t("Details")}</summary>
                            <ul className="mt-2 space-y-1 text-[0.8125rem] leading-5 text-ink-muted">
                              {details.map((line, index) => <li key={`${issue.id}:${index}`}>{line}</li>)}
                              {problem && <li><span className="font-bold">{t("Suggested fix:")} </span>{issue.requested_correction}</li>}
                            </ul>
                          </details>
                        )}
                      </>
                    ))}
                    {!pageIsDrawing && !included && <div className="flex flex-wrap items-center gap-2 pt-1">
                      {issue.status === "revised" ? (
                        <>
                          <span className="basis-full font-body text-[0.8125rem] text-ink-muted">{t("Does it look fixed?")}</span>
                          <Button size="sm" variant="secondary" disabled={busy} onClick={() => decide(issue, false)}>
                            <Check size={14} aria-hidden="true" />{t("Looks fixed")}
                          </Button>
                          <Button size="sm" variant="outline" disabled={busy} onClick={() => draft.include(issue)}>
                            {t("Still wrong")}
                          </Button>
                        </>
                      ) : (
                        <>
                          {issue.correction_owner === "draw" && issue.issue_type !== "manual_change" && (
                            <Button size="sm" variant="secondary" disabled={busy} onClick={() => draft.include(issue)}>
                              <Plus size={14} aria-hidden="true" />{t("Add to changes")}
                            </Button>
                          )}
                          <Button size="sm" variant="outline" className="border-transparent text-ink-muted hover:border-transparent hover:bg-surface-container hover:text-ink-black" disabled={busy} onClick={() => decide(issue, true)}>
                            {t(issue.issue_type === "manual_change" ? "Withdraw request" : "Not a problem")}
                          </Button>
                        </>
                      )}
                    </div>}
                    {actionError?.issueId === issue.id && (
                      <ErrorNotice error={actionError.error} operation="save" />
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {!pageIsDrawing && (!textChecked || !visualChecked) && (
        <div className="space-y-3 bg-surface-container p-3.5">
          {!textChecked && (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-2 font-body text-[0.8125rem] text-ink-black"><CircleAlert size={15} aria-hidden="true" className="shrink-0 text-warn-orange" />{t("The text check didn't finish.")}</p>
              <Button size="sm" variant="outline" className="bg-bristol" disabled={retryingText} onClick={onRetryText}>
                {t(retryingText ? "Checking text…" : "Check text again")}
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
        <p className="flex items-center gap-2 font-body text-[0.8125rem] text-ink-black"><CircleAlert size={15} aria-hidden="true" className="shrink-0 text-warn-orange" />{t("The artwork check didn't finish.")}</p>
        <Button size="sm" variant="outline" className="bg-bristol"
          disabled={review.isPending || !estimate.data || !!estimate.error}
          onClick={() => review.mutate({ project, pageNumber }, {
            onError: (error) => maybeShowInsufficientCredits(error, { actionLabel: t("CHECK ARTWORK AGAIN") }),
          })}>
          {t(review.isPending ? "Checking the artwork…" : "Check artwork again")}
          {estimate.data ? ` · ~${estimate.data.estimate_credits} ${t("credits")}` : ""}
        </Button>
      </div>
      {estimate.error && <ErrorNotice error={(estimate.error as Error)} operation="estimate" />}
      {review.error && <ErrorNotice error={(review.error as Error)} operation="generate" />}
    </div>
  );
}

const REFERENCE_GROUPS: { kind: ReferenceKind | null; label: string; Icon: LucideIcon }[] = [
  { kind: "style", label: msg("Style"), Icon: Palette },
  { kind: "character", label: msg("Characters"), Icon: User },
  { kind: "location", label: msg("Places"), Icon: MapPin },
  { kind: "prop", label: msg("Objects"), Icon: Package },
  { kind: null, label: msg("Other"), Icon: ImageIcon },
];

/**
 * What the artwork was compared with, as pictures grouped like the Cast:
 * the selected style, then characters, places and objects. Any thumbnail
 * opens the whole set in the viewer.
 */
function ComparedWith({ project, pageNumber }: { project: string; pageNumber: number }) {
  const { t } = useI18n();
  const cached = useCachedVisualReview(project, pageNumber);
  const { open, viewer } = useImageViewer();
  const references = cached.data?.references ?? [];
  const uncertain = cached.data?.report?.uncertain ?? [];
  if (references.length === 0 && uncertain.length === 0) return null;
  const groupOf = (kind?: ReferenceKind | null) => REFERENCE_GROUPS.some((group) => group.kind === kind) ? kind ?? null : null;
  const groups = REFERENCE_GROUPS
    .map((group) => ({ ...group, items: references.filter((reference) => groupOf(reference.kind) === group.kind) }))
    .filter((group) => group.items.length > 0);
  // One viewer set in display order; each thumbnail opens at its own image.
  const pictured = groups.flatMap((group) => group.items).filter((reference) => reference.image_path);
  const nameOf = (reference: VisualReviewReference) =>
    reference.kind === "style" ? t("Selected style") : reference.display_label ?? reference.label;
  const images = pictured.map((reference) => ({
    src: referenceFileUrl(project, reference.image_path!),
    alt: nameOf(reference),
    label: nameOf(reference),
  }));
  return (
    <details className="group/compared border-t border-ink-black/15 pt-3">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-3 [&::-webkit-details-marker]:hidden">
        <span className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-ink-soft">{t("Compared with")}</span>
        <span aria-hidden="true" className="flex -space-x-2">
          {images.slice(0, 5).map((image) => (
            <img key={image.src} src={image.src} alt="" loading="lazy" decoding="async"
              className="size-7 rounded-full border-2 border-bristol bg-surface-container object-cover" />
          ))}
        </span>
        <span className="font-meta text-xs text-ink-muted">{references.length}</span>
        <span aria-hidden="true" className="ml-auto flex size-4 items-center justify-center font-meta text-xs text-ink-muted transition-transform group-open/compared:rotate-90">›</span>
      </summary>
      <div className="mt-3 space-y-4">
        {groups.map(({ kind, label, Icon, items }) => (
          <section key={kind ?? "other"} aria-label={t(label)}>
            <p className="font-meta text-[11px] font-bold uppercase tracking-wider text-ink-muted">{t(label)}</p>
            <ul className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4">
              {items.map((reference) => {
                const name = nameOf(reference);
                const index = pictured.indexOf(reference);
                return (
                  <li key={reference.id} className="min-w-0">
                    {reference.image_path ? (
                      <button type="button" onClick={() => open(images, index)}
                        aria-label={`${t("Zoom and inspect")} · ${name}`}
                        className="block aspect-square w-full overflow-hidden border border-ink-black/20 bg-surface-container transition-colors hover:border-ink-black focus-visible:outline-2 focus-visible:outline-hero-red">
                        <img src={referenceFileUrl(project, reference.image_path)} alt="" loading="lazy" decoding="async"
                          className="h-full w-full object-cover" />
                      </button>
                    ) : (
                      <span className="flex aspect-square w-full items-center justify-center border border-dashed border-ink-black/25 text-ink-muted">
                        <Icon size={20} aria-hidden="true" />
                      </span>
                    )}
                    <p className="mt-1 line-clamp-2 font-body text-xs font-bold leading-4" title={reference.visual_anchor ? readableAnchor(reference.visual_anchor) : undefined}>
                      {name}
                    </p>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
        {uncertain.length > 0 && (
          <section aria-label={t("COULDN'T TELL")}>
            <p className="font-meta text-[11px] font-bold uppercase tracking-wider text-ink-muted">{t("COULDN'T TELL")}</p>
            <ul className="mt-1 list-disc space-y-1 pl-4 font-body text-xs leading-5">
              {uncertain.map((note, index) => <li key={`uncertain:${index}`}>{note}</li>)}
            </ul>
          </section>
        )}
      </div>
      {viewer}
    </details>
  );
}
