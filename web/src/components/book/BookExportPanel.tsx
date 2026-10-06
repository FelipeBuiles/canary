import { useState } from "react";
import { Archive, Check, Download, FileText } from "lucide-react";
import { downloadExportUrl } from "../../api/pages";
import { useI18n } from "../../i18n";
import type { FinishPreflight } from "../../types/api";
import { ConfirmDrawer, EntityCard, SectionHeader } from "../composites";
import { Button } from "../ui/Button";
import { StatusPill } from "../ui/StatusPill";
import { Surface } from "../ui/Surface";
import { Stamp, useArrival } from "../ui/motion";

type ExportFormat = "pdf" | "cbz";

interface BookExportPanelProps {
  project: string;
  packages: FinishPreflight["packages"];
  exportUrls: Partial<Record<ExportFormat, string>>;
  canExport: boolean;
  pending: boolean;
  pendingFormat?: ExportFormat;
  pendingForce?: boolean;
  error?: Error | null;
  unavailableReason?: string;
  /** Short status for formats that can't be created yet, e.g. "2 fixes needed first". */
  blockedLabel?: string;
  onCreate: (format: ExportFormat, force?: boolean) => void;
}

export function BookExportPanel({
  project,
  packages,
  exportUrls,
  canExport,
  pending,
  pendingFormat,
  pendingForce,
  error,
  unavailableReason,
  blockedLabel,
  onCreate,
}: BookExportPanelProps) {
  const { t } = useI18n();
  const [rebuildFormat, setRebuildFormat] = useState<ExportFormat | null>(null);

  return (
    <section id="book-downloads" tabIndex={-1} className="scroll-mt-6" aria-labelledby="book-export-heading">
      <div id="book-export-heading">
        <SectionHeader variant="underline" title={t("Take your book with you")} description={t("Choose a format for the way you read.")} />
      </div>
      {error && (
        <Surface role="alert" tone="gold" padding="md" shadow="none" className="mb-4">
          <p className="break-words font-body text-sm font-bold">{error.message}</p>
        </Surface>
      )}
      {!canExport && (
        <p className="mb-4 font-body text-sm leading-6 text-ink-muted">
          {unavailableReason ?? t("Resolve the edition checks before creating a package.")}
        </p>
      )}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,18rem),1fr))] gap-4">
        {(["pdf", "cbz"] as const).map((format) => {
          const saved = packages.find((item) => item.format === format);
          const working = pending && pendingFormat === format;
          const FormatIcon = format === "pdf" ? FileText : Archive;
          const workingLabel = pendingForce
            ? (format === "pdf" ? t("Rebuilding PDF…") : t("Rebuilding CBZ…"))
            : (format === "pdf" ? t("Creating PDF…") : t("Creating CBZ…"));
          return (
            <EntityCard key={format} padding="tight">
              {saved && !working && <PrintedStamp saved={!!saved} />}
              <div className="flex flex-wrap items-start justify-between gap-3">
                <FormatIcon aria-hidden="true" size={28} strokeWidth={1.5} className="text-ink-muted" />
                <StatusPill tone={working ? "gold" : saved ? "sage" : "pulp"}>
                  {saved && !working && <Check size={14} aria-hidden="true" className="mr-1.5" />}
                  {working ? workingLabel : saved ? t("Ready to download") : !canExport ? (blockedLabel ?? t("Waiting for edition checks")) : t("Not created yet")}
                </StatusPill>
              </div>
              <h3 className="mt-5 font-display text-3xl font-black leading-none tracking-tight">{format.toUpperCase()}</h3>
              <p className="mt-3 font-body text-sm leading-6 text-ink-muted">
                {format === "pdf" ? t("For reading and printing.") : t("An image archive for comic-reader apps.")}
              </p>
              <div className="mt-auto pt-6">
                {saved ? (
                  <a
                    href={exportUrls[format] ?? downloadExportUrl(project, format)}
                    className="inline-flex min-h-11 w-full items-center justify-center gap-2 border-[2px] border-ink-black bg-ink-black px-4 py-3 font-meta text-xs font-bold text-bristol transition-colors hover:bg-hero-red focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red"
                  >
                    <Download size={16} aria-hidden="true" />
                    {t("DOWNLOAD")} {format.toUpperCase()}
                  </a>
                ) : (
                  <Button fullWidth variant="primary" disabled={pending || !canExport} onClick={() => onCreate(format)}>
                    {working ? workingLabel : format === "pdf" ? t("Create PDF") : t("Create CBZ")}
                  </Button>
                )}
              </div>
            </EntityCard>
          );
        })}
      </div>
      <details className="mt-5 border-t border-ink-black/15">
        <summary className="min-h-11 cursor-pointer py-4 font-body text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red">{t("Rebuild package")}</summary>
        <p className="font-body text-sm leading-6 text-ink-muted">
          {t("Missing or damaged download? Rebuild it from your saved pages. This replaces package files, not artwork, and uses no credits.")}
        </p>
        <div className="mt-3 flex flex-wrap gap-3">
          {(["pdf", "cbz"] as const).map((format) => (
            <Button key={format} variant="outline" disabled={pending || !canExport} onClick={() => setRebuildFormat(format)}>
              {pending && pendingFormat === format && pendingForce
                ? (format === "pdf" ? t("Rebuilding PDF…") : t("Rebuilding CBZ…"))
                : (format === "pdf" ? t("Rebuild PDF") : t("Rebuild CBZ"))}
            </Button>
          ))}
        </div>
      </details>
      <ConfirmDrawer
        open={rebuildFormat !== null}
        title={rebuildFormat === "pdf" ? t("Rebuild PDF") : t("Rebuild CBZ")}
        body={t("Rebuilding replaces existing package files with a fresh copy from your saved pages. Your page artwork and review decisions stay unchanged. No credits are used.")}
        confirmLabel={rebuildFormat === "pdf" ? t("Rebuild PDF") : t("Rebuild CBZ")}
        busy={pending || !canExport}
        onClose={() => setRebuildFormat(null)}
        onConfirm={() => {
          if (!rebuildFormat || pending || !canExport) return;
          onCreate(rebuildFormat, true);
          setRebuildFormat(null);
        }}
      />
    </section>
  );
}


/** Rests on a finished package; slams in when the package lands while watched. */
function PrintedStamp({ saved }: { saved: boolean }) {
  const { t } = useI18n();
  const { arrived, settle } = useArrival(saved);
  return (
    <Stamp play={arrived} onSettled={settle} rotate={-8} className="pointer-events-none absolute right-5 top-[4.75rem]">
      {t("Printed")}
    </Stamp>
  );
}
