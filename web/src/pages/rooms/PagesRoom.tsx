import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useAcceptPageIssue,
  useAdaptation,
  useApproveStage,
  useBookPlan,
  useCompletePages,
  useCorrectPageIssue,
  useCreatePageIssue,
  useGenerateCompletePage,
  useGenerationJobs,
  useProjectStatus,
  useRunPipeline,
  useStageValidation,
} from "../../api/queries";
import { pageRenderUrl } from "../../api/pages";
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
import { StatusPill } from "../../components/ui/StatusPill";
import { Surface } from "../../components/ui/Surface";
import { useI18n } from "../../i18n";
import type {
  CompletePageSummary,
  EditorialIssue,
  PageIssue,
  StageValidation,
} from "../../types/api";

function ExceptionList({ issues }: { issues: EditorialIssue[] }) {
  const { t } = useI18n();
  if (issues.length === 0) return null;
  return (
    <section aria-label={t("ADAPT & PLAN EXCEPTIONS")}>
      <SectionHeader
        variant="underline"
        title={t("ADAPT & PLAN EXCEPTIONS")}
        description={t("Review these editorial judgments before spending credits on page art.")}
      />
      <div className="grid gap-3 lg:grid-cols-2">
        {issues.map((issue) => (
          <Surface key={issue.id} tone="gold" border="hard" shadow="paper-sm" padding="md">
            <p className="font-body text-sm font-bold leading-6">{issue.message}</p>
            <p className="mt-2 font-body text-xs leading-5 text-ink-black/70">
              {issue.evidence.join(" · ")}
            </p>
          </Surface>
        ))}
      </div>
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

  if (issues.length === 0) {
    return <p className="font-body text-sm text-ink-muted">{t("No page issues recorded.")}</p>;
  }

  return (
    <ol className="space-y-3">
      {issues.map((issue) => (
        <li key={issue.id}>
          <Surface border="soft" shadow="none" padding="md">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <StatusPill tone={issue.status === "resolved" ? "sage" : issue.classification === "invariant_failure" ? "red" : "gold"}>
                  {t(issue.status.toUpperCase())}
                </StatusPill>
                <p className="mt-3 font-body text-sm font-bold">{issue.requested_correction}</p>
                <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
                  {t("Revision")} {issue.render_revision}
                  {issue.resolution_revision ? ` → ${t("Revision")} ${issue.resolution_revision}` : ""}
                </p>
              </div>
              {issue.status === "open" && (
                <div className="flex flex-wrap gap-2">
                  {issue.correction_owner === "draw" && (
                    <Button
                      size="xs"
                      onClick={() => correct.mutate(
                        {
                          project,
                          pageNumber,
                          issueId: issue.id,
                        },
                        {
                          onSuccess: ({ job }) => onJobQueued(job.id, pageNumber),
                        },
                      )}
                      disabled={correct.isPending || pageIsDrawing}
                    >
                      {t("CORRECT COMPLETE PAGE")}
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
                      {t("ACCEPT AS-IS")}
                    </Button>
                  )}
                </div>
              )}
            </div>
          </Surface>
        </li>
      ))}
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
  const [correction, setCorrection] = useState("");
  const revision = item.active_render?.render.revision;

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
      className="fixed inset-0 z-modal overflow-y-auto bg-ink-black/75 p-3 md:p-8"
    >
      <div className="mx-auto max-w-6xl border-[3px] border-ink-black bg-pulp-paper shadow-ink">
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
                src={pageRenderUrl(project, item.page.page_number, revision)}
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
  const { data, isLoading, error, refetch } = useCompletePages(id);
  const run = useRunPipeline();
  const generate = useGenerateCompletePage();
  const approve = useApproveStage();
  const [selected, setSelected] = useState<number | null>(null);
  const [pageJobs, setPageJobs] = useState<Record<string, number>>({});
  const jobIds = Object.keys(pageJobs);
  const { data: generationJobs } = useGenerationJobs(id, jobIds);

  const drawStatus = status?.stages.draw?.status ?? "pending";
  const exceptions = useMemo(
    () => [...(adaptation?.editorial_issues ?? []), ...(plan?.editorial_issues ?? [])],
    [adaptation, plan],
  );
  const selectedItem = data?.pages.find((item) => item.page.page_number === selected);

  useEffect(() => {
    const terminalIds = (generationJobs?.jobs ?? [])
      .filter((job) => job.status === "complete" || job.status === "failed")
      .map((job) => job.id);
    if (terminalIds.length === 0) return;
    void refetch().finally(() => {
      setPageJobs((current) => {
        const next = { ...current };
        terminalIds.forEach((jobId) => delete next[jobId]);
        return next;
      });
    });
  }, [generationJobs?.jobs, refetch]);

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
          stage={status?.stages.plan?.status === "complete" ? "draw" : "plan"}
          status={status?.stages.plan?.status ?? "pending"}
        />
        <BlockingFailureList validation={adaptValidation ?? planValidation} />
      </RoomShell>
    );
  }

  function continueToBook() {
    if (!id) return;
    approve.mutate(
      { project: id, stage: "draw" },
      { onSuccess: () => navigate(`/project/${encodeURIComponent(id)}/book`) },
    );
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker={t("PAGES")}
        title={t("REVIEW COMPLETE PAGES")}
        lead={t("Each thumbnail is one fully lettered page. Corrections always create a complete new revision.")}
      />

      <ExceptionList issues={exceptions} />

      <section>
        <SectionHeader
          variant="underline"
          title={t("PAGE GALLERY")}
          description={`${data.pages.length} ${t("planned pages")}`}
        />
        {drawStatus === "pending" && (
          <Surface tone="ink" padding="md" className="mb-5 flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-[60ch] text-sm leading-6 text-bristol/80">
              {t("Start Draw to lock one page model for this edition. Page art is generated only when you request it.")}
            </p>
            <Button
              variant="onInk"
              onClick={() => run.mutate({ project: id, stage: "draw" })}
              disabled={run.isPending}
            >
              {t("PREPARE PAGE EDITION")}
            </Button>
          </Surface>
        )}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4">
          {data.pages.map((item) => {
            const revision = item.active_render?.render.revision;
            return (
              <EntityCard key={item.page.page_number} padding="cozy">
                <button
                  type="button"
                  onClick={() => setSelected(item.page.page_number)}
                  aria-label={`${t("Open page")} ${item.page.page_number}, ${t("revision")} ${revision ?? 0}`}
                  className="block w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
                >
                  <div className="aspect-[2/3] overflow-hidden bg-surface-container">
                    {revision ? (
                      <img
                        src={pageRenderUrl(id, item.page.page_number, revision)}
                        alt={`${t("Complete page thumbnail")} ${item.page.page_number}, ${t("revision")} ${revision}`}
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
                    {item.issues.some((issue) => issue.status === "open") && (
                      <StatusPill tone="gold">{item.issues.filter((issue) => issue.status === "open").length}</StatusPill>
                    )}
                  </div>
                  <p className="mt-1 font-meta text-xs text-ink-muted">
                    {revision ? `${t("Revision")} ${revision}` : t("Not generated")}
                  </p>
                </button>
                {!revision && drawStatus !== "pending" && (
                  <Button
                    className="mt-3"
                    size="xs"
                    fullWidth
                    onClick={() => generate.mutate(
                      { project: id, pageNumber: item.page.page_number },
                      {
                        onSuccess: ({ job }) => setPageJobs((current) => ({
                          ...current,
                          [job.id]: item.page.page_number,
                        })),
                      },
                    )}
                    disabled={
                      generate.isPending
                      || Object.values(pageJobs).includes(item.page.page_number)
                    }
                  >
                    {Object.values(pageJobs).includes(item.page.page_number)
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
          onJobQueued={(jobId, pageNumber) => setPageJobs((current) => ({
            ...current,
            [jobId]: pageNumber,
          }))}
          pageIsDrawing={Object.values(pageJobs).includes(selectedItem.page.page_number)}
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
