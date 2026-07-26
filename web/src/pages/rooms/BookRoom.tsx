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

export function BookRoom() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const { data: status } = useProjectStatus(id);
  const finishStatus = status?.stages.finish?.status ?? "pending";
  const { data: preflight, isLoading } = useFinishPreflight(
    id,
    finishStatus === "complete" || status?.finish_ready === true,
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
  const blockingFailures = (preflight?.packaging_failures.length ?? 0)
    + (preflight?.pages.reduce((total, page) => total + page.invariant_failures.length, 0) ?? 0);
  const canExport = !preflight || (blockingFailures === 0 && unresolvedIssues === 0);

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
          description={t("Creative corrections return to Draw; Finish never changes page artwork.")}
        />

        {isLoading ? (
          <Surface padding="lg" border="soft" shadow="none">
            <p className="font-meta text-sm font-bold">{t("CHECKING THE BOOK…")}</p>
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
              <StatusPill tone={blockingFailures === 0 ? "sage" : "red"}>
                {t("PREFLIGHT")}
              </StatusPill>
              <p className="mt-4 font-display text-2xl font-black uppercase">
                {blockingFailures === 0 ? t("No blocking failures") : `${blockingFailures} ${t("blocking failures")}`}
              </p>
            </Surface>
            <Surface padding="md" border="hard" shadow="paper">
              <StatusPill tone="gold">{t("ISSUES")}</StatusPill>
              <p className="mt-4 font-display text-2xl font-black uppercase">
                {acceptedIssues} {acceptedIssues === 1 ? t("accepted editorial issue") : t("accepted editorial issues")}
              </p>
              {unresolvedIssues > 0 && (
                <p className="mt-2 font-body text-sm font-bold text-hero-red">
                  {unresolvedIssues} {unresolvedIssues === 1 ? t("unresolved issue") : t("unresolved issues")}
                </p>
              )}
            </Surface>
          </div>
        ) : (
          <Surface padding="md" tone="gold" border="hard" shadow="paper">
            <p className="font-body text-sm font-bold leading-6">
              {t("Finish preflight runs before the first export. It does not call an image model.")}
            </p>
          </Surface>
        )}
      </section>

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
            disabled={exportBook.isPending || !canExport}
          >
            {t("EXPORT PDF")}
          </Button>
          <Button
            variant="outline"
            onClick={() => exportBook.mutate({ project: id, format: "cbz" })}
            disabled={exportBook.isPending || !canExport}
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
