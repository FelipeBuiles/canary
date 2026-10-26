import { useState, type ReactNode } from "react";
import { Download } from "lucide-react";
import { downloadExportUrl } from "../../api/pages";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import type { FinishPreflight } from "../../types/api";
import { ConfirmDrawer } from "../composites";
import { ErrorNotice } from "../composites/ErrorNotice";
import { Button } from "../ui/Button";

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
  /** The panel's quiet menu, which also offers Rebuild. */
  menu: (items: Array<{ key: string; label: string; disabled?: boolean; onSelect: () => void }>) => ReactNode;
  children?: ReactNode;
}

/** One way out: pick a format, then one button creates or downloads it. */
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
  menu,
  children,
}: BookExportPanelProps) {
  const { t } = useI18n();
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [rebuildFormat, setRebuildFormat] = useState<ExportFormat | null>(null);
  const saved = packages.find((item) => item.format === format);
  const working = pending && pendingFormat === format;
  const workingLabel = pendingForce
    ? (format === "pdf" ? t("Rebuilding PDF…") : t("Rebuilding CBZ…"))
    : (format === "pdf" ? t("Creating PDF…") : t("Creating CBZ…"));

  return (
    <section id="book-downloads" tabIndex={-1} aria-labelledby="book-export-heading" className="scroll-mt-6">
      <div className="flex items-center justify-between gap-3">
        <h3 id="book-export-heading" className="font-meta text-[0.6875rem] font-bold uppercase tracking-[0.14em] text-ink-muted">{t("Download")}</h3>
        {menu((["pdf", "cbz"] as const).map((item) => ({
          key: `rebuild-${item}`,
          label: item === "pdf" ? t("Rebuild PDF") : t("Rebuild CBZ"),
          disabled: pending || !canExport,
          onSelect: () => setRebuildFormat(item),
        })))}
      </div>

      <div role="radiogroup" aria-label={t("Format")} className="mt-3 grid grid-cols-2 border border-ink-black/15 p-0.5">
        {(["pdf", "cbz"] as const).map((item) => (
          <button key={item} type="button" role="radio" aria-checked={format === item} onClick={() => setFormat(item)}
            className={cn("flex h-9 items-center justify-center font-meta text-xs font-semibold transition-colors",
              format === item ? "bg-ink-black text-pulp-paper" : "text-ink-muted hover:bg-sidebar-tint hover:text-ink-black",
              "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-hero-red")}>
            {item.toUpperCase()}
          </button>
        ))}
      </div>
      <p className="mt-2 font-body text-xs leading-5 text-ink-muted">
        {format === "pdf" ? t("For reading and printing.") : t("An image archive for comic-reader apps.")}
      </p>

      {error && <div className="mt-3"><ErrorNotice error={error} operation="export" /></div>}

      <div className="mt-4">
        {saved && !working ? (
          <a href={exportUrls[format] ?? downloadExportUrl(project, format)}
            className="flex min-h-12 w-full items-center justify-center gap-2 border-[2px] border-ink-black bg-hero-red px-4 font-meta text-sm font-semibold text-bristol shadow-press transition-[translate,box-shadow,background-color] hover:translate-x-px hover:translate-y-px hover:bg-hero-red-press hover:shadow-[2px_2px_0_0_var(--color-ink-black)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-hero-red">
            <Download size={16} aria-hidden="true" />
            {format === "pdf" ? t("Download PDF") : t("Download CBZ")}
          </a>
        ) : (
          <Button fullWidth size="lg" variant="primary" disabled={pending || !canExport} onClick={() => onCreate(format)}>
            {working ? workingLabel : format === "pdf" ? t("Create PDF") : t("Create CBZ")}
          </Button>
        )}
        <p role="status" className="mt-2 font-body text-xs leading-5 text-ink-muted">
          {working ? t("Takes about a minute. No credits.")
            : saved ? t("Ready to download")
            : !canExport ? (blockedLabel ?? unavailableReason ?? t("Waiting for edition checks"))
            : t("Takes about a minute. No credits.")}
        </p>
        {!canExport && blockedLabel && unavailableReason && <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{unavailableReason}</p>}
      </div>
      {children}

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
