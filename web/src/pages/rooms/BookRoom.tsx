import { ErrorNotice } from "../../components/composites/ErrorNotice";
import { BookPublication } from "../../components/book/BookPublication";
import { MoreHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
import { pageDisplayImage } from "../../lib/pageState";
import { getPageReplanEstimate, replanPage } from "../../api/pages";
import { BookExportPanel } from "../../components/book/BookExportPanel";
import { CreditHistoryLedger } from "../../components/credits/CreditHistoryLedger";
import { CreditSpendSummary } from "../../components/credits/CreditSpendSummary";
import { BookDesk } from "../../components/book/BookDesk";
import { cn } from "../../lib/cn";
import { BookReader } from "../../components/BookReader";
import { PageCheckRecovery } from "../../components/pages/PageCheckRecovery";
import {
  ConfirmDrawer,
  RoomHeader,
  RoomShell,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/Skeleton";
import { useI18n } from "../../i18n";
import { deskIndexForPage, deskViews, readerPages } from "../../lib/bookReader";
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
  const [deskIndex, setDeskIndex] = useState(0);
  const views = useMemo(() => deskViews(bookPages, !!status?.has_cover), [bookPages, status?.has_cover]);
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
  const packages = preflight?.packages ?? [];
  const reviewUrl = (pageNumber: number, review: "page" | "lettering") =>
    `/project/${encodeURIComponent(id)}/pages?page=${pageNumber}&review=${review}`;
  const uncheckedPages = completePages?.pages.filter((page) => page.active_render && page.analysis_recovery?.status !== "checked").length ?? 0;
  // Pages the desk marks: anything that blocks export.
  const flaggedPages = new Set<number>([
    ...findings.flatMap((finding) => finding.pageNumbers),
    ...(preflight?.pages.filter((page) => page.unresolved_editorial_issue_ids.length > 0).map((page) => page.page_number) ?? []),
    ...(preflight?.correction_requests.map((request) => request.page_number) ?? []),
  ]);
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

  const coverSrc = status?.has_cover ? `/api${projectPath(id)}/files/cover/cover.png` : pageDisplayImage(id, bookPages[0] ?? { pageNumber: 1, revision: 1 });
  const showPage = (pageNumber: number) => setDeskIndex(deskIndexForPage(views, pageNumber));
  const thumbOf = (pageNumber: number) => {
    const page = bookPages.find((item) => item.pageNumber === pageNumber);
    return page ? pageDisplayImage(id, page, "thumbnail") : undefined;
  };
  const statusLine = checking ? null
    : preflight && !preflightError ? t("{ready} of {total} pages pass", { ready: String(readyPages), total: String(preflight.pages.length) })
    : null;
  const hasChecks = !!preflight && !checking && !preflightError
    && (fixCount > 0 || uncheckedPages > 0 || placementReviews.length > 0 || acceptedIssues > 0);

  return (
    <RoomShell project={id} bleed>
      <RoomHeader
        title={t("Book")}
        lead={completePages ? `${bookPages.length} ${bookPages.length === 1 ? t("page drawn") : t("pages drawn")}` : undefined}
      />

      {readerOpen && (
        <BookReader
          project={id}
          pages={bookPages}
          onClose={() => setReaderOpen(false)}
        />
      )}

      <div className="flex min-h-[34rem] flex-1 flex-col studio-desktop:min-h-0 studio-desktop:flex-row">
        {bookPages.length > 0 ? (
          <BookDesk project={id} views={views} index={Math.min(deskIndex, Math.max(views.length - 1, 0))} onIndex={setDeskIndex}
            coverSrc={coverSrc} flagged={flaggedPages} onRead={() => setReaderOpen(true)} />
        ) : (
          <section aria-label={t("Your book")} className="benday-ink flex min-h-[24rem] flex-1 items-center justify-center p-8 text-center">
            <p className="font-meta text-sm text-on-chrome-muted">{pagesLoading ? t("Loading artwork…") : t("Page previews are unavailable.")}</p>
          </section>
        )}

        <aside aria-label={title} className="flex shrink-0 flex-col border-t border-ink-black/12 bg-bristol text-ink-black studio-desktop:w-[24rem] studio-desktop:border-l studio-desktop:border-t-0">
          <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 pb-8 pt-5">
            <header>
              <h2 className="text-balance break-words font-display text-[1.625rem] font-black uppercase leading-[0.95] tracking-[-0.03em]">{title}</h2>
              <div role="status" className={cn("mt-4 flex items-center gap-2.5 border-l-[3px] px-3 py-2.5",
                checking ? "border-ink-black/30 bg-surface-container"
                  : preflightError || !preflight || fixCount > 0 ? "border-hero-red bg-hero-red/[0.06]"
                  : "border-ready bg-ready/[0.08]")}>
                <span className="font-meta text-[0.8125rem] font-semibold">
                  {checking ? t("Checking edition…")
                    : preflightError || !preflight ? t("The book could not be checked.")
                    : fixCount > 0 ? `${fixCount} ${t("{count, plural, one {fix needed before export} other {fixes needed before export}}", { count: fixCount })}`
                    : t("Ready to export")}
                </span>
                {statusLine && <span className="ml-auto shrink-0 font-meta text-xs text-ink-muted">{statusLine}</span>}
              </div>
              {!checking && placementReviews.length > 0 && (
                <p className="mt-2 font-meta text-xs text-ink-muted">
                  <span aria-hidden="true" className="mr-1.5 inline-block size-1.5 bg-narrator-gold align-middle" />
                  {placementReviews.length} {t("{count, plural, one {page to check by eye} other {pages to check by eye}}", { count: placementReviews.length })}
                </p>
              )}
            </header>

            {(!preflight || preflightError) && !checking && (
              <ErrorNotice error={preflightError} operation="load" title="The book could not be checked."
                onRetry={() => void refetch()} retryDisabled={isFetching} retryLabel={t("Retry edition checks")} />
            )}

            {hasChecks && preflight && (
              <section id="edition-checks" tabIndex={-1} aria-labelledby="edition-checks-heading" className="scroll-mt-6">
                <PanelHeading id="edition-checks-heading">{t("Before you export")}</PanelHeading>
                <ul className="mt-3 space-y-2">
                  {findings.map((finding) => (
                    <CheckItem key={finding.key} tone="fix"
                      title={finding.copy ? t(finding.copy.title) : finding.message}
                      pages={finding.pageNumbers}
                      thumb={finding.pageNumbers.length === 1 ? thumbOf(finding.pageNumbers[0]) : undefined}
                      onShow={finding.pageNumbers.length > 0 ? () => showPage(finding.pageNumbers[0]) : undefined}
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
                          href={(page) => reviewUrl(page, finding.copy?.review ?? "page")} />
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
                      <CheckItem key={issueId} tone="fix" pages={[page.page_number]} thumb={thumbOf(page.page_number)} onShow={() => showPage(page.page_number)}
                        title={issue?.requested_correction || t("An editorial concern needs your review.")}
                        detail={issue?.status === "revised" ? t("Revised — not yet confirmed fixed") : t("Accept it as it is, or ask for a revision.")}>
                        <Link className={PANEL_LINK} to={reviewUrl(page.page_number, "page")}>
                          {t("Review page")} {page.page_number}
                        </Link>
                      </CheckItem>
                    );
                  }))}
                  {preflight.correction_requests.map((request) => (
                    <CheckItem key={request.id} tone="fix" pages={[request.page_number]} thumb={thumbOf(request.page_number)} onShow={() => showPage(request.page_number)}
                      title={request.requested_correction}
                      detail={t("A correction was requested for this page and hasn’t been drawn yet.")}>
                      <Link className={PANEL_LINK} to={reviewUrl(request.page_number, "page")}>
                        {t("Open page checks")} · {t("Page")} {request.page_number}
                      </Link>
                    </CheckItem>
                  ))}
                  {uncheckedPages > 0 && <li><PageCheckRecovery project={id} unchecked={uncheckedPages} onRecovered={() => void refetch()} /></li>}
                  {placementReviews.length > 0 && (
                    <CheckItem tone="optional" pages={placementReviews.map((page) => page.page_number)}
                      title={t("{count, plural, one {Lettering on # page hasn’t been checked by eye} other {Lettering on # pages hasn’t been checked by eye}}", { count: placementReviews.length })}
                      detail={t("Balloons were placed automatically. Open each page’s Lettering to check faces, reading order and quiet spaces, then mark it reviewed. Export isn’t blocked.")}>
                      <Link className="inline-flex min-h-9 items-center gap-2 bg-ink-black px-3 font-meta text-xs font-semibold text-bristol hover:bg-ink-black/85"
                        to={reviewUrl(placementReviews[0].page_number, "lettering")}>
                        {t("Start with page")} {placementReviews[0].page_number}
                      </Link>
                      <PageLinks pages={placementReviews.map((page) => page.page_number)} label={t("Review lettering placement")}
                        href={(page) => reviewUrl(page, "lettering")} />
                    </CheckItem>
                  )}
                </ul>
                {acceptedIssues > 0 && (
                  <details className="mt-2">
                    <summary className="min-h-9 cursor-pointer py-2 font-meta text-xs font-semibold text-ink-muted hover:text-ink-black">{t("Accepted decisions")} ({acceptedIssues})</summary>
                    <ul className="space-y-1">
                      {preflight.pages.filter((page) => page.accepted_editorial_issue_ids.length > 0).map((page) => (
                        <li key={page.page_number}>
                          <Link className={PANEL_LINK} to={reviewUrl(page.page_number, "page")}>
                            {t("Page")} {page.page_number} · {page.accepted_editorial_issue_ids.length} {t("accepted")}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </section>
            )}
            {retryPreflight.error && <ErrorNotice error={retryPreflight.error} operation="generate" />}

            <BookExportPanel project={id}
              packages={canExport && !exportBook.isPending ? packages : []}
              exportUrls={exportUrls} canExport={canExport} pending={exportBook.isPending}
              pendingFormat={exportBook.variables?.format} pendingForce={exportBook.variables?.force}
              error={exportBook.error} onCreate={createExport}
              blockedLabel={fixCount > 0 ? `${fixCount} ${t("{count, plural, one {fix needed first} other {fixes needed first}}", { count: fixCount })}` : undefined}
              unavailableReason={checking ? t("Checking edition…") : preflightError ? t("The book could not be checked.") : undefined}
              menu={(items) => <PanelMenu items={items} />}>
              {newPackage && !isFetching && !preflightError && <p key={newPackage} role="status" onAnimationEnd={() => setNewPackage(null)} className="animate-register-stamp mt-3 inline-block bg-narrator-gold px-3 py-1.5 font-meta text-xs font-bold">{t("Edition ready")} · {newPackage.split(":")[1].toUpperCase()}</p>}
              {status?.parts && status.parts.length > 1 && (
                <details className="mt-3 border-t border-ink-black/10 pt-1">
                  <summary className="min-h-9 cursor-pointer py-2 font-meta text-xs font-semibold text-ink-muted hover:text-ink-black">{t("Combine parts")}</summary>
                  <CombinedExport project={id} parts={status.parts} bare />
                </details>
              )}
            </BookExportPanel>

            <div id="book-share" tabIndex={-1} className="scroll-mt-6 border-t border-ink-black/10 pt-5">
              <BookPublication project={id} title={title} ready={canExport} onPreview={() => setReaderOpen(true)} />
            </div>

            <section id="book-credit-history" tabIndex={-1} aria-label={t("Credit history")} className="scroll-mt-6 border-t border-ink-black/10 pt-5">
              <CreditSpendSummary compact spendByStage={creditHistory?.pages[0]?.spend_by_stage} />
              {creditHistoryError && (
                <div role="alert" className="mt-3">
                  <p className="font-body text-xs">{t("Credit history could not be loaded.")}</p>
                  <Button variant="outline" size="sm" className="mt-2" onClick={() => void refetchCreditHistory()}>{t("Retry credit history")}</Button>
                </div>
              )}
              <details className="mt-2">
                <summary className="min-h-9 cursor-pointer py-2 font-meta text-xs font-semibold text-ink-muted hover:text-ink-black">{t("History")}</summary>
                {creditHistoryLoading ? (
                  <div className="space-y-2">{[1, 2, 3].map((item) => <Skeleton key={item} className="h-12" />)}</div>
                ) : creditHistoryError && creditDayGroups.length === 0 ? null : creditDayGroups.length === 0 ? (
                  <p className="font-body text-xs text-ink-muted">{t("No credit activity has been recorded for this book yet.")}</p>
                ) : (
                  <>
                    <CreditHistoryLedger groups={creditDayGroups} />
                    {hasOlderCreditHistory && (
                      <Button variant="outline" size="sm" fullWidth className="mt-4" disabled={isFetchingOlderCreditHistory} onClick={() => void fetchOlderCreditHistory()}>
                        {t(isFetchingOlderCreditHistory ? "Loading history…" : "Load older history")}
                      </Button>
                    )}
                  </>
                )}
                <Link to={`/credits?project=${encodeURIComponent(splitProjectKey(id).id)}`} className={cn(PANEL_LINK, "mt-1")}>{t("View all credit history")}</Link>
              </details>
            </section>

            {finishDiagnostics.length ? (
              <section aria-label={t("TECHNICAL DIAGNOSTICS")} className="border-t border-ink-black/10 pt-5">
                <PanelHeading>{t("TECHNICAL DIAGNOSTICS")}</PanelHeading>
                <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{t("Internal continuity evidence for development. It does not block export or require an editorial decision.")}</p>
                <ul className="mt-3 space-y-2">
                  {finishDiagnostics.map((diagnostic) => (
                    <li key={diagnostic.key} className="border border-narrator-gold/50 bg-narrator-gold/10 px-3 py-2.5">
                      <p className="font-meta text-xs text-ink-muted">
                        {`${t("Page")} ${diagnostic.pageNumber}`}{diagnostic.count > 1 && ` · ×${diagnostic.count}`}
                      </p>
                      <p className="mt-1 font-body text-sm font-semibold leading-5">{diagnostic.message}</p>
                      {diagnostic.evidence.length > 0 && <p className="mt-1 font-body text-xs leading-5 text-ink-black/70">{diagnostic.evidence.join(" · ")}</p>}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        </aside>
      </div>
    </RoomShell>
  );
}

const PANEL_LINK = "inline-flex min-h-9 items-center font-meta text-xs font-semibold underline decoration-ink-black/25 underline-offset-4 hover:decoration-ink-black";

function PanelHeading({ id, children }: { id?: string; children: ReactNode }) {
  return <h3 id={id} className="font-meta text-[0.6875rem] font-bold uppercase tracking-[0.14em] text-ink-muted">{children}</h3>;
}

/** The panel's quiet extras (rebuilding a package), kept behind one button. */
function PanelMenu({ items }: { items: Array<{ key: string; label: string; disabled?: boolean; onSelect: () => void }> }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    function close(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <div ref={rootRef} className="relative">
      <button type="button" aria-expanded={open} aria-haspopup="true" aria-label={t("More download options")} title={t("More download options")}
        onClick={() => setOpen((value) => !value)}
        className="flex size-8 items-center justify-center text-ink-muted transition-colors hover:bg-surface-container hover:text-ink-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
        <MoreHorizontal size={18} aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-48 border border-ink-black/12 bg-bristol py-1 shadow-float">
          {items.map((item) => (
            <button key={item.key} type="button" disabled={item.disabled}
              onClick={() => { setOpen(false); item.onSelect(); }}
              className="flex h-9 w-full items-center px-3 text-left font-meta text-[0.8125rem] font-medium text-ink-black transition-colors hover:bg-sidebar-tint disabled:cursor-not-allowed disabled:text-ink-soft disabled:hover:bg-transparent">
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** One thing to settle before export. Its stamp says whether it blocks export. */
function CheckItem({ tone, title, pages = [], thumb, onShow, detail, subjects = [], evidence = [], children }: {
  tone: "fix" | "optional";
  title: string;
  pages?: number[];
  /** The page's thumbnail; selecting it turns the book to that page. */
  thumb?: string;
  onShow?: () => void;
  detail?: string | null;
  subjects?: string[];
  evidence?: string[];
  children?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <li className="flex gap-3 border border-ink-black/12 bg-bristol p-3">
      {thumb && onShow && (
        <button type="button" onClick={onShow} aria-label={`${t("Show")} · ${t("Page")} ${pages[0]}`}
          className="relative h-[4.5rem] w-12 shrink-0 bg-ink-black outline outline-1 outline-ink-black/15 transition-[outline-color] hover:outline-ink-black focus-visible:outline-2 focus-visible:outline-hero-red">
          <img src={thumb} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-meta text-[0.6875rem] font-semibold">
          {pages.length === 1 && <span className="text-ink-muted">{t("Page")} {pages[0]}</span>}
          <span className={tone === "fix" ? "text-status-blocked-text" : "text-ink-muted"}>
            {tone === "fix" ? t("Blocks export") : t("Optional")}
          </span>
        </p>
        <p className="mt-1 font-body text-sm font-semibold leading-5">{title}</p>
        {subjects.length > 0 && <p className="mt-1 font-body text-xs leading-5">{subjects.join(" · ")}</p>}
        {detail && <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{detail}</p>}
        {evidence.length > 0 && (
          <details className="mt-1 font-body text-xs leading-5 text-ink-muted">
            <summary className="min-h-8 cursor-pointer py-1.5">{t("Evidence")}</summary>
            <p className="break-words">{evidence.join(" · ")}</p>
          </details>
        )}
        {children && <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">{children}</div>}
      </div>
    </li>
  );
}

/** A page link for one page; compact numbered links when a check spans many. */
function PageLinks({ pages, label, href }: { pages: number[]; label: string; href: (page: number) => string }) {
  const { t } = useI18n();
  if (pages.length === 1) {
    return (
      <Link className={PANEL_LINK} to={href(pages[0])}>
        {label} · {t("Page")} {pages[0]}
      </Link>
    );
  }
  return (
    <ul className="flex flex-wrap gap-1" aria-label={label}>
      {pages.map((page) => (
        <li key={page}>
          <Link aria-label={`${label} · ${t("Page")} ${page}`} to={href(page)}
            className="inline-flex h-8 min-w-8 items-center justify-center border border-ink-black/20 px-1.5 font-meta text-xs tabular-nums hover:border-ink-black hover:bg-ink-black hover:text-bristol focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red">
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
      {replan.error && <ErrorNotice error={replan.error} operation="generate" />}
      <ConfirmDrawer
        open={open}
        title={label}
        body={t("Rewrites this page’s panel descriptions so every character keeps the look the story has reached. Its beats, lettering and the rest of the book stay as they are. The current artwork is kept until you redraw the page from Pages.")}
        cost={estimate.data}
        extraBody={estimate.error ? <ErrorNotice error={estimate.error} operation="estimate" /> : undefined}
        confirmLabel={label}
        busy={replan.isPending}
        disabled={!estimate.data}
        onClose={() => setOpen(false)}
        onConfirm={() => replan.mutate()}
      />
    </>
  );
}
