import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useAcceptPageIssue,
  useAnalyzeCompletePage,
  useReviewPageVisuals,
  useVisualReviewEstimate,
  useAdaptation,
  useApproveStage,
  useBookPlan,
  useCompletePages,
  useCorrectPageIssue,
  useCreatePageIssue,
  useDismissPageIssue,
  useGenerateCompletePage,
  useGenerationJobs,
  useProjectStatus,
  useRunPipeline,
  useStageValidation,
} from "../../api/queries";
import { pageRenderPreviewUrl } from "../../api/pages";
import {
  ApprovalBar,
  EntityCard,
  RoomHeader,
  RoomShell,
  SectionHeader,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { FieldLabel, TextAreaField } from "../../components/ui/Field";
import { FlowingDotsPlaceholder } from "../../components/ui/FlowingDotsPlaceholder";
import { StatusPill } from "../../components/ui/StatusPill";
import { Surface } from "../../components/ui/Surface";
import { useI18n } from "../../i18n";
import { useShowDevContent } from "../../lib/devContent";
import { getImageFailureCopy } from "../../lib/imageFailure";
import type {
  CompletePageSummary,
  EditorialIssue,
  GenerationJob,
  PageIssue,
  StageValidation,
} from "../../types/api";

type EditorialIssueGroup = {
  label: string;
  issues: EditorialIssue[];
};

type EditorialIssueSummary = {
  key: string;
  message: string;
  issues: EditorialIssue[];
};

const OCR_ISSUE_TYPES = new Set([
  "misspelled_lettering",
  "missing_lettering",
  "duplicated_lettering",
  "invented_lettering",
  "reordered_lettering",
]);

function pageIssueCopy(issue: PageIssue, t: (value: string) => string) {
  if (!OCR_ISSUE_TYPES.has(issue.issue_type)) {
    return {
      title: issue.requested_correction,
      description: null,
      expected: null,
      recognized: null,
    };
  }
  const readEvidence = (prefix: string) => {
    const value = issue.evidence.find((item) => item.startsWith(prefix));
    if (!value) return null;
    try {
      return JSON.parse(value.slice(prefix.length)) as string[];
    } catch {
      return null;
    }
  };
  const titles: Record<string, string> = {
    misspelled_lettering: "Some lettering does not match",
    missing_lettering: "Some lettering is missing or unreadable",
    duplicated_lettering: "Some lettering appears more than once",
    invented_lettering: "The page contains unexpected lettering",
    reordered_lettering: "The lettering may be in the wrong reading order",
  };
  return {
    title: t(titles[issue.issue_type]),
    description: t("The text check compared this page with the approved script and found a difference."),
    expected: readEvidence("expected_text="),
    recognized: readEvidence("recognized_text="),
  };
}

function exactDifference(expected: string[], recognized: string[]) {
  const index = expected.findIndex((value, position) => value !== recognized[position]);
  if (index < 0 || recognized[index] == null) return null;
  const before = expected[index];
  const after = recognized[index];
  let prefix = 0;
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < before.length - prefix
    && suffix < after.length - prefix
    && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  return {
    expected: {
      prefix: before.slice(0, prefix),
      changed: before.slice(prefix, before.length - suffix),
      suffix: suffix ? before.slice(-suffix) : "",
    },
    recognized: {
      prefix: after.slice(0, prefix),
      changed: after.slice(prefix, after.length - suffix),
      suffix: suffix ? after.slice(-suffix) : "",
    },
  };
}

function uniqueEditorialIssues(issues: EditorialIssue[]) {
  return [...new Map(issues.map((issue) => [issue.id, issue])).values()];
}

function editorialIssueGroup(code: string) {
  if (
    code === "rushed_reaction_or_aftermath"
    || code === "weak_page_turn"
    || code === "poor_peak_release_proportion"
    || code === "emphasis_mismatch"
  ) {
    return "PACING & PAGE TURNS";
  }
  if (code.includes("continuity")) return "CONTINUITY";
  if (code.includes("omission")) return "SOURCE COVERAGE";
  return "OTHER NOTES";
}

function summarizeEditorialIssues(issues: EditorialIssue[]) {
  return issues.reduce<EditorialIssueSummary[]>((result, issue) => {
    const key = `${issue.code}:${issue.message}`;
    const existing = result.find((summary) => summary.key === key);
    if (existing) {
      existing.issues.push(issue);
    } else {
      result.push({ key, message: issue.message, issues: [issue] });
    }
    return result;
  }, []);
}

function EditorialDiagnostics({ issues }: { issues: EditorialIssue[] }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [showDevContent] = useShowDevContent();
  const uniqueIssues = useMemo(() => uniqueEditorialIssues(issues), [issues]);
  const groups = useMemo(
    () => uniqueIssues.reduce<EditorialIssueGroup[]>((result, issue) => {
      const label = editorialIssueGroup(issue.code);
      const existing = result.find((group) => group.label === label);
      if (existing) {
        existing.issues.push(issue);
      } else {
        result.push({ label, issues: [issue] });
      }
      return result;
    }, []),
    [uniqueIssues],
  );
  if (uniqueIssues.length === 0) return null;
  const diagnosticLabel = uniqueIssues.length === 1
    ? t("diagnostic")
    : t("diagnostics");
  return (
    <section aria-label={t("EDITORIAL REVIEW")}>
      <Surface tone="container" border="soft" shadow="none" padding="md">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <StatusPill tone="neutral">
                {uniqueIssues.length} {diagnosticLabel}
              </StatusPill>
              <span className="font-meta text-xs font-bold text-ink-muted">
                {t("EDITORIAL REVIEW")}
              </span>
            </div>
            <p className="mt-2 max-w-[68ch] font-body text-sm leading-6 text-ink-black/75">
              {t("Review these story and pacing suggestions before drawing. They do not block the book.")}
            </p>
          </div>
          <Button
            variant="outline"
            size="xs"
            aria-expanded={expanded}
            aria-controls="editorial-diagnostic-details"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded
              ? t("HIDE DIAGNOSTICS")
              : t("SHOW DIAGNOSTICS")}
          </Button>
        </div>

        {expanded && (
          <div id="editorial-diagnostic-details" className="mt-5 border-t border-ink-black/20 pt-1">
            {groups.map((group) => (
              <section key={group.label} className="py-4" aria-label={t(group.label)}>
                <div className="flex items-baseline justify-between gap-4">
                  <h3 className="font-body text-sm font-bold">{t(group.label)}</h3>
                  <span className="font-meta text-xs font-bold text-ink-muted">
                    {group.issues.length}
                  </span>
                </div>
                <ul className="mt-1 space-y-4">
                  {summarizeEditorialIssues(group.issues).map((summary) => (
                    <li key={summary.key}>
                      <div className="flex items-start justify-between gap-4">
                        <p className="font-body text-sm leading-6 text-ink-black/85">
                          {summary.message}
                        </p>
                        {summary.issues.length > 1 && (
                          <span className="shrink-0 font-meta text-xs font-bold text-ink-muted">
                            ×{summary.issues.length}
                          </span>
                        )}
                      </div>
                      {showDevContent && <ul className="mt-1 space-y-1 font-mono text-xs leading-5 text-ink-muted">
                        {summary.issues.flatMap((issue) => issue.evidence).map((evidence, index) => (
                          <li key={`${summary.key}:${index}`}>{evidence}</li>
                        ))}
                      </ul>}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </Surface>
    </section>
  );
}

function BlockingFailureList({ validation }: { validation?: StageValidation }) {
  const { t } = useI18n();
  if (!validation || validation.invariant_failures.length === 0) return null;
  return (
    <section aria-label={t("WHAT MUST BE FIXED")}>
      <SectionHeader
        variant="underline"
        title={t("WHAT MUST BE FIXED")}
        description={t("These contract failures block the book and cannot be accepted.")}
      />
      <div className="grid gap-3">
        {validation.invariant_failures.map((failure) => (
          <Surface key={failure.id} tone="red" border="hard" shadow="paper-sm" padding="md">
            <p className="font-body text-sm font-bold leading-6">{failure.message}</p>
            <p className="mt-2 font-body text-xs leading-5 text-ink-black/70">
              {failure.evidence.join(" · ")}
            </p>
          </Surface>
        ))}
      </div>
      {validation.recommendations.length > 0 && (
        <p className="mt-3 font-body text-sm leading-6">
          {validation.recommendations.join(" ")}
        </p>
      )}
    </section>
  );
}

function IssueHistory({
  project,
  pageNumber,
  issues,
  onJobQueued,
  pageIsDrawing,
}: {
  project: string;
  pageNumber: number;
  issues: PageIssue[];
  onJobQueued: (jobId: string, pageNumber: number) => void;
  pageIsDrawing: boolean;
}) {
  const { t } = useI18n();
  const correct = useCorrectPageIssue();
  const accept = useAcceptPageIssue();
  const dismiss = useDismissPageIssue();
  const [correctionError, setCorrectionError] = useState<{
    issueId: string;
    message: string;
  } | null>(null);

  if (issues.length === 0) {
    return <p className="font-body text-sm text-ink-muted">{t("No page issues recorded.")}</p>;
  }

  return (
    <ol className="space-y-3">
      {issues.map((issue) => {
        const copy = pageIssueCopy(issue, t);
        const difference = copy.expected && copy.recognized
          ? exactDifference(copy.expected, copy.recognized)
          : null;
        return (
          <li key={issue.id}>
            <Surface
              tone={issue.classification === "invariant_failure" && (issue.status === "open" || issue.status === "revised") ? "pulp" : "bristol"}
              border="soft"
              shadow="none"
              padding="md"
            >
            <div className="space-y-3">
              <div>
                <StatusPill tone={issue.status === "resolved" || issue.status === "dismissed" ? "sage" : issue.classification === "invariant_failure" ? "red" : "gold"}>
                  {t(issue.status.toUpperCase())}
                </StatusPill>
                <p className="mt-3 font-body text-sm font-bold">{copy.title}</p>
                {copy.description && (
                  <p className="mt-1 max-w-[62ch] font-body text-xs leading-5 text-ink-black/75">
                    {copy.description}
                  </p>
                )}
                {(copy.expected || copy.recognized) && (
                  <dl className="mt-3 grid gap-2 font-body text-xs leading-5">
                    {copy.expected && (
                      <div>
                        <dt className="font-meta font-bold text-ink-muted">{t("EXPECTED SCRIPT")}</dt>
                        <dd>{copy.expected.join(" · ") || t("No lettering")}</dd>
                      </div>
                    )}
                    {copy.recognized && (
                      <div>
                        <dt className="font-meta font-bold text-ink-muted">{t("FOUND ON PAGE")}</dt>
                        <dd>{copy.recognized.join(" · ") || t("No readable lettering found")}</dd>
                      </div>
                    )}
                  </dl>
                )}
                {difference && (
                  <div className="mt-3 border-l-[3px] border-narrator-gold bg-chip-gold/40 px-3 py-2 font-body text-xs leading-5">
                    <p className="font-meta font-bold text-ink-muted">{t("EXACT DIFFERENCE")}</p>
                    <p>
                      <span className="font-bold">{t("Expected:")} </span>
                      {difference.expected.prefix}
                      <mark className="bg-hero-red/15 text-hero-red">{difference.expected.changed || "∅"}</mark>
                      {difference.expected.suffix}
                    </p>
                    <p>
                      <span className="font-bold">{t("Found:")} </span>
                      {difference.recognized.prefix}
                      <mark className="bg-hero-red/15 text-hero-red">{difference.recognized.changed || "∅"}</mark>
                      {difference.recognized.suffix}
                    </p>
                  </div>
                )}
                <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
                  {t("Revision")} {issue.render_revision}
                  {issue.resolution_revision ? ` → ${t("Revision")} ${issue.resolution_revision}` : ""}
                </p>
                {issue.dismissal_reason && (
                  <p className="mt-2 font-body text-xs leading-5 text-ink-black/70">
                    {issue.dismissal_reason}
                  </p>
                )}
              </div>
              {(issue.status === "open" || issue.status === "revised") && (
                <div className="flex flex-wrap justify-end gap-2">
                  {issue.correction_owner === "draw" && issue.id === issues.find((candidate) => (candidate.status === "open" || candidate.status === "revised") && candidate.correction_owner === "draw")?.id && (
                    <Button
                      size="xs"
                      onClick={() => {
                        setCorrectionError(null);
                        correct.mutate(
                          {
                            project,
                            pageNumber,
                            issueId: issue.id,
                          },
                          {
                            onSuccess: ({ job }) => {
                              setCorrectionError(null);
                              onJobQueued(job.id, pageNumber);
                            },
                            onError: (error) => setCorrectionError({
                              issueId: issue.id,
                              message: error instanceof Error ? error.message : String(error),
                            }),
                          },
                        );
                      }}
                      disabled={correct.isPending || pageIsDrawing}
                    >
                      {t("CORRECT PAGE FINDINGS")}
                    </Button>
                  )}
                  {issue.classification === "editorial_issue" && (
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => accept.mutate({
                        project,
                        pageNumber,
                        issueId: issue.id,
                      })}
                      disabled={accept.isPending}
                    >
                      {t(issue.status === "revised" ? "CONFIRM FIX" : "ACCEPT AS-IS")}
                    </Button>
                  )}
                  {issue.classification === "invariant_failure"
                    && issue.id.startsWith("page-issue-draw-page-") && (
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => dismiss.mutate({
                        project,
                        pageNumber,
                        issueId: issue.id,
                      })}
                      disabled={dismiss.isPending}
                    >
                      {t("DISMISS FALSE POSITIVE")}
                    </Button>
                  )}
                </div>
              )}
            </div>
            {correctionError?.issueId === issue.id && (
              <p
                role="alert"
                className="mt-3 border-l-[3px] border-hero-red pl-3 font-body text-xs font-bold leading-5 text-hero-red"
              >
                {t("Could not create corrected revision.")} {correctionError.message}
              </p>
            )}
            {(issue.status === "open" || issue.status === "revised") && issue.correction_owner === "draw" && (
              <p className="mt-3 font-body text-xs leading-5 text-ink-black/70">
                {t("This creates one page revision addressing all unresolved Draw findings. Review the result to confirm visual fixes.")}
              </p>
            )}
            </Surface>
          </li>
        );
      })}
    </ol>
  );
}

function PageReview({
  project,
  item,
  onClose,
  onJobQueued,
  pageIsDrawing,
}: {
  project: string;
  item: CompletePageSummary;
  onClose: () => void;
  onJobQueued: (jobId: string, pageNumber: number) => void;
  pageIsDrawing: boolean;
}) {
  const { t } = useI18n();
  const createIssue = useCreatePageIssue();
  const visualReview = useReviewPageVisuals();
  const [correction, setCorrection] = useState("");
  const revision = item.active_render?.render.revision;
  const visualEstimate = useVisualReviewEstimate(project, item.page.page_number, !!revision);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const requestedCorrection = correction.trim();
    if (!requestedCorrection) return;
    createIssue.mutate({
      project,
      pageNumber: item.page.page_number,
      requestedCorrection,
    });
  }

  return (
    <section
      role="dialog"
      aria-modal="true"
      aria-label={`${t("Page")} ${item.page.page_number} ${t("review")}`}
      className="fixed inset-0 z-[120] overflow-y-auto bg-ink-black/75 p-3 md:p-8"
      onClick={onClose}
    >
      <div
        className="mx-auto max-w-6xl border-[3px] border-ink-black bg-pulp-paper shadow-ink"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-4 border-b-[3px] border-ink-black bg-bristol px-4 py-3">
          <div>
            <h2 className="font-display text-xl font-black uppercase">
              {t("Page")} {item.page.page_number}
            </h2>
            <p className="font-meta text-xs font-bold text-ink-muted">
              {t("Revision")} {revision ?? "—"}
            </p>
          </div>
          <Button variant="outline" size="xs" onClick={onClose} aria-label={t("Close page review")}>
            {t("CLOSE")}
          </Button>
        </header>

        <div className="grid gap-6 p-4 lg:grid-cols-[minmax(18rem,0.9fr)_minmax(20rem,1.1fr)] lg:p-6">
          <div>
            {revision ? (
              <img
                src={pageRenderPreviewUrl(project, item.page.page_number, revision, "reader")}
                alt={`${t("Complete page")} ${item.page.page_number}, ${t("revision")} ${revision}`}
                className="mx-auto max-h-[72vh] w-auto border-[2px] border-ink-black bg-bristol object-contain shadow-paper"
              />
            ) : (
              <Surface padding="lg" border="soft" shadow="none">
                <p>{t("This page has not been drawn yet.")}</p>
              </Surface>
            )}
          </div>

          <div className="space-y-7">
            <section>
              <SectionHeader variant="underline" title={t("CANONICAL PAGE INTENT")} />
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="font-meta text-xs text-ink-muted">{t("Page turn")}</dt><dd>{item.page.page_turn_role}</dd></div>
                <div><dt className="font-meta text-xs text-ink-muted">{t("Density")}</dt><dd>{item.page.density_intent}</dd></div>
                <div className="col-span-2"><dt className="font-meta text-xs text-ink-muted">{t("Layout intent")}</dt><dd>{item.page.layout_intent}</dd></div>
              </dl>
            </section>

            {revision && item.active_render?.render.parent_revision && (
              <p className="bg-narrator-gold px-3 py-2 font-meta text-xs font-bold">
                {t("Revision")} {item.active_render.render.parent_revision} → {t("Revision")} {revision}
              </p>
            )}

            {revision && (
              <section className="space-y-3">
                <p className="font-body text-sm">{t("OCR checks lettering. Use a visual check for reference, object, and scene discrepancies; review its findings yourself.")}</p>
                <Button size="xs" variant="outline" disabled={visualReview.isPending || pageIsDrawing || !visualEstimate.data}
                  onClick={() => visualReview.mutate({ project, pageNumber: item.page.page_number })}>
                  {t(visualReview.isPending ? "CHECKING VISUALS…" : "CHECK VISUAL CONSISTENCY")}
                  {visualEstimate.data ? ` · ~${visualEstimate.data.estimate_credits} ${t("credits")}` : ""}
                </Button>
                <p className="font-body text-xs text-ink-muted">{t("This optional check uses credits. Reopening the same completed check does not call the model again.")}</p>
                {visualEstimate.error && <p role="alert">{visualEstimate.error.message}</p>}
                {visualReview.error && <p role="alert">{visualReview.error.message}</p>}
                {visualReview.data && <p role="status">{visualReview.data.findings.length} {t("visual findings to review")}</p>}
                {visualReview.data?.uncertain.map((note, index) => <p className="font-body text-xs" key={index}>{note}</p>)}
              </section>
            )}

            <section>
              <SectionHeader variant="underline" title={t("ISSUE HISTORY")} />
              <IssueHistory
                project={project}
                pageNumber={item.page.page_number}
                issues={item.issues}
                onJobQueued={onJobQueued}
                pageIsDrawing={pageIsDrawing}
              />
            </section>

            {revision && (
              <form onSubmit={submit}>
                <FieldLabel htmlFor="page-correction">{t("What needs correction?")}</FieldLabel>
                <TextAreaField
                  id="page-correction"
                  aria-label={t("What needs correction?")}
                  value={correction}
                  onChange={(event) => setCorrection(event.target.value)}
                  placeholder={t("Describe the evidence and the result you need. The correction redraws the complete page.")}
                />
                <Button className="mt-3" type="submit" disabled={!correction.trim() || createIssue.isPending}>
                  {t("ADD PAGE ISSUE")}
                </Button>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export function PagesRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { data: status } = useProjectStatus(id);
  const { data: adaptation } = useAdaptation(id);
  const { data: plan } = useBookPlan(id);
  const planFailed = status?.stages.plan?.status === "failed";
  const adaptFailed = status?.stages.adapt?.status === "failed";
  const { data: planValidation } = useStageValidation(id, "plan", planFailed);
  const { data: adaptValidation } = useStageValidation(id, "adapt", adaptFailed);
  const planNeedsAdapt = planValidation?.invariant_failures.some(
    (failure) => failure.owner_stage === "adapt",
  ) ?? false;
  const { data, isLoading, error, refetch } = useCompletePages(id);
  const run = useRunPipeline();
  const generate = useGenerateCompletePage();
  const analyze = useAnalyzeCompletePage();
  const approve = useApproveStage();
  const [selected, setSelected] = useState<number | null>(null);
  const [pageJobs, setPageJobs] = useState<Record<string, number>>({});
  const [startingPages, setStartingPages] = useState<number[]>([]);
  const [batchPages, setBatchPages] = useState<number[]>([]);
  const [batchStartedAt, setBatchStartedAt] = useState<number | null>(null);
  const [pageFailures, setPageFailures] = useState<Partial<Record<number, GenerationJob>>>({});
  const jobIds = Object.keys(pageJobs);
  const watchingBatch = batchPages.length > 0
    && status?.stages.draw?.status !== "failed";
  const { data: trackedGenerationJobs } = useGenerationJobs(
    id,
    watchingBatch ? [] : jobIds,
    watchingBatch,
  );
  const generationJobs = watchingBatch ? undefined : trackedGenerationJobs;
  const batchGenerationJobs = watchingBatch ? trackedGenerationJobs : undefined;

  const drawStatus = status?.stages.draw?.status ?? "pending";
  const interruptedStage = status?.stages.adapt?.status !== "complete"
    ? "adapt"
    : planNeedsAdapt
      ? "adapt"
    : status?.stages.plan?.status !== "complete"
      ? "plan"
      : "draw";
  const interruptedStageInfo = status?.stages[interruptedStage];
  const interruptedStatus = planNeedsAdapt
    ? "failed"
    : interruptedStageInfo?.status ?? "pending";
  const exceptions = useMemo(
    () => [...(adaptation?.editorial_issues ?? []), ...(plan?.editorial_issues ?? [])],
    [adaptation, plan],
  );
  const selectedItem = data?.pages.find((item) => item.page.page_number === selected);

  useEffect(() => {
    const failedJobs = (generationJobs?.jobs ?? [])
      .filter((job) => job.status === "failed");
    const terminalIds = (generationJobs?.jobs ?? [])
      .filter((job) => job.status === "complete" || job.status === "failed")
      .map((job) => job.id);
    if (terminalIds.length === 0) return;
    void refetch().finally(() => {
      if (failedJobs.length > 0) {
        setPageFailures((current) => {
          const next = { ...current };
          failedJobs.forEach((job) => {
            const pageNumber = pageJobs[job.id];
            if (pageNumber !== undefined) next[pageNumber] = job;
          });
          return next;
        });
      }
      setPageJobs((current) => {
        const next = { ...current };
        terminalIds.forEach((jobId) => delete next[jobId]);
        return next;
      });
    });
  }, [generationJobs?.jobs, pageJobs, refetch]);

  useEffect(() => {
    if (batchPages.length === 0) return;
    const relevant = (batchGenerationJobs?.jobs ?? []).filter(
      (job) =>
        job.kind === "complete_page_draw"
        && job.payload.issue_id == null
        && (batchStartedAt == null || Date.parse(job.queued_at) >= batchStartedAt)
        && batchPages.includes(Number(job.payload.page_number)),
    );
    const terminalPages = relevant
      .filter((job) => job.status === "complete" || job.status === "failed")
      .map((job) => Number(job.payload.page_number));
    if (terminalPages.length === 0) return;
    const failed = relevant.filter((job) => job.status === "failed");
    void refetch().finally(() => {
      if (failed.length > 0) {
        setPageFailures((current) => {
          const next = { ...current };
          failed.forEach((job) => {
            next[Number(job.payload.page_number)] = job;
          });
          return next;
        });
      }
      setBatchPages((current) => current.filter((page) => !terminalPages.includes(page)));
    });
  }, [batchGenerationJobs?.jobs, batchPages, batchStartedAt, refetch]);

  if (isLoading && drawStatus !== "pending") {
    return (
      <RoomShell
        project={id ?? ""}
        isLoading
        loadingText={t("PREPARING COMPLETE PAGES…")}
        loadingStage="draw"
        loadingStageStatus={drawStatus}
      />
    );
  }

  if (!id || error || !data) {
    return (
      <RoomShell project={id ?? ""}>
        <StagePlaceholder
          project={id ?? ""}
          stage={interruptedStage}
          status={interruptedStatus}
          stale={interruptedStageInfo?.stale}
          itemsDone={interruptedStageInfo?.items_done}
          itemsTotal={interruptedStageInfo?.items_total}
          retryAsRerun={planNeedsAdapt}
          allowPendingStart={interruptedStage === "adapt"}
          error={interruptedStageInfo?.error}
          errorDetail={interruptedStageInfo?.error_detail}
        />
        <BlockingFailureList validation={adaptValidation ?? planValidation} />
      </RoomShell>
    );
  }
  const projectId = id;
  const pages = data.pages;

  function continueToBook() {
    if (!id) return;
    approve.mutate(
      { project: id, stage: "draw" },
      { onSuccess: () => navigate(`/project/${encodeURIComponent(id)}/book`) },
    );
  }

  function drawPage(
    pageNumber: number,
    depiction: "canonical" | "less_graphic" = "canonical",
  ) {
    setStartingPages((current) => (
      current.includes(pageNumber) ? current : [...current, pageNumber]
    ));
    setPageFailures((current) => {
      const next = { ...current };
      delete next[pageNumber];
      return next;
    });
    generate.mutate(
      depiction === "canonical"
        ? { project: projectId, pageNumber }
        : { project: projectId, pageNumber, depiction },
      {
        onSuccess: ({ job }) => {
          setStartingPages((current) => current.filter((page) => page !== pageNumber));
          setPageJobs((current) => ({
            ...current,
            [job.id]: pageNumber,
          }));
        },
        onError: () => {
          setStartingPages((current) => current.filter((page) => page !== pageNumber));
        },
      },
    );
  }

  function startDraw(queuePages: boolean) {
    const undrawnPages = pages
      .filter((item) => !item.active_render)
      .map((item) => item.page.page_number);
    if (queuePages) {
      setBatchStartedAt(Date.now());
      setBatchPages(undrawnPages);
    }
    run.mutate(
      { project: projectId, stage: "draw", queuePages },
      {
        onError: () => {
          if (queuePages) setBatchPages([]);
        },
      },
    );
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker={t("PAGES")}
        title={t("REVIEW COMPLETE PAGES")}
        lead={t("Each thumbnail is one fully lettered page. Corrections always create a complete new revision.")}
      />

      <EditorialDiagnostics issues={exceptions} />

      <section>
        <SectionHeader
          variant="underline"
          title={t("PAGE GALLERY")}
          description={`${data.pages.length} ${t("planned pages")}`}
        />
        {drawStatus === "pending" && (
          <Surface tone="ink" padding="md" className="mb-5">
            <div className="flex flex-wrap items-end justify-between gap-5">
              <div className="max-w-[62ch]">
                <h3 className="font-body text-base font-bold text-bristol">
                  {t("How do you want to draw this edition?")}
                </h3>
                <p className="mt-1 text-sm leading-6 text-bristol/80">
                  {t("Queue every page now, or prepare the edition and generate pages one at a time while you review.")}
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={() => startDraw(false)}
                  disabled={run.isPending}
                >
                  {t("GO ONE BY ONE")}
                </Button>
                <Button
                  variant="onInk"
                  onClick={() => startDraw(true)}
                  disabled={run.isPending}
                >
                  {t("QUEUE ALL PAGES")}
                </Button>
              </div>
            </div>
          </Surface>
        )}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          {data.pages.map((item) => {
            const revision = item.active_render?.render.revision;
            const pageIsDrawing = startingPages.includes(item.page.page_number)
              || (drawStatus !== "failed" && batchPages.includes(item.page.page_number))
              || Object.values(pageJobs).includes(item.page.page_number);
            const pageFailure = pageFailures[item.page.page_number] ?? item.failure;
            const failurePhase = pageFailure && "phase" in pageFailure
              ? pageFailure.phase
              : undefined;
            const failureCopy = pageFailure
              ? getImageFailureCopy(
                  t,
                  pageFailure.classification,
                  pageFailure.user_message,
                  pageFailure.error,
                )
              : null;
            const canRetryGeneration = Boolean(pageFailure?.recoverable)
              && !revision
              && pageFailure?.classification !== "provider_blocked";
            return (
              <EntityCard key={item.page.page_number} padding="cozy">
                <button
                  type="button"
                  onClick={() => setSelected(item.page.page_number)}
                  aria-label={`${t("Open page")} ${item.page.page_number}, ${t("revision")} ${revision ?? 0}`}
                  className="block w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
                >
                  <div className="aspect-[2/3] overflow-hidden bg-surface-container">
                    {pageIsDrawing ? (
                      <FlowingDotsPlaceholder
                        aspect="2 / 3"
                        label={t("DRAWING PAGE…")}
                        caption={t("Queued in the page press")}
                        aria-label={`${t("Page")} ${item.page.page_number}: ${t("generation in progress")}`}
                        className="h-full border-0"
                      />
                    ) : revision ? (
                      <img
                        src={pageRenderPreviewUrl(id, item.page.page_number, revision, "thumbnail")}
                        alt={`${t("Complete page thumbnail")} ${item.page.page_number}, ${t("revision")} ${revision}`}
                        loading="lazy"
                        decoding="async"
                        className="h-full w-full object-contain"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center px-4 text-center font-meta text-xs font-bold text-ink-muted">
                        {t("READY TO DRAW")}
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <span className="font-display text-lg font-black uppercase">{t("Page")} {item.page.page_number}</span>
                    {item.issues.some((issue) => (issue.status === "open" || issue.status === "revised")) && (
                      <StatusPill tone="gold">{item.issues.filter((issue) => (issue.status === "open" || issue.status === "revised")).length}</StatusPill>
                    )}
                  </div>
                  <p className="mt-1 font-meta text-xs text-ink-muted">
                    {revision ? `${t("Revision")} ${revision}` : t("Not generated")}
                  </p>
                </button>
                {failureCopy && (
                  <Surface
                    tone="pulp"
                    border="soft"
                    shadow="none"
                    padding="sm"
                    className="mt-3 border-l-[4px] border-l-hero-red"
                    role="alert"
                  >
                    <strong className="font-meta text-[0.62rem] tracking-[0.12em] text-hero-red">
                      {failureCopy.title}
                    </strong>
                    <p className="mt-1 text-xs leading-5 text-ink-black/75">
                      {failureCopy.message}
                    </p>
                    {failureCopy.guidance && (
                      <p className="mt-2 text-xs leading-5 text-ink-black/75">
                        {failureCopy.guidance}
                      </p>
                    )}
                    {pageFailure?.classification === "provider_blocked" && !revision && (
                      <div className="mt-3 grid gap-2">
                        <Button
                          size="xs"
                          fullWidth
                          onClick={() => drawPage(item.page.page_number, "less_graphic")}
                          disabled={
                            generate.isPending
                            || pageIsDrawing
                          }
                        >
                          {t("DRAW WITHOUT REFERENCES")}
                        </Button>
                        <Button
                          size="xs"
                          variant="outline"
                          fullWidth
                          onClick={() => drawPage(item.page.page_number)}
                          disabled={
                            generate.isPending
                            || pageIsDrawing
                          }
                        >
                          {t("TRY AGAIN UNCHANGED")}
                        </Button>
                      </div>
                    )}
                    {canRetryGeneration && (
                      <Button
                        className="mt-3"
                        size="xs"
                        fullWidth
                        onClick={() => drawPage(item.page.page_number)}
                        disabled={generate.isPending || pageIsDrawing}
                      >
                        {pageIsDrawing ? t("DRAWING PAGE…") : t("TRY AGAIN")}
                      </Button>
                    )}
                    {failurePhase === "analysis" && revision && (
                      <Button
                        className="mt-3"
                        size="xs"
                        fullWidth
                        onClick={() => analyze.mutate({
                          project: projectId,
                          pageNumber: item.page.page_number,
                        })}
                        disabled={analyze.isPending}
                      >
                        {analyze.isPending ? t("CHECKING TEXT…") : t("RETRY TEXT CHECK")}
                      </Button>
                    )}
                  </Surface>
                )}
                {!revision && drawStatus !== "pending" && !failureCopy && (
                  <Button
                    className="mt-3"
                    size="xs"
                    fullWidth
                    onClick={() => drawPage(item.page.page_number)}
                    disabled={
                      pageIsDrawing
                    }
                  >
                    {pageIsDrawing
                      ? t("DRAWING PAGE…")
                      : t("GENERATE COMPLETE PAGE")}
                  </Button>
                )}
              </EntityCard>
            );
          })}
        </div>
      </section>

      {selectedItem && (
        <PageReview
          project={id}
          item={selectedItem}
          onClose={() => setSelected(null)}
          onJobQueued={(jobId, pageNumber) => {
            setPageFailures((current) => {
              const next = { ...current };
              delete next[pageNumber];
              return next;
            });
            setPageJobs((current) => ({
              ...current,
              [jobId]: pageNumber,
            }));
          }}
          pageIsDrawing={
            startingPages.includes(selectedItem.page.page_number)
            || (drawStatus !== "failed" && batchPages.includes(selectedItem.page.page_number))
            || Object.values(pageJobs).includes(selectedItem.page.page_number)
          }
        />
      )}

      <ApprovalBar
        next={t("Run Finish preflight and export the book")}
        primaryLabel={t("CONTINUE TO BOOK")}
        onPrimary={continueToBook}
        primaryDisabled={
          approve.isPending
          || drawStatus !== "awaiting_review"
          || data.issue_summary.blocking_issue_ids.length > 0
          || data.pages.some((item) => !item.active_render)
        }
        busy={approve.isPending}
        note={
          data.issue_summary.unresolved_issue_ids.length > 0
            ? `${data.issue_summary.unresolved_issue_ids.length} ${t("unresolved page issues must be accepted before export")}`
            : undefined
        }
      />
    </RoomShell>
  );
}
