import { BookPublication } from "../../components/book/BookPublication";
import { BookOpen, ArrowDown } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  useCompletePages,
  useCreditHistory,
  useExport,
  useFinishPreflight,
  useProjectStatus,
  useRunFinishPreflight,
  useStoryBible,
} from "../../api/queries";
import { pageCompositePreviewUrl } from "../../api/lettering";
import { getPageReplanEstimate, pageRenderPreviewUrl, replanPage } from "../../api/pages";
import { BookExportPanel } from "../../components/book/BookExportPanel";
import { CreditHistoryLedger } from "../../components/credits/CreditHistoryLedger";
import { PageThumbnail } from "../../components/pages/PageThumbnail";
import { BookReader } from "../../components/BookReader";
import { PageCheckRecovery } from "../../components/pages/PageCheckRecovery";
import {
  ConfirmDrawer,
  RoomHeader,
  RoomShell,
  SectionHeader,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/Skeleton";
import { Surface } from "../../components/ui/Surface";
import { useI18n } from "../../i18n";
import { readerPages } from "../../lib/bookReader";
import { groupRunsByDay } from "../../lib/creditsHistory";
import { useShowDevContent } from "../../lib/devContent";
import { groupEditionFindings } from "../../lib/editionChecks";
import type { FinishPreflight } from "../../types/api";
import { invalidateProject, projectPath, splitProjectKey } from "../../api/projectScope";
import { CombinedExport } from "../../components/parts/CombinedExport";

type FinishFindingGroup = {
  key: string;
  pageNumber: number | null;
  message: string;
  evidence: string[];
  count: number;
};

function groupFinishDiagnostics(preflight?: FinishPreflight): FinishFindingGroup[] {
  if (!preflight) return [];
  const groups = new Map<string, FinishFindingGroup>();
  preflight.pages.forEach((page) => {
    (page.diagnostics ?? []).forEach((diagnostic) => {
      const key = `${page.page_number}:${diagnostic.code}:${diagnostic.message}`;
      const existing = groups.get(key);
      if (existing) {
        existing.count += 1;
        existing.evidence = Array.from(new Set([...existing.evidence, ...diagnostic.evidence]));
        return;
      }
      groups.set(key, {
        key,
        pageNumber: page.page_number,
        message: diagnostic.message,
        evidence: diagnostic.evidence,
        count: 1,
      });
    });
  });
  return Array.from(groups.values());
}

export function BookRoom() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const [showDevContent] = useShowDevContent();
  const { data: status } = useProjectStatus(id);
  const {
    data: creditHistory,
    isLoading: creditHistoryLoading,
    isError: creditHistoryError,
    refetch: refetchCreditHistory,
    fetchNextPage: fetchOlderCreditHistory,
    hasNextPage: hasOlderCreditHistory,
    isFetchingNextPage: isFetchingOlderCreditHistory,
  } = useCreditHistory(id);
  const finishStatus = status?.stages.finish?.status ?? "pending";
  const drawComplete = status?.stages.draw?.status === "complete";
  const shouldRunPreflight =
    drawComplete || finishStatus === "complete" || status?.finish_ready === true;
  const { data: preflight, isLoading, isFetching, error: preflightError, refetch } = useFinishPreflight(
    id,
    shouldRunPreflight,
  );
  const exportBook = useExport();
  const retryPreflight = useRunFinishPreflight();
  const { data: completePages, isLoading: pagesLoading } = useCompletePages(id);
  const { data: bible } = useStoryBible(id);
  const bookPages = useMemo(() => readerPages(completePages), [completePages]);
  const [readerOpen, setReaderOpen] = useState(false);
  const [exportUrls, setExportUrls] = useState<Partial<Record<"pdf" | "cbz", string>>>({});
  const [newPackage, setNewPackage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  if (!id) return null;
  if (finishStatus === "pending" && !shouldRunPreflight) {
    return (
      <RoomShell project={id}>
        <StagePlaceholder
          project={id}
          stage="finish"
          status="pending"
        />
        <BookPublication project={id} title={status?.project_name ?? t("Your book")} ready={false} />
      </RoomShell>
    );
  }

  const readyPages = preflight?.pages.filter(
    (page) => page.invariant_failures.length === 0 && page.unresolved_editorial_issue_ids.length === 0,
  ).length ?? 0;
  const acceptedIssues = preflight?.pages.reduce(
    (total, page) => total + page.accepted_editorial_issue_ids.length,
    0,
  ) ?? 0;
  const unresolvedIssues = preflight?.pages.reduce(
    (total, page) => total + page.unresolved_editorial_issue_ids.length,
    0,
  ) ?? 0;
  const technicalFindingCount = (preflight?.packaging_failures.length ?? 0)
    + (preflight?.pages.reduce((total, page) => total + page.invariant_failures.length, 0) ?? 0);
  const exportBlockers = technicalFindingCount + unresolvedIssues;
  const canExport = !!preflight && !isLoading && !isFetching && !preflightError && !retryPreflight.isPending && exportBlockers === 0;
  const placementReviews = preflight?.pages.filter(page => page.lettering_placement_review_needed) ?? [];
  const findings = groupEditionFindings(preflight, bible);
  const finishDiagnostics = showDevContent ? groupFinishDiagnostics(preflight) : [];
  const checking = isLoading || isFetching || retryPreflight.isPending;
  // Distinct things to fix, not raw finding rows: one page repeating a finding counts once.
  const fixCount = findings.length + unresolvedIssues + (preflight?.correction_requests.length ?? 0);
  const title = status?.project_name ?? t("Your book");
  const creditRuns = creditHistory?.pages.flatMap((page) => page.runs ?? []) ?? [];
  const creditDayGroups = groupRunsByDay(creditRuns);
  const creditProjectNames = new Map([[id, title]]);
  const packages = preflight?.packages ?? [];
  const reviewUrl = (pageNumber: number, review: "page" | "checks" | "visual" | "lettering") =>
    `/project/${encodeURIComponent(id)}/pages?page=${pageNumber}&review=${review}`;
  const uncheckedPages = completePages?.pages.filter((page) => page.active_render && page.analysis_recovery?.status !== "checked").length ?? 0;
  const pageIssues = new Map(completePages?.pages.flatMap((page) => (page.issues ?? []).map((issue) => [issue.id, issue] as const)));

  function createExport(format: "pdf" | "cbz", force = false) {
    if (!id) return;
    exportBook.mutate(
      { project: id, format, force },
      {
        onSuccess: (result) => {
          if (!result.url) return;
          setExportUrls((current) => ({ ...current, [format]: result.url }));
          if (result.preflight?.packages.some((item) => item.format === format)) {
            setNewPackage(`${result.preflight.edition_revision}:${format}`);
          }
        },
      },
    );
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker={t("BOOK")}
        title={t("YOUR EDITION")}
        lead={t("Read your pages, settle any remaining decisions, and prepare your book to keep.")}
      />


      <section aria-label={t("Read your book")} className="grid gap-8 bg-ink-black p-6 text-bristol shadow-paper md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] md:items-center md:p-9">
        {bookPages.length > 0 && <button type="button" onClick={() => setReaderOpen(true)} aria-label={t("Open the book reader")} className="mx-auto aspect-[2/3] w-full max-w-[15rem] overflow-hidden bg-surface-container text-ink-black shadow-[6px_6px_0_0_var(--color-narrator-gold)] transition-transform hover:-translate-y-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold motion-reduce:transition-none">
          {status?.has_cover
            ? <img src={`/api${projectPath(id)}/files/cover/cover.png`} alt={t("Book cover")} className="h-full w-full object-cover" decoding="async" />
            : <PageThumbnail reveal={false} onRevealEnd={() => {}} src={(bookPages[0].hybrid ? pageCompositePreviewUrl(id, bookPages[0].pageNumber, bookPages[0].revision, "reader", bookPages[0].letteringRevision) : pageRenderPreviewUrl(id, bookPages[0].pageNumber, bookPages[0].revision, "reader"))} alt={t("First page of the book")} />}
        </button>}
        <div className="min-w-0">
          <h2 className="break-words font-display text-3xl font-black leading-tight tracking-[-0.03em] md:text-5xl">{title}</h2>
          <p className="mt-3 font-meta text-sm text-bristol/85">{completePages ? `${bookPages.length} ${bookPages.length === 1 ? t("page drawn") : t("pages drawn")}` : pagesLoading ? t("Loading artwork…") : t("Page previews are unavailable.")}</p>
          <p role="status" className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 font-meta text-xs font-bold uppercase tracking-[0.1em]">
            {checking ? <span className="text-bristol/85">{t("Checking edition…")}</span>
              : preflightError || !preflight ? <span className="text-narrator-gold">{t("The book could not be checked.")}</span>
              : fixCount > 0 ? <span className="bg-hero-red px-2 py-1 text-bristol">{fixCount} {t("{count, plural, one {fix needed before export} other {fixes needed before export}}", { count: fixCount })}</span>
              : <span className="bg-narrator-gold px-2 py-1 text-ink-black">{t("Ready to export")}</span>}
            {!checking && placementReviews.length > 0 && <span className="text-bristol/75">{placementReviews.length} {t("{count, plural, one {page to check by eye} other {pages to check by eye}}", { count: placementReviews.length })}</span>}
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            {bookPages.length > 0 && <Button variant="onInk" onClick={() => setReaderOpen(true)}><BookOpen size={18} aria-hidden="true" />{t("Read your book")}</Button>}
            <a href={canExport ? "#book-downloads" : "#edition-checks"} className="inline-flex min-h-11 items-center gap-2 px-3 font-meta text-sm text-bristol underline underline-offset-4 hover:text-narrator-gold">{canExport ? t("Download your edition") : t("Review edition checks")}<ArrowDown size={16} aria-hidden="true" /></a>
          </div>
          <p className="mt-4 font-body text-xs leading-6 text-bristol/75">{t("Reading does not generate artwork or use credits.")}</p>
        </div>
      </section>

      {readerOpen && (
        <BookReader
          project={id}
          pages={bookPages}
          onClose={() => setReaderOpen(false)}
        />
      )}

      <section id="edition-checks" tabIndex={-1} aria-labelledby="edition-checks-heading" className="scroll-mt-6">
        <div id="edition-checks-heading">
          <SectionHeader
            variant="underline"
            title={t("BEFORE YOU EXPORT")}
            description={t("What blocks your edition comes first. Checks marked optional never block export.")}
            actions={preflight && !checking && !preflightError ? <span className="font-meta text-xs font-bold text-ink-muted">{readyPages} / {preflight.pages.length} {t("pages ready")}</span> : undefined}
          />
        </div>

        {checking ? (
          <Surface padding="lg" border="soft" shadow="none" role="status" aria-live="polite">
            <p className="font-meta text-sm font-bold">{t("Checking edition…")}</p>
            <p className="mt-2 font-body text-sm font-semibold leading-6 text-ink-muted">
              {t("Finish is loading the last check and will run again only if this edition changed.")}
            </p>
          </Surface>
        ) : !preflight || preflightError ? (
          <Surface padding="md" tone="red" border="hard" shadow="paper" role="alert">
            <p className="font-body text-sm font-bold leading-6">
              {t("The book could not be checked.")}
            </p>
            {preflightError && <p className="mt-2 break-words font-body text-sm leading-6">{preflightError.message}</p>}
            <Button className="mt-3" variant="outline" disabled={isFetching} onClick={() => void refetch()}>
              {isFetching ? t("Checking edition…") : t("Retry edition checks")}
            </Button>
          </Surface>
        ) : (
          <ul className="space-y-3">
            {findings.map((finding) => (
              <CheckItem key={finding.key} tone="fix"
                title={finding.copy ? t(finding.copy.title) : finding.message}
                pages={finding.pageNumbers}
                detail={finding.copy ? t(finding.copy.fix) : null}
                subjects={finding.subjects}
                evidence={finding.evidence}>
                {finding.copy?.replannable && finding.ownerStage === "plan" && finding.pageNumbers.map((pageNumber) => (
                  <ReplanPageAction key={pageNumber} project={id} pageNumber={pageNumber}
                    disabled={isFetching || retryPreflight.isPending}
                    onReplanned={() => { void refetch(); void invalidateProject(queryClient, id); }} />
                ))}
                {finding.pageNumbers.length > 0 ? (
                  <PageLinks pages={finding.pageNumbers}
                    label={t(finding.copy?.review === "page" ? "Open page" : finding.copy?.review === "lettering" ? "Open lettering" : "Open page checks")}
                    href={(page) => reviewUrl(page, finding.copy?.review ?? "checks")} />
                ) : (
                  <Button size="sm" variant="outline" disabled={isFetching || retryPreflight.isPending} onClick={() => retryPreflight.mutate({ project: id })}>
                    {t("Retry edition checks")}
                  </Button>
                )}
              </CheckItem>
            ))}
            {preflight.pages.flatMap((page) => page.unresolved_editorial_issue_ids.map((issueId) => {
              const issue = pageIssues.get(issueId);
              return (
                <CheckItem key={issueId} tone="fix" pages={[page.page_number]}
                  title={issue?.requested_correction || t("An editorial concern needs your review.")}
                  detail={issue?.status === "revised" ? t("Revised — not yet confirmed fixed") : t("Accept it as it is, or ask for a revision.")}>
                  <Link className="inline-flex min-h-11 items-center font-meta text-xs font-bold underline underline-offset-4" to={reviewUrl(page.page_number, "visual")}>
                    {t("Review page")} {page.page_number}
                  </Link>
                </CheckItem>
              );
            }))}
            {preflight.correction_requests.map((request) => (
              <CheckItem key={request.id} tone="fix" pages={[request.page_number]} title={request.requested_correction}
                detail={t("A correction was requested for this page and hasn’t been drawn yet.")}>
                <Link className="inline-flex min-h-11 items-center font-meta text-xs font-bold underline underline-offset-4" to={reviewUrl(request.page_number, "checks")}>
                  {t("Open page checks")} · {t("Page")} {request.page_number}
                </Link>
              </CheckItem>
            ))}
            {uncheckedPages > 0 && <li><PageCheckRecovery project={id} unchecked={uncheckedPages} editable={!!completePages?.pages.some((page) => page.lettering_mode === "hybrid")} onRecovered={() => void refetch()} /></li>}
            {placementReviews.length > 0 && (
              <CheckItem tone="optional" pages={placementReviews.map((page) => page.page_number)}
                title={t("{count, plural, one {Lettering on # page hasn’t been checked by eye} other {Lettering on # pages hasn’t been checked by eye}}", { count: placementReviews.length })}
                detail={t("Balloons were placed automatically. Open each page’s Lettering to check faces, reading order and quiet spaces, then mark it reviewed. Export isn’t blocked.")}>
                <Link className="inline-flex min-h-11 items-center gap-2 border-2 border-ink-black bg-ink-black px-3 font-meta text-xs font-bold text-bristol hover:bg-hero-red"
                  to={reviewUrl(placementReviews[0].page_number, "lettering")}>
                  {t("Start with page")} {placementReviews[0].page_number}
                </Link>
                <PageLinks pages={placementReviews.map((page) => page.page_number)} label={t("Review lettering placement")}
                  href={(page) => reviewUrl(page, "lettering")} />
              </CheckItem>
            )}
            {fixCount === 0 && uncheckedPages === 0 && placementReviews.length === 0 && (
              <CheckItem tone="done" title={t("Every page is ready to export.")} />
            )}
          </ul>
        )}
        {preflight && !checking && acceptedIssues > 0 && (
          <details className="mt-4">
            <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold">{t("Accepted decisions")} ({acceptedIssues})</summary>
            <ul className="space-y-2">
              {preflight.pages.filter((page) => page.accepted_editorial_issue_ids.length > 0).map((page) => (
                <li key={page.page_number}>
                  <Link className="inline-flex min-h-11 items-center font-body text-sm font-bold underline underline-offset-4" to={reviewUrl(page.page_number, "visual")}>
                    {t("Page")} {page.page_number} · {page.accepted_editorial_issue_ids.length} {t("accepted")}
                  </Link>
                </li>
              ))}
            </ul>
          </details>
        )}
        {retryPreflight.error && <p role="alert" className="mt-3 font-body text-sm text-hero-red">{retryPreflight.error.message}</p>}
      </section>

      <BookExportPanel project={id}
        packages={canExport && !exportBook.isPending ? packages : []}
        exportUrls={exportUrls} canExport={canExport} pending={exportBook.isPending}
        pendingFormat={exportBook.variables?.format} pendingForce={exportBook.variables?.force}
        error={exportBook.error} onCreate={createExport}
        blockedLabel={fixCount > 0 ? `${fixCount} ${t("{count, plural, one {fix needed first} other {fixes needed first}}", { count: fixCount })}` : undefined}
        unavailableReason={checking ? t("Checking edition…") : preflightError ? t("The book could not be checked.") : fixCount > 0 ? t("Fix what blocks export above, then create your package.") : undefined} />
      {newPackage && !isFetching && !preflightError && <p key={newPackage} role="status" onAnimationEnd={() => setNewPackage(null)} className="animate-register-stamp inline-block bg-narrator-gold px-3 py-2 font-meta text-sm font-bold">{t("Edition ready")} · {newPackage.split(":")[1].toUpperCase()}</p>}

      <BookPublication project={id} title={title} ready={canExport} onPreview={() => setReaderOpen(true)} />

      {finishDiagnostics.length ? (
        <section aria-label={t("TECHNICAL DIAGNOSTICS")}>
          <SectionHeader
            variant="underline"
            title={t("TECHNICAL DIAGNOSTICS")}
            description={t("Internal continuity evidence for development. It does not block export or require an editorial decision.")}
          />
          <div className="space-y-3">
            {finishDiagnostics.map((diagnostic) => (
              <Surface key={diagnostic.key} tone="gold" padding="md" border="soft" shadow="none">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-meta text-xs font-bold tracking-[0.08em] text-ink-muted">
                      {`${t("Page")} ${diagnostic.pageNumber}`}
                    </p>
                    <p className="mt-1 font-body text-sm font-bold leading-6">{diagnostic.message}</p>
                  </div>
                  {diagnostic.count > 1 && (
                    <span className="shrink-0 font-meta text-xs font-bold text-ink-muted">
                      ×{diagnostic.count}
                    </span>
                  )}
                </div>
                {diagnostic.evidence.length > 0 && (
                  <p className="mt-2 font-body text-xs leading-5 text-ink-black/70">
                    {diagnostic.evidence.join(" · ")}
                  </p>
                )}
              </Surface>
            ))}
          </div>
        </section>
      ) : null}

      {status?.parts && <CombinedExport project={id} parts={status.parts} />}

      <section id="book-credit-history" className="scroll-mt-6">
        <SectionHeader
          variant="underline"
          title={t("CREDIT HISTORY")}
          description={t("Credits used by this book across every edition and revision. Open an activity to see its hold, final charge, and released credits.")}
          actions={<Link to={`/credits?project=${encodeURIComponent(splitProjectKey(id).id)}`} className="inline-flex min-h-11 items-center font-meta text-xs font-bold underline underline-offset-4">{t("View all credit history")}</Link>}
        />
        <p className="mb-4 font-body text-sm leading-6 text-ink-muted">{t("Open holds are still reserved. They are separate from final charges.")}</p>
        {creditHistoryError && (
          <Surface tone="pulp" padding="md" shadow="none" role="alert" className="mb-4">
            <p className="font-body text-sm">{t("Credit history could not be loaded.")}</p>
            <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetchCreditHistory()}>{t("Retry credit history")}</Button>
          </Surface>
        )}
        {creditHistoryLoading ? (
          <div className="space-y-2">{[1, 2, 3].map((item) => <Skeleton key={item} className="h-14" />)}</div>
        ) : creditHistoryError && creditDayGroups.length === 0 ? null : creditDayGroups.length === 0 ? (
          <Surface border="soft" shadow="none" padding="md">
            <p className="font-body text-sm text-ink-muted">{t("No credit activity has been recorded for this book yet.")}</p>
          </Surface>
        ) : (
          <>
            <CreditHistoryLedger groups={creditDayGroups} projectNameMap={creditProjectNames} />
            {hasOlderCreditHistory && (
              <Button variant="outline" size="sm" fullWidth className="mt-5" disabled={isFetchingOlderCreditHistory} onClick={() => void fetchOlderCreditHistory()}>
                {t(isFetchingOlderCreditHistory ? "Loading history…" : "Load older history")}
              </Button>
            )}
          </>
        )}
      </section>
    </RoomShell>
  );
}

/** One line of the pre-export checklist. The rule colour says whether it blocks export. */
function CheckItem({ tone, title, pages = [], detail, subjects = [], evidence = [], children }: {
  tone: "fix" | "optional" | "done";
  title: string;
  pages?: number[];
  detail?: string | null;
  subjects?: string[];
  evidence?: string[];
  children?: ReactNode;
}) {
  const { t } = useI18n();
  const rule = tone === "fix" ? "border-hero-red" : tone === "optional" ? "border-narrator-gold" : "border-archive-sage";
  return (
    <li className={`border-l-[4px] ${rule} bg-bristol px-4 py-4 md:px-5`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="min-w-0 font-body text-sm font-bold leading-6">
          {pages.length === 1 && <span className="mr-2 font-meta text-xs text-ink-muted">{t("Page")} {pages[0]}</span>}
          {title}
        </p>
        {tone !== "done" && (
          <span className={`shrink-0 font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] ${tone === "fix" ? "text-hero-red" : "text-ink-muted"}`}>
            {tone === "fix" ? t("Blocks export") : t("Optional")}
          </span>
        )}
      </div>
      {subjects.length > 0 && <p className="mt-1 font-body text-sm leading-6">{subjects.join(" · ")}</p>}
      {detail && <p className="mt-1 font-body text-sm leading-6 text-ink-muted">{detail}</p>}
      {evidence.length > 0 && (
        <details className="mt-1 font-body text-xs leading-5 text-ink-muted">
          <summary className="min-h-11 cursor-pointer py-3">{t("Evidence")}</summary>
          <p className="break-words">{evidence.join(" · ")}</p>
        </details>
      )}
      {children && <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">{children}</div>}
    </li>
  );
}

/** A page link for one page; compact numbered links when a check spans many. */
function PageLinks({ pages, label, href }: { pages: number[]; label: string; href: (page: number) => string }) {
  const { t } = useI18n();
  if (pages.length === 1) {
    return (
      <Link className="inline-flex min-h-11 items-center font-meta text-xs font-bold text-hero-red underline underline-offset-4" to={href(pages[0])}>
        {label} · {t("Page")} {pages[0]}
      </Link>
    );
  }
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={label}>
      {pages.map((page) => (
        <li key={page}>
          <Link aria-label={`${label} · ${t("Page")} ${page}`} to={href(page)}
            className="inline-flex h-9 min-w-9 items-center justify-center border border-ink-black/25 bg-pulp-paper px-2 font-meta text-xs tabular-nums hover:border-ink-black hover:bg-ink-black hover:text-bristol focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red">
            {page}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * Rewrites one page's plan so it stops looking ahead of the story. Paid (one
 * planning call), confirmed with its estimate; the page's art is redrawn
 * separately afterwards, from Pages.
 */
function ReplanPageAction({ project, pageNumber, disabled, onReplanned }: {
  project: string;
  pageNumber: number;
  disabled?: boolean;
  onReplanned: () => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const estimate = useQuery({
    queryKey: ["project", project, "page-replan-estimate", pageNumber],
    queryFn: () => getPageReplanEstimate(project, pageNumber),
    enabled: open,
    retry: false,
  });
  const replan = useMutation({
    mutationFn: () => replanPage(project, pageNumber),
    onSuccess: () => { setOpen(false); onReplanned(); },
  });
  const label = `${t("Re-plan page")} ${pageNumber}`;
  return (
    <>
      <Button size="sm" disabled={disabled || replan.isPending} onClick={() => { replan.reset(); setOpen(true); }}>
        {replan.isPending ? t("Re-planning…") : label}
      </Button>
      {replan.isSuccess && <p role="status" className="basis-full font-body text-sm">{t("Page {page} was re-planned. Redraw it from Pages so the art matches.", { page: String(pageNumber) })}</p>}
      {replan.error && <p role="alert" className="basis-full font-body text-sm text-hero-red">{replan.error.message}</p>}
      <ConfirmDrawer
        open={open}
        title={label}
        body={t("Rewrites this page’s panel descriptions so every character keeps the look the story has reached. Its beats, lettering and the rest of the book stay as they are. The current artwork is kept until you redraw the page from Pages.")}
        cost={estimate.data}
        extraBody={estimate.error ? <p role="alert" className="font-body text-sm text-hero-red">{estimate.error.message}</p> : undefined}
        confirmLabel={label}
        busy={replan.isPending}
        disabled={!estimate.data}
        onClose={() => setOpen(false)}
        onConfirm={() => replan.mutate()}
      />
    </>
  );
}
