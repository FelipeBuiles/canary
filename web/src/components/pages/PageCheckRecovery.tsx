import { ErrorNotice } from "../composites/ErrorNotice";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getPageCheckEstimate, recoverPageChecks, runFinishPreflight, type PageCheckEstimate } from "../../api/pages";
import { ApiError } from "../../api/client";
import { ConfirmDrawer } from "../composites";
import { Button } from "../ui/Button";
import { useI18n } from "../../i18n";
import { invalidateProject } from "../../api/projectScope";

/** One calm line, after drawing settles, for pages whose automatic text check
 * didn't finish. Every page is checked as it is drawn; this only re-reads. */
export function PageCheckRecovery({ project, unchecked, onRecovered, requested = 0 }: { project: string; unchecked: number; onRecovered?: () => void; requested?: number }) {
  const { t } = useI18n();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [estimate, setEstimate] = useState<PageCheckEstimate | null>(null);
  const [error, setError] = useState<Error | string | null>(null);
  const [interrupted, setInterrupted] = useState(false);
  const [results, setResults] = useState<Array<{ page_number: number; status: string; error?: string }>>([]);

  const handled = useRef(0);
  const recover = useCallback(async (approved?: PageCheckEstimate) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setEstimate(null);
    try {
      const renders = Object.fromEntries((approved?.pages ?? []).flatMap((page) =>
        page.render_image_sha256 ? [[page.page_number, page.render_image_sha256]] : []));
      let result;
      let uncertain = interrupted;
      try {
        result = approved && interrupted
          ? await recoverPageChecks(project, true, renders, crypto.randomUUID())
          : await recoverPageChecks(project, !!approved, renders);
        if (approved) uncertain = false;
      } catch (cause) {
        if (!approved || !(cause instanceof TypeError
          || (cause instanceof ApiError && (cause.status >= 500 || cause.code === "idempotency_indeterminate")))) throw cause;
        // A lost batch response does not erase checks already saved. Read those
        // back without permitting another provider call or clearing its receipt.
        uncertain = true;
        setInterrupted(true);
        result = await recoverPageChecks(project, false, {});
      }
      setResults(result.pages);
      setEstimate(null);
      if (uncertain && result.pages.some((page) => page.status !== "checked" && page.status !== "undrawn")) {
        setError(t("The earlier check was interrupted. Saved checks are preserved. Refresh saved checks to see any completed results before requesting another check."));
      } else {
        setInterrupted(false);
      }
      await invalidateProject(client, project);
      await runFinishPreflight(project);
      await invalidateProject(client, project);
      onRecovered?.();
      if (!approved && result.pages.some((page) => page.status === "requires_ocr")) {
        setEstimate(await getPageCheckEstimate(project));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }, [busy, client, interrupted, onRecovered, project, t]);

  useEffect(() => {
    if (requested > handled.current && !busy) {
      handled.current = requested;
      void recover();
    }
  }, [requested, busy, recover]);

  const failed = results.filter((page) => page.status !== "checked" && page.status !== "undrawn").length;
  const message = busy ? t("Checking pages…")
    : results.length && !failed ? t("All pages checked.")
    : failed ? t("{count, plural, one {The text check still didn't finish on # page.} other {The text check still didn't finish on # pages.}}", { count: failed })
    : t("{count, plural, one {The text check didn't finish on # page. Checking again never redraws it.} other {The text check didn't finish on # pages. Checking again never redraws them.}}", { count: unchecked });
  return <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-l-[3px] border-narrator-gold bg-bristol px-3 py-2">
    <p role="status" className="min-w-0 flex-1 font-body text-sm leading-6">{message}</p>
    {!(results.length && !failed) && <Button size="xs" variant="outline" disabled={busy} onClick={() => void recover()}>
      {interrupted ? t("Refresh saved checks") : failed ? t("Try again") : t("Check again")}
    </Button>}
    {error && <ErrorNotice error={error instanceof Error ? error : null} recovery={typeof error === "string" ? error : undefined} operation="generate" />}
    {estimate && <ConfirmDrawer open title={t("Check the remaining pages?")}
      body={`${estimate.paid_pages} ${t("pages need a new check. Artwork will not be redrawn. Saved checks are free.")}${interrupted ? ` ${t("The interrupted check may still be charged. Confirm only if you want to start a new check for pages without saved results.")}` : ""}`}
      cost={estimate} confirmLabel={t("CHECK PAGES")} busy={busy}
      onClose={() => setEstimate(null)} onConfirm={() => void recover(estimate)} />}
  </div>;
}
