import { useCallback, useEffect, useState } from "react";
import { operatorFetch, type OperatorConnection } from "../api/operator";
import { Button } from "./ui/Button";
import { Surface } from "./ui/Surface";

type RuntimeSetting = {
  key: string; kind: string; description: string; minimum: number | null; maximum: number | null;
  unset_means: string; editable: boolean; value: string; source: string; environment_value: string;
};
type RuntimeSettings = { store: string; settings: RuntimeSetting[] };

const PATH = "/api/ops/backoffice/settings";
const SOURCE: Record<string, string> = {
  database: "Stored here", environment: "Host environment", unset: "Not set", safe: "Held off: settings unreadable",
};
const STORE: Record<string, string> = {
  absent: "The settings table is not installed on this server, so every value comes from the host environment. Apply docs/migrations/2026-11-12-app-settings.sql to edit them here.",
  unavailable: "The settings table could not be read. Give-away settings are held off until it can be.",
};

/** Operator settings that apply without a restart: stored value, else host environment, else default. */
export function RuntimeSettingsPanel({ connection }: { connection: OperatorConnection }) {
  const [data, setData] = useState<RuntimeSettings | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");

  const refresh = useCallback(async () => {
    try {
      setData(await operatorFetch<RuntimeSettings>(PATH, connection));
      setError("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not load the settings.");
    }
  }, [connection]);
  useEffect(() => {
    const load = async () => { await refresh(); };
    void load();
  }, [refresh]);

  async function change(key: string, value: string | null) {
    setPending(key);
    try {
      const path = `${PATH}/${encodeURIComponent(key)}`;
      setData(await operatorFetch<RuntimeSettings>(path, connection, value === null
        ? { method: "DELETE" } : { method: "PUT", body: JSON.stringify({ value }) }));
      setDrafts(current => Object.fromEntries(Object.entries(current).filter(([name]) => name !== key)));
      setError("");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The setting was not changed.");
    } finally {
      setPending("");
    }
  }

  return <Surface className="mb-6 space-y-4 p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2>Live settings</h2><p>These apply within a minute, without a restart. A stored value overrides the host environment; removing it restores the environment value or the default.</p></div>
      <Button variant="secondary" onClick={() => void refresh()}>Refresh settings</Button>
    </div>
    {error && <p role="alert" className="bg-chip-red/50 px-3 py-2 font-body text-sm font-semibold text-hero-red">{error}</p>}
    {data && STORE[data.store] && <p role="status" className="bg-chip-gold px-3 py-2 font-body text-sm font-semibold text-ink-black">{STORE[data.store]}</p>}
    {!data && !error && <p role="status">Loading settings…</p>}
    {data && <ul className="divide-y-[2px] divide-ink-black/10">
      {data.settings.map((setting) => {
        const draft = drafts[setting.key];
        const busy = pending === setting.key;
        const range = setting.minimum !== null && setting.maximum !== null ? ` Allowed: ${setting.minimum} to ${setting.maximum}.` : "";
        return <li key={setting.key} className="grid gap-2 py-3 md:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] md:items-center">
          <div className="min-w-0">
            <div className="break-all font-meta text-[0.62rem] font-bold tracking-[0.04em] text-ink-black">{setting.key}</div>
            <p className="font-body text-sm text-ink-soft">{setting.description}{range}</p>
            <p className="font-body text-xs text-ink-muted">
              {setting.value ? <>Now: <strong className="break-all">{setting.value}</strong> · {SOURCE[setting.source] ?? setting.source}</> : <>Not set: {setting.unset_means}</>}
              {!setting.editable && data.store === "loaded" && " · Changed in the host environment only"}
            </p>
          </div>
          {setting.editable && <form className="flex flex-wrap items-center gap-2" onSubmit={(event) => { event.preventDefault(); if (draft?.trim()) void change(setting.key, draft); }}>
            <input aria-label={`New value for ${setting.key}`} value={draft ?? ""} placeholder={setting.kind === "bool" ? "true or false" : setting.kind === "date" ? "2026-12-22" : "New value"}
              onChange={(event) => setDrafts((current) => ({ ...current, [setting.key]: event.target.value }))}
              className="h-10 min-w-0 flex-1 border-[2px] border-ink-black/18 bg-bristol px-2.5 font-body text-sm text-ink-black outline-none focus:border-hero-red" />
            <Button type="submit" disabled={busy || !draft?.trim()}>Save</Button>
            {setting.source === "database" && <Button type="button" variant="secondary" disabled={busy} onClick={() => void change(setting.key, null)}>Remove</Button>}
          </form>}
        </li>;
      })}
    </ul>}
  </Surface>;
}
