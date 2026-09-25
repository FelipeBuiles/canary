import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getPageCheckEstimate, recoverPageChecks, runFinishPreflight, type PageCheckEstimate } from "../../api/pages";
import { ConfirmDrawer } from "../composites";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";

/** One calm line for pages drawn without a page read (older books, or a read that failed).
 * New pages are read automatically as they are drawn. */
export function PageCheckRecovery({ project, unchecked, editable = true, onRecovered, requested = 0 }: { project: string; unchecked: number; editable?: boolean; onRecovered?: () => void; requested?: number }) {
  const { t } = useI18n();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [estimate, setEstimate] = useState<PageCheckEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Array<{ page_number: number; status: string; error?: string }>>([]);

  const handled = useRef(0);
  const recover = useCallback(async (approved?: PageCheckEstimate) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const renders = Object.fromEntries((approved?.pages ?? []).flatMap((page) =>
        page.render_image_sha256 ? [[page.page_number, page.render_image_sha256]] : []));
      const result = await recoverPageChecks(project, !!approved, renders);
      setResults(result.pages);
      setEstimate(null);
      await client.invalidateQueries({ queryKey: ["project", project] });
      await runFinishPreflight(project);
      await client.invalidateQueries({ queryKey: ["project", project] });
      onRecovered?.();
      if (!approved && result.pages.some((page) => page.status === "requires_ocr")) {
        setEstimate(await getPageCheckEstimate(project));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }, [busy, client, onRecovered, project]);

  useEffect(() => {
    if (requested > handled.current && !busy) {
      handled.current = requested;
      void recover();
    }
  }, [requested, busy, recover]);

  const failed = results.filter((page) => page.status !== "checked" && page.status !== "undrawn").length;
  const message = busy ? t("Checking pages…")
    : results.length && !failed ? t("All pages checked.")
    : failed ? `${failed} ${t(failed === 1 ? "page couldn’t be checked. Export still works." : "pages couldn’t be checked. Export still works.")}`
    : editable
      ? `${unchecked} ${t(unchecked === 1 ? "page isn’t checked yet. Checking places balloons around faces and spots stray lettering." : "pages aren’t checked yet. Checking places balloons around faces and spots stray lettering.")}`
      : `${unchecked} ${t(unchecked === 1 ? "page hasn’t had a text check. It can suggest wording differences; export still works." : "pages haven’t had a text check. It can suggest wording differences; export still works.")}`;
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-l-[3px] border-narrator-gold bg-bristol px-3 py-2">
    <p role="status" className="min-w-0 flex-1 font-body text-sm leading-6">{message}</p>
    {!(results.length && !failed) && <Button size="xs" variant="outline" disabled={busy} onClick={() => void recover()}>
      {failed ? t("Try again") : t("Check pages")}
    </Button>}
    {error && <p role="alert" className="w-full text-sm text-hero-red">{error}</p>}
    {estimate && <ConfirmDrawer open title={t("Check the remaining pages?")}
      body={`${estimate.paid_pages} ${t("pages need a new check. Artwork will not be redrawn. Saved checks are free.")}`}
      cost={estimate} confirmLabel={t("CHECK PAGES")} busy={busy}
      onClose={() => setEstimate(null)} onConfirm={() => void recover(estimate)} />}
  </div>;
}
