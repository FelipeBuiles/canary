import { useEffect, useRef, useState } from "react";
import { operatorFetch, type OperatorConnection } from "../api/operator";
import source from "./tester-tracker.html?raw";

type RecordRow = { id: string; revision: number; data: Record<string, unknown> };
type Snapshot = Record<string, RecordRow[]>;
const themeTokens = [
  "--color-hero-red", "--color-pulp-paper", "--color-bristol", "--color-ink-black",
  "--color-ink-muted", "--color-ink-soft", "--color-surface-container", "--color-narrator-gold",
  "--color-ghost-shadow", "--color-secondary-container", "--color-on-secondary-container",
  "--color-ready", "--color-on-gold", "--color-warn-orange", "--font-display", "--font-body", "--font-meta",
];
const collections = ["people", "sessions", "notes", "findings"];

/** Keep the reference workflow isolated; only the operator host can access the API. */
export function TesterTracker({ connection }: { connection: OperatorConnection }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [storageError, setStorageError] = useState<string | null>(null);
  useEffect(() => {
    let disposed = false;
    let snapshot: Snapshot = {};
    let loaded = false;
    let queue = Promise.resolve();
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || !event.data?.tracker) return;
      const message = event.data;
      queue = queue.catch(() => {}).then(async () => {
        try {
          if (message.action === "load") {
            snapshot = await operatorFetch<Snapshot>("/api/ops/backoffice/tester-tracker", connection);
            loaded = true;
          } else if (message.action === "write" && collections.includes(message.collection)) {
            if (!loaded) throw new Error("Storage is disconnected. Reload the tracker before saving.");
            const current = snapshot[message.collection]?.find(row => row.id === message.recordId);
            const row = await operatorFetch<RecordRow>(`/api/ops/backoffice/tester-tracker/${message.collection}/${encodeURIComponent(message.recordId)}`, connection, {
              method: "PUT",
              body: JSON.stringify({ mode: message.mode, data: message.data ?? {}, expected_revision: current?.revision ?? 0 }),
            });
            snapshot[message.collection] = (snapshot[message.collection] ?? []).filter(item => item.id !== row.id);
            if (message.mode !== "delete") snapshot[message.collection].push(row);
          } else throw new Error("Invalid tracker request");
          if (!disposed) setStorageError(null);
          const styles = getComputedStyle(document.documentElement);
          const theme = Object.fromEntries(themeTokens.map(token => [token, styles.getPropertyValue(token).trim()]));
          const result = Object.fromEntries(collections.map(col => [col, (snapshot[col] ?? []).map(row => ({ ...row.data, id: row.id }))]));
          if (!disposed) (event.source as Window).postMessage({ tracker: true, id: message.id, result, theme }, "*");
        } catch (error) {
          const detail = error && typeof error === "object" && "status" in error && error.status === 404
            ? "This server does not provide the tester tracker API. Connect to the updated backend before saving."
            : error instanceof Error ? error.message : "Tracker request failed";
          if (!disposed) setStorageError(detail);
          if (!disposed) (event.source as Window).postMessage({ tracker: true, id: message.id, error: detail }, "*");
        }
      });
    };
    window.addEventListener("message", receive);
    return () => { disposed = true; window.removeEventListener("message", receive); };
  }, [connection]);
  return <div className="flex min-w-0 flex-1 flex-col">{storageError && <p role="alert" className="border-b-2 border-hero-red bg-pulp-paper px-6 py-4 font-body text-sm text-hero-red">Not saved: {storageError}</p>}<iframe ref={frame} title="Tester session tracker" sandbox="allow-scripts allow-forms" srcDoc={source} className="block w-full flex-1 border-0 bg-pulp-paper" style={{ width: "100%", minHeight: "calc(100dvh - 150px)" }} /></div>;
}
