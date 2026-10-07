import { useState } from "react";
import { useI18n } from "../../i18n";
import { errorDetails } from "../../lib/errorPresentation";
import { Button } from "../ui/Button";

export function ErrorDetails({ error, detail, code }: { error?: unknown; detail?: string | null; code?: string | null }) {
  const { t } = useI18n();
  const [copyState, setCopyState] = useState<"ready" | "copied" | "failed">("ready");
  const text = errorDetails(error, detail, code);
  if (!text) return null;
  return <details className="mt-2 min-w-0" onToggle={(event) => { if (!event.currentTarget.open) setCopyState("ready"); }}>
    <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm font-semibold">{t("Technical details")}</summary>
    <pre tabIndex={0} className="mb-3 max-h-64 overflow-y-auto whitespace-pre-wrap font-mono text-xs leading-5 text-ink-muted [overflow-wrap:anywhere]">{text}</pre>
    <Button variant="outline" size="sm" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setCopyState("copied"); }
      catch { setCopyState("failed"); }
    }}>{t("Copy details")}</Button>
    {copyState !== "ready" && <p role="status" className="mt-2 font-body text-sm text-ink-muted">
      {t(copyState === "copied" ? "Details copied." : "Copying did not work. Select the details above to copy them.")}
    </p>}
  </details>;
}
