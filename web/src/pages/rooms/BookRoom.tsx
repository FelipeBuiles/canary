import { useParams } from "react-router-dom";
import {
  useExport,
  useFinishPreflight,
  useProjectStatus,
} from "../../api/queries";
import { downloadExportUrl } from "../../api/pages";
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
import type { FinishPreflight, InvariantFailure } from "../../types/api";

type FinishFindingGroup = {
  key: string;
  pageNumber: number | null;
  message: string;
  evidence: string[];
  count: number;
};

function groupFinishFindings(preflight?: FinishPreflight): FinishFindingGroup[] {
  if (!preflight) return [];
  const groups = new Map<string, FinishFindingGroup>();

  const add = (finding: InvariantFailure, pageNumber: number | null) => {
    const key = `${pageNumber ?? "book"}:${finding.code}:${finding.message}`;
    const existing = groups.get(key);
    if (existing) {
      existing.count += 1;
      existing.evidence = Array.from(new Set([...existing.evidence, ...finding.evidence]));
      return;
    }
    groups.set(key, {
      key,
      pageNumber,
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

export function BookRoom() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const { data: status } = useProjectStatus(id);
  const finishStatus = status?.stages.finish?.status ?? "pending";
  const drawComplete = status?.stages.draw?.status === "complete";
  const shouldRunPreflight =
    drawComplete || finishStatus === "complete" || status?.finish_ready === true;
  const { data: preflight, isLoading } = useFinishPreflight(
    id,
    shouldRunPreflight,
  );
  const exportBook = useExport();

  if (!id) return null;
  if (finishStatus === "pending" && status?.stages.draw?.status !== "complete") {
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
  const canExport = !!preflight && !isLoading && exportBlockers === 0;
  const finishFindings = groupFinishFindings(preflight);
  const editorialTone = unresolvedIssues > 0
    ? "red"
    : acceptedIssues > 0
      ? "gold"
      : "sage";
  const editorialSummary = unresolvedIssues > 0
    ? `${unresolvedIssues} ${unresolvedIssues === 1 ? t("unresolved editorial issue") : t("unresolved editorial issues")}`
    : acceptedIssues > 0
      ? `${acceptedIssues} ${acceptedIssues === 1 ? t("accepted editorial issue") : t("accepted editorial issues")}`
      : t("No editorial issues");

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker={t("BOOK")}
        title={t("FINISH & EXPORT")}
        lead={t("Finish verifies every complete page, production dimensions, issue decisions, and package order.")}
      />

      <section>
        <SectionHeader
          variant="underline"
          title={t("FINISH PREFLIGHT")}
          description={t("Finish checks the book before export. Creative corrections return to Draw; Finish never changes page artwork.")}
        />

        {isLoading ? (
          <Surface padding="lg" border="soft" shadow="none" role="status" aria-live="polite">
            <p className="font-meta text-sm font-bold">{t("CHECKING THE BOOK…")}</p>
            <p className="mt-2 max-w-[60ch] font-body text-sm font-semibold leading-6 text-ink-muted">
              {t("Finish is checking every page before export.")}
            </p>
          </Surface>
        ) : preflight ? (
          <div className="grid gap-4 md:grid-cols-3">
            <Surface padding="md" border="hard" shadow="paper">
              <StatusPill tone={readyPages === preflight.pages.length ? "sage" : "gold"}>
                {t("PAGES")}
              </StatusPill>
              <p className="mt-4 font-display text-2xl font-black uppercase">
                {readyPages} {readyPages === 1 ? t("page ready") : t("pages ready")}
              </p>
            </Surface>
            <Surface padding="md" border="hard" shadow="paper">
              <StatusPill tone={technicalFindingCount === 0 ? "sage" : "red"}>
                {t("PREFLIGHT")}
              </StatusPill>
              <p className="mt-4 font-display text-2xl font-black uppercase">
                {technicalFindingCount === 0
                  ? t("No technical blockers")
                  : `${technicalFindingCount} ${t("technical findings")}`}
              </p>
            </Surface>
            <Surface padding="md" border="hard" shadow="paper">
              <StatusPill tone={editorialTone}>
                {acceptedIssues > 0 || unresolvedIssues > 0 ? t("ISSUES") : t("NO EDITORIAL ISSUES")}
              </StatusPill>
              <p className="mt-4 font-display text-2xl font-black uppercase">
                {editorialSummary}
              </p>
              {unresolvedIssues > 0 && (
                <p className="mt-2 font-body text-sm font-bold text-hero-red">
                  {t("These decisions must be resolved before export.")}
                </p>
              )}
            </Surface>
          </div>
        ) : (
          <Surface padding="md" tone="red" border="hard" shadow="paper" role="alert">
            <p className="font-body text-sm font-bold leading-6">
              {t("The book could not be checked.")}
            </p>
            <p className="mt-2 font-body text-sm font-semibold leading-6">
              {t("Refresh the page and try again.")}
            </p>
          </Surface>
        )}
      </section>

      {finishFindings.length ? (
        <section aria-label={t("VALIDATION FINDINGS")}>
          <SectionHeader
            variant="underline"
            title={t("VALIDATION FINDINGS")}
            description={t("These technical checks are separate from your editorial review decisions.")}
          />
          <div className="space-y-3">
            {finishFindings.map((finding) => (
              <Surface key={finding.key} tone="red" padding="md" border="hard" shadow="paper-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-meta text-xs font-bold tracking-[0.08em] text-hero-red">
                      {finding.pageNumber === null ? t("BOOK") : `${t("Page")} ${finding.pageNumber}`}
                    </p>
                    <p className="mt-1 font-body text-sm font-bold leading-6">{finding.message}</p>
                  </div>
                  {finding.count > 1 && (
                    <span className="shrink-0 font-meta text-xs font-bold text-ink-muted">
                      ×{finding.count}
                    </span>
                  )}
                </div>
                {finding.evidence.length > 0 && (
                  <p className="mt-2 font-body text-xs leading-5 text-ink-black/70">
                    {finding.evidence.join(" · ")}
                  </p>
                )}
              </Surface>
            ))}
          </div>
        </section>
      ) : null}

      {preflight?.correction_requests.length ? (
        <section>
          <SectionHeader variant="underline" title={t("CORRECTIONS RETURNED TO DRAW")} />
          <div className="space-y-3">
            {preflight.correction_requests.map((request) => (
              <Surface key={request.id} padding="md" border="soft" shadow="none">
                <p className="font-body text-sm font-bold">
                  {t("Page")} {request.page_number}: {request.requested_correction}
                </p>
              </Surface>
            ))}
          </div>
        </section>
      ) : null}

      <section>
        <SectionHeader
          variant="underline"
          title={t("EXPORT")}
          description={t("Create a verified reading copy or archive package.")}
        />
        {exportBook.error && (
          <Surface tone="gold" padding="md" border="hard" shadow="none" className="mb-4">
            <p className="font-body text-sm font-bold">{exportBook.error.message}</p>
          </Surface>
        )}
        <div className="flex flex-wrap gap-3">
          <Button
            onClick={() => exportBook.mutate({ project: id, format: "pdf" })}
            disabled={exportBook.isPending || isLoading || !canExport}
          >
            {t("EXPORT PDF")}
          </Button>
          <Button
            variant="outline"
            onClick={() => exportBook.mutate({ project: id, format: "cbz" })}
            disabled={exportBook.isPending || isLoading || !canExport}
          >
            {t("EXPORT CBZ")}
          </Button>
          {preflight?.packages.map((item) => (
            <a
              key={item.format}
              href={downloadExportUrl(id, item.format)}
              className="inline-flex min-h-11 items-center border-[2px] border-ink-black bg-bristol px-4 font-meta text-xs font-bold tracking-[0.1em] text-ink-black"
            >
              {t("DOWNLOAD")} {item.format.toUpperCase()}
            </a>
          ))}
        </div>
      </section>
    </RoomShell>
  );
}
