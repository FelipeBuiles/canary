import { BookOpen, ArrowDown } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  useCompletePages,
  useExport,
  useFinishPreflight,
  useProjectStatus,
  useProviderUsage,
  useRunFinishPreflight,
} from "../../api/queries";
import { pageCompositePreviewUrl } from "../../api/lettering";
import { pageRenderPreviewUrl } from "../../api/pages";
import { BookExportPanel } from "../../components/book/BookExportPanel";
import { PageThumbnail } from "../../components/pages/PageThumbnail";
import { BookReader } from "../../components/BookReader";
import { PageCheckRecovery } from "../../components/pages/PageCheckRecovery";
import {
  RoomHeader,
  RoomShell,
  SectionHeader,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { StatusPill } from "../../components/ui/StatusPill";
import { Surface } from "../../components/ui/Surface";
import { useI18n } from "../../i18n";
import { readerPages } from "../../lib/bookReader";
import { useShowDevContent } from "../../lib/devContent";
import type { FinishPreflight, InvariantFailure } from "../../types/api";

type FinishFindingGroup = {
  key: string;
  pageNumber: number | null;
  pageNumbers?: number[];
  message: string;
  evidence: string[];
  count: number;
};

function groupFinishFindings(preflight?: FinishPreflight): FinishFindingGroup[] {
  if (!preflight) return [];
  const groups = new Map<string, FinishFindingGroup>();

  const add = (finding: InvariantFailure, pageNumber: number | null) => {
    const key = `${pageNumber === null ? "book" : "pages"}:${finding.code}:${finding.message}`;
    const existing = groups.get(key);
    if (existing) {
      existing.count += 1;
      if (pageNumber !== null) existing.pageNumbers?.push(pageNumber);
      existing.evidence = Array.from(new Set([...existing.evidence, ...finding.evidence]));
      return;
    }
    groups.set(key, {
      key,
      pageNumber,
      pageNumbers: pageNumber === null ? [] : [pageNumber],
      message: finding.message,
      evidence: finding.evidence,
      count: 1,
    });
  };

  preflight.packaging_failures.forEach((finding) => add(finding, null));
  preflight.pages.forEach((page) => {
    page.invariant_failures.forEach((finding) => add(finding, page.page_number));
  });
  return Array.from(groups.values());
}

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
  const providerUsage = useProviderUsage(id, showDevContent);
  const { data: status } = useProjectStatus(id);
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
  const bookPages = useMemo(() => readerPages(completePages), [completePages]);
  const [readerOpen, setReaderOpen] = useState(false);
  const [exportUrls, setExportUrls] = useState<Partial<Record<"pdf" | "cbz", string>>>({});
  const [newPackage, setNewPackage] = useState<string | null>(null);

  if (!id) return null;
  if (finishStatus === "pending" && !shouldRunPreflight) {
    return (
      <RoomShell project={id}>
        <StagePlaceholder
          project={id}
          stage="finish"
          status="pending"
        />
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
  const finishFindings = groupFinishFindings(preflight);
  const finishDiagnostics = showDevContent ? groupFinishDiagnostics(preflight) : [];
  const editorialSummary = unresolvedIssues > 0
    ? `${unresolvedIssues} ${unresolvedIssues === 1 ? t("unresolved editorial issue") : t("unresolved editorial issues")}`
    : acceptedIssues > 0
      ? `${acceptedIssues} ${acceptedIssues === 1 ? t("accepted editorial issue") : t("accepted editorial issues")}`
      : t("No editorial issues");
  const title = status?.project_name ?? t("Your book");
  const packages = preflight?.packages ?? [];
  const reviewUrl = (pageNumber: number, review: "checks" | "visual" | "lettering") =>
    `/project/${encodeURIComponent(id)}/pages?page=${pageNumber}&review=${review}`;
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


      <section aria-label={t("Read your book")} className="grid items-center gap-8 bg-ink-black p-6 text-bristol shadow-paper md:grid-cols-[minmax(0,1.4fr)_minmax(0,0.6fr)] md:p-9">
        <div className="min-w-0">
          <h2 className="break-words font-display text-3xl font-black leading-tight tracking-[-0.03em] md:text-5xl">{title}</h2>
          <p className="mt-4 font-meta text-sm text-bristol/85">{completePages ? `${bookPages.length} ${bookPages.length === 1 ? t("page drawn") : t("pages drawn")}` : pagesLoading ? t("Loading artwork…") : t("Page previews are unavailable.")}</p>
          <p className="mt-4 max-w-[52ch] font-body text-base leading-7 text-bristol/85">{t("Take a final read, then bring your edition off the screen.")}</p>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            {bookPages.length > 0 && <Button variant="onInk" onClick={() => setReaderOpen(true)}><BookOpen size={18} aria-hidden="true" />{t("Read your book")}</Button>}
            <a href={canExport ? "#book-downloads" : "#edition-checks"} className="inline-flex min-h-11 items-center gap-2 px-3 font-meta text-sm text-bristol underline underline-offset-4 hover:text-narrator-gold">{canExport ? t("Download your edition") : t("Review edition checks")}<ArrowDown size={16} aria-hidden="true" /></a>
          </div>
          <p className="mt-4 font-body text-xs leading-6 text-bristol/75">{t("Reading does not generate artwork or use credits.")}</p>
        </div>
        {bookPages.length > 0 && <button type="button" onClick={() => setReaderOpen(true)} aria-label={t("Open the book reader")} className="mx-auto h-80 w-full max-w-[240px] bg-surface-container text-ink-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold md:h-96 md:max-w-[280px]">
          <PageThumbnail reveal={false} onRevealEnd={() => {}} src={(bookPages[0].hybrid ? pageCompositePreviewUrl(id, bookPages[0].pageNumber, bookPages[0].revision, "reader", bookPages[0].letteringRevision) : pageRenderPreviewUrl(id, bookPages[0].pageNumber, bookPages[0].revision, "reader"))} alt={t("First page of the book")} />
        </button>}
      </section>

      <BookExportPanel project={id}
        packages={canExport && !exportBook.isPending ? packages : []}
        exportUrls={exportUrls} canExport={canExport} pending={exportBook.isPending}
        pendingFormat={exportBook.variables?.format} pendingForce={exportBook.variables?.force}
        error={exportBook.error} onCreate={createExport}
        unavailableReason={isLoading || isFetching || retryPreflight.isPending ? t("Checking edition…") : preflightError ? t("The book could not be checked.") : undefined} />
      {newPackage && !isFetching && !preflightError && <p key={newPackage} role="status" onAnimationEnd={() => setNewPackage(null)} className="animate-register-stamp inline-block bg-narrator-gold px-3 py-2 font-meta text-sm font-bold">{t("Edition ready")} · {newPackage.split(":")[1].toUpperCase()}</p>}

      {readerOpen && (
        <BookReader
          project={id}
          pages={bookPages}
          onClose={() => setReaderOpen(false)}
        />
      )}

      <section id="edition-checks" tabIndex={-1} className="scroll-mt-6">
        <SectionHeader
          variant="underline"
          title={t("EDITION CHECKS")}
          description={t("Export checks cover files and page versions. Review artwork and wording in Pages; optional text checks do not block export.")}
        />

        {isLoading || isFetching || retryPreflight.isPending ? (
          <Surface padding="lg" border="soft" shadow="none" role="status" aria-live="polite">
            <p className="font-meta text-sm font-bold">{t("Checking edition…")}</p>
            <p className="mt-2 max-w-[60ch] font-body text-sm font-semibold leading-6 text-ink-muted">
              {t("Finish is loading the last check and will run again only if this edition changed.")}
            </p>
          </Surface>
        ) : preflight && !preflightError ? (
          <Surface padding="md" border="soft" shadow="none">
            <div className="flex flex-wrap items-center gap-3">
              <StatusPill tone={exportBlockers === 0 ? "sage" : "red"}>
                {exportBlockers === 0 ? t("Ready to package") : t("Review needed")}
              </StatusPill>
              <span className="font-body text-sm font-bold">{readyPages} {readyPages === 1 ? t("page ready") : t("pages ready")}</span>
              <span className="font-body text-sm">{technicalFindingCount === 0 ? t("No technical blockers") : `${technicalFindingCount} ${t("technical findings")}`}</span>
              <span className="font-body text-sm">{editorialSummary}</span>
            </div>
            {acceptedIssues > 0 && (
              <details className="mt-3">
                <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs font-bold">{t("Accepted decisions")}</summary>
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
          </Surface>
        ) : (
          <Surface padding="md" tone="red" border="hard" shadow="paper" role="alert">
            <p className="font-body text-sm font-bold leading-6">
              {t("The book could not be checked.")}
            </p>
            <Button className="mt-3" variant="outline" disabled={isFetching} onClick={() => void refetch()}>
              {isFetching ? t("Checking edition…") : t("Retry edition checks")}
            </Button>
          </Surface>
        )}
        {retryPreflight.error && <p role="alert" className="mt-3 font-body text-sm text-hero-red">{retryPreflight.error.message}</p>}
      </section>
      {completePages?.pages.some((page) => page.active_render && page.analysis_recovery?.status !== "checked") && (
        <details className="space-y-3">
          <summary className="cursor-pointer py-3 font-meta text-sm font-bold">{t("Optional text review")}</summary>
          <p className="text-sm text-ink-muted">{t("Look for possible wording differences. You can export without running this check.")}</p>
          <PageCheckRecovery project={id} onRecovered={() => void refetch()} />
        </details>
      )}

      {unresolvedIssues > 0 && (
        <section aria-label={t("Editorial decisions")}>
          <SectionHeader variant="underline" title={t("Editorial decisions")} description={t("Review these concerns before packaging. Revised artwork still needs a decision.")} />
          <ul className="space-y-3">
            {preflight?.pages.flatMap((page) => page.unresolved_editorial_issue_ids.map((issueId) => {
              const issue = pageIssues.get(issueId);
              return (
                <li key={issueId}>
                  <Surface padding="md" tone="gold" border="soft" shadow="none">
                    <p className="font-body text-sm font-bold">{t("Page")} {page.page_number}: {issue?.requested_correction || t("An editorial concern needs your review.")}</p>
                    {issue?.status === "revised" && <p className="mt-2 font-body text-sm">{t("Revised — not yet confirmed fixed")}</p>}
                    <Link className="mt-2 inline-flex min-h-11 items-center font-meta text-xs font-bold underline underline-offset-4" to={reviewUrl(page.page_number, "visual")}>
                      {t("Review page")} {page.page_number}
                    </Link>
                  </Surface>
                </li>
              );
            }))}
          </ul>
        </section>
      )}

      {finishFindings.length ? (
        <section aria-label={t("VALIDATION FINDINGS")}>
          <SectionHeader
            variant="underline"
            title={t("VALIDATION FINDINGS")}
            description={t("These technical checks are separate from your editorial review decisions.")}
          />
          <div className="space-y-3">
            {finishFindings.map((finding) => (
              <Surface key={finding.key} tone="pulp" padding="md" border="soft" shadow="none">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-meta text-xs font-bold tracking-[0.08em]">
                      {finding.pageNumber === null ? t("BOOK") : `${t("Page")} ${finding.pageNumbers?.join(", ") ?? finding.pageNumber}`}
                    </p>
                    <p className="mt-1 font-body text-sm font-bold leading-6">{finding.message}</p>
                  </div>
                  {finding.count > 1 && (
                    <span className="shrink-0 font-meta text-xs font-bold">
                      ×{finding.count}
                    </span>
                  )}
                </div>
                {finding.evidence.length > 0 && (
                  <details className="mt-2 font-body text-xs leading-5">
                    <summary className="min-h-11 cursor-pointer py-3">{t("Evidence")}</summary>
                    <p>{finding.evidence.join(" · ")}</p>
                  </details>
                )}
                {finding.pageNumber !== null ? (
                  <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">{Array.from(new Set(finding.pageNumbers ?? [finding.pageNumber])).map((pageNumber) => <Link key={pageNumber} className="inline-flex min-h-11 items-center font-meta text-xs font-bold text-hero-red underline underline-offset-4" to={reviewUrl(pageNumber, finding.key.includes("lettering_layout") ? "lettering" : "checks")}>
                    {t("Open page checks")} · {t("Page")} {pageNumber}
                  </Link>)}</div>
                ) : (
                  <Button className="mt-3" variant="outline" disabled={isFetching || retryPreflight.isPending} onClick={() => retryPreflight.mutate({ project: id })}>
                    {retryPreflight.isPending ? t("Checking edition…") : t("Retry edition checks")}
                  </Button>
                )}
              </Surface>
            ))}
          </div>
        </section>
      ) : null}

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

      {preflight?.correction_requests.length ? (
        <section>
          <SectionHeader variant="underline" title={t("PAGE CORRECTIONS")} />
          <div className="space-y-3">
            {preflight.correction_requests.map((request) => (
              <Surface key={request.id} padding="md" border="soft" shadow="none">
                <p className="font-body text-sm font-bold">
                  {t("Page")} {request.page_number}: {request.requested_correction}
                </p>
                <Link className="mt-2 inline-flex min-h-11 items-center font-meta text-xs font-bold underline underline-offset-4" to={reviewUrl(request.page_number, "checks")}>
                  {t("Open page checks")} · {t("Page")} {request.page_number}
                </Link>
              </Surface>
            ))}
          </div>
        </section>
      ) : null}

      {showDevContent && (
        <Surface padding="md" border="soft" shadow="none">
          <h2 className="font-meta font-bold">{t("PROVIDER COSTS")}</h2>
          {providerUsage.error && <p role="alert">{t("Provider usage is unavailable.")}</p>}
          {providerUsage.data && <>
            <p>${providerUsage.data.known_cost_usd.toFixed(4)} {t("recorded provider cost; separate from charged credits")}</p>
            {providerUsage.data.artifact_link_error && <p role="status">{providerUsage.data.artifact_link_error}</p>}
            {!providerUsage.data.complete && <p>{t("Incomplete cost evidence")}: {providerUsage.data.unknown_cost_count} {t("unpriced calls")}, {providerUsage.data.artifact_calls_missing_from_events} {t("missing events")}</p>}
            <p className="font-body text-xs">{Object.entries(providerUsage.data.cost_sources).map(([source, count]) => `${source}: ${count}`).join(" · ")}</p>
            <table className="mt-3 w-full text-left font-body text-sm">
              <thead><tr><th>{t("Page")}</th><th>{t("Operation")}</th><th>{t("Calls")}</th><th>USD</th></tr></thead>
              <tbody>{providerUsage.data.groups.map((group) => <tr key={`${group.page_number}:${group.category}`}>
                <td>{group.page_number ?? "—"}</td><td>{group.category}</td><td>{group.call_count}</td><td>{group.known_cost_usd.toFixed(4)}{group.unknown_cost_count ? " + ?" : ""}</td>
              </tr>)}</tbody>
            </table>
          </>}
        </Surface>
      )}
    </RoomShell>
  );
}
