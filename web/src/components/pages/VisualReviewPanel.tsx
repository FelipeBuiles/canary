import { useState } from "react";
import { useI18n } from "../../i18n";
import type { PageIssue } from "../../types/api";
import { useCachedVisualReview, useReviewPageVisuals, useVisualReviewEstimate } from "../../api/pageRevisions";
import {
  pageRenderPreviewUrl,
  referenceFileUrl,
  type VisualReviewFinding,
  type VisualReviewReference,
} from "../../api/pages";
import { Button } from "../ui/Button";
import { SectionHeader } from "../composites";
import { Surface } from "../ui/Surface";
import { visualFindingIssueId, visualFindingKey } from "./visualFindings";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";


export interface VisualReviewDraftSeed {
  key: string;
  instruction: string;
  issueId?: string;
}

function ReferenceCard({ project, reference }: { project: string; reference: VisualReviewReference }) {
  const { t } = useI18n();
  const label = reference.display_label ?? reference.label;
  const imageUrl = reference.image_path ? referenceFileUrl(project, reference.image_path) : undefined;
  return (
    <li className="flex min-w-0 items-center gap-3 border border-ink-black/20 bg-bristol px-2 py-2">
      {imageUrl ? (
        <a href={imageUrl} target="_blank" rel="noopener noreferrer" className="shrink-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red">
        <img
          src={imageUrl}
          alt={label}
          loading="lazy"
          decoding="async"
          className="h-36 w-36 border border-ink-black/30 object-contain"
        />
        </a>
      ) : (
        <span
          aria-hidden="true"
          className="flex h-36 w-36 shrink-0 items-center justify-center bg-surface-container font-display text-lg font-black text-ink-muted"
        >
          {label.slice(0, 1).toUpperCase()}
        </span>
      )}
      <span className="min-w-0">
        <span className="block truncate font-body text-xs font-bold">{label}</span>
        {reference.visual_anchor && (
          <span className="block truncate font-body text-xs text-ink-muted">{reference.visual_anchor}</span>
        )}
        {!reference.image_path && (
          <span className="block font-body text-xs text-ink-muted">{t("Reference portrait unavailable")}</span>
        )}
      </span>
    </li>
  );
}

/**
 * Benefit-led visual review: does this page match its cast and scene? Shows
 * the actual page beside its approved references, the saved result on reopen,
 * uncertainty, and an explicit paid re-check. Findings join the revision
 * draft through their persisted issue ids, never as duplicates.
 */
interface VisualReviewPanelProps {
  project: string;
  pageNumber: number;
  revision: number | undefined;
  pageIsDrawing: boolean;
  issues: PageIssue[];
  /** Issue ids already selected in the revision draft (dedupe). */
  draftKeys: string[];
  onAddToDraft: (seeds: VisualReviewDraftSeed[]) => void;
}

export function VisualReviewPanel({
  project,
  pageNumber,
  revision,
  pageIsDrawing,
  issues,
  draftKeys,
  onAddToDraft,
}: VisualReviewPanelProps) {
  const { t } = useI18n();
  const cached = useCachedVisualReview(project, pageNumber, !!revision);
  const estimate = useVisualReviewEstimate(project, pageNumber, !!revision);
  const review = useReviewPageVisuals();
  // PageReview keys this panel by render revision, so a remount (not an
  // effect) clears local "added" memory when the target changes.
  const [addedKeys, setAddedKeys] = useState<string[]>([]);

  const freshReport = review.data && review.data.render_revision === revision ? review.data : undefined;
  const savedEnvelope = cached.data && cached.data.render_revision === revision ? cached.data : undefined;
  const report = freshReport ?? savedEnvelope?.report ?? null;
  const staleSaved = !!cached.data && cached.data.render_revision !== revision;
  const references = savedEnvelope?.references ?? [];
  const findingIssues = savedEnvelope?.finding_issues ?? [];
  const isCurrent = !!report && report.render_revision === revision;
  const added = new Set([...draftKeys, ...addedKeys]);
  if (!revision) return null;

  function seedFor(finding: VisualReviewFinding, index: number): VisualReviewDraftSeed {
    return {
      key: visualFindingKey(finding),
      instruction: `Panel ${finding.panel_number} (${finding.category}): expected ${finding.expected}; observed ${finding.observation}. Fix: ${finding.correction}`,
      issueId: visualFindingIssueId(finding, index + 1, findingIssues, issues),
    };
  }

  function addFinding(finding: VisualReviewFinding, index: number) {
    const seed = seedFor(finding, index);
    setAddedKeys((current) => (current.includes(seed.key) ? current : [...current, seed.key]));
    onAddToDraft([seed]);
  }

  function addAll() {
    const seeds = (report?.findings ?? [])
      .map((finding, index) => seedFor(finding, index))
      .filter((seed) => !added.has(seed.key) && !(seed.issueId && added.has(seed.issueId)));
    setAddedKeys((current) => [...current, ...seeds.map((seed) => seed.key)]);
    onAddToDraft(seeds);
  }

  function findingInDraft(finding: VisualReviewFinding, index: number): boolean {
    const seed = seedFor(finding, index);
    return added.has(seed.key) || (!!seed.issueId && added.has(seed.issueId));
  }

  return (
    <section aria-label={t("VISUAL REVIEW")} className="space-y-3">
      <SectionHeader variant="underline" title={t("VISUAL REVIEW")} />
      <h3 className="font-display text-lg font-black uppercase leading-6">
        {t("Does this page match your cast and scene?")}
      </h3>
      <p className="max-w-[62ch] font-body text-sm leading-6">
        {t("Compare the drawn page against the approved cast and setting portraits. Anything below is a concrete mismatch you can send to the redraw draft.")}
      </p>

      {cached.isLoading && (
        <p className="font-body text-xs text-ink-muted">{t("Loading saved visual review…")}</p>
      )}

      <div className="grid gap-3 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <figure>
          <img
            src={pageRenderPreviewUrl(project, pageNumber, revision, "reader")}
            alt={`${t("Drawn page")} ${pageNumber}, ${t("revision")} ${revision}`}
            loading="lazy"
            decoding="async"
            className="w-full border-[2px] border-ink-black object-contain"
          />
          <figcaption className="mt-1 font-meta text-xs font-bold text-ink-muted">
            {t("DRAWN PAGE")} · {t("Revision")} {revision}
          </figcaption>
        </figure>
        <div className="min-w-0">
          <p className="font-meta text-xs font-bold text-ink-muted">
            {t("APPROVED REFERENCES")} · {references.length}
          </p>
          {references.length === 0 ? (
            <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
              {savedEnvelope
                ? t("This render recorded no reference portraits.")
                : t("References appear here once a review has been saved for this render.")}
            </p>
          ) : (
            <ul className="mt-2 grid min-w-0 grid-cols-1 gap-2">
              {references.map((reference) => (
                <ReferenceCard key={reference.id} project={project} reference={reference} />
              ))}
            </ul>
          )}
        </div>
      </div>

      {staleSaved && (
        <p role="status" className="font-body text-xs font-bold text-hero-red">
          {t("The saved review belongs to revision")} {cached.data?.render_revision}
          {t("; run a fresh check for this render.")}
        </p>
      )}

      {report && (
        <Surface tone="bristol" border="soft" shadow="none" padding="md">
          <p className="font-meta text-xs font-bold text-ink-muted">
            {freshReport ? t("COMPLETED JUST NOW") : t("SAVED RESULT")}
            {` · ${t("Revision")} ${report.render_revision}`}
            {!isCurrent && ` · ${t("For an older revision; redraws may already address it.")}`}
          </p>
          {report.findings.length === 0 && report.uncertain.length === 0 ? (
            <p className="mt-2 font-body text-sm">
              {t("The visual check found no discrepancies against the approved references.")}
            </p>
          ) : (
            <ol className="mt-3 space-y-4">
              {report.findings.map((finding, index) => {
                const inDraft = findingInDraft(finding, index);
                return (
                  <li key={visualFindingKey(finding)} className="border-t border-ink-black/15 pt-3">
                    <p className="font-body text-sm font-bold">
                      {t("Panel")} {finding.panel_number} · {finding.category}
                    </p>
                    <dl className="mt-1 space-y-1 font-body text-xs leading-5">
                      <div>
                        <dt className="inline font-bold">{t("Observed:")} </dt>
                        <dd className="inline">{finding.observation}</dd>
                      </div>
                      <div>
                        <dt className="inline font-bold">{t("Expected:")} </dt>
                        <dd className="inline">{finding.expected}</dd>
                      </div>
                      <div>
                        <dt className="inline font-bold">{t("Suggested fix:")} </dt>
                        <dd className="inline">{finding.correction}</dd>
                      </div>
                    </dl>
                    <Button
                      className="mt-2"
                      size="xs"
                      variant="outline"
                      disabled={inDraft || !isCurrent}
                      onClick={() => addFinding(finding, index)}
                    >
                      {inDraft ? t("IN REVISION DRAFT") : t("ADD TO DRAFT")}
                    </Button>
                  </li>
                );
              })}
            </ol>
          )}
          {report.uncertain.length > 0 && (
            <div className="mt-3 border-t border-ink-black/15 pt-3">
              <p className="font-meta text-xs font-bold text-ink-muted">{t("UNCERTAIN")}</p>
              <ul className="mt-1 space-y-1 font-body text-xs leading-5">
                {report.uncertain.map((note, index) => (
                  <li key={`uncertain:${index}`}>{note}</li>
                ))}
              </ul>
            </div>
          )}
          {report.findings.length > 1 && (
            <Button
              className="mt-3"
              size="xs"
              variant="outline"
              onClick={addAll}
              disabled={!isCurrent || report.findings.every((finding, index) => findingInDraft(finding, index))}
            >
              {t("ADD ALL TO DRAFT")}
            </Button>
          )}
        </Surface>
      )}

      {!report && !cached.isLoading && (
        <p className="font-body text-xs leading-5 text-ink-muted">
          {t("No visual review saved for this render yet.")}
        </p>
      )}

      <div className="border-[2px] border-ink-black bg-narrator-gold/20 px-3 py-3">
        <Button
          size="sm"
          disabled={review.isPending || pageIsDrawing || !estimate.data || !!estimate.error}
          onClick={() => review.mutate({ project, pageNumber }, {
            onError: (error) => maybeShowInsufficientCredits(error, { actionLabel: t("CHECK THE ARTWORK") }),
          })}
        >
          {t(review.isPending ? "CHECKING THE ARTWORK…" : report ? "RE-CHECK THE ARTWORK" : "CHECK THE ARTWORK")}
          {estimate.data ? ` · ~${estimate.data.estimate_credits} ${t("credits")}` : ""}
        </Button>
        {estimate.data?.reserved_credits != null && (
          <p className="mt-2 text-sm">{t("Temporary hold")}: {estimate.data.reserved_credits} {t("credits")}</p>
        )}
        <p className="mt-2 font-body text-xs leading-5 text-ink-black/75">
          {t("An optional paid look at cast, objects and setting against the approved portraits. Reopening a saved result never spends again.")}
        </p>
      </div>
      {estimate.error && (
        <div role="alert" className="space-y-2 text-sm text-hero-red">
          <p>{(estimate.error as Error).message}</p>
          <Button variant="outline" size="sm" onClick={() => void estimate.refetch()}>{t("RETRY ESTIMATE")}</Button>
        </div>
      )}
      {review.error && <p role="alert" className="font-body text-xs text-hero-red">{(review.error as Error).message}</p>}
      {cached.error && <p role="alert" className="font-body text-xs text-hero-red">{(cached.error as Error).message}</p>}
    </section>
  );
}
