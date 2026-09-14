import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getPageCheckEstimate, recoverPageChecks, runFinishPreflight, type PageCheckEstimate } from "../../api/pages";
import { ConfirmDrawer } from "../composites";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";

export function PageCheckRecovery({ project, onRecovered, requested = 0 }: { project: string; onRecovered?: () => void; requested?: number }) {
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

  return <div className="space-y-3">
    <Button variant="outline" disabled={busy} onClick={() => void recover()}>
      {busy ? t("CHECKING TEXT…") : t("CHECK UNCHECKED PAGES")}
    </Button>
    {error && <p role="alert" className="text-sm text-hero-red">{error}</p>}
    {results.length > 0 && <div role="status" className="text-sm">
      <p>{t("Text checks completed")}: {results.filter((page) => page.status === "checked").length}</p>
      {results.filter((page) => page.status !== "checked" && page.status !== "undrawn").map((page) =>
        <p key={page.page_number}>{t("Page")} {page.page_number}: {t("Not checked — export is still available")}</p>)}
    </div>}
    {estimate && <ConfirmDrawer open title={t("Check text on saved pages?")}
      body={`${estimate.paid_pages} ${t("pages need a new text check. Artwork will not be redrawn. Cached checks are free.")}`}
      cost={estimate} confirmLabel={t("CONFIRM TEXT CHECK")} busy={busy}
      onClose={() => setEstimate(null)} onConfirm={() => void recover(estimate)} />}
  </div>;
}
