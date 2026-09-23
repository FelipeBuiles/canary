import { useEffect, useState, type FormEvent } from "react";
import {
  fetchOperatorModels,
  updateOperatorModels,
  type OperatorConnection,
  type OperatorModelSettings,
} from "../api/operator";
import { Button } from "./ui/Button";
import { SelectField } from "./ui/Field";
import { Surface } from "./ui/Surface";

export function OperatorModelPanel({ connection }: { connection: OperatorConnection }) {
  const [settings, setSettings] = useState<OperatorModelSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchOperatorModels(connection).then((result) => {
      if (cancelled) return;
      setSettings(result);
      setError(null);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load stage models.");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [connection]);

  if (loading) return <p role="status" className="font-body text-sm">Loading stage models…</p>;
  if (!settings) return <p role="alert" className="font-body text-sm text-hero-red">{error ?? "Could not load stage models."}</p>;

  const changes = Object.fromEntries(Object.entries(draft).filter(([stage, model]) => settings.selections[stage] !== model));
  const changed = Object.keys(changes).length > 0;
  const byId = new Map(settings.models.map((model) => [model.id, model]));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!changed || saving) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const result = await updateOperatorModels(changes, connection);
      setSettings(result);
      setDraft({});
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save stage models.");
    } finally {
      setSaving(false);
    }
  }

  return <form aria-label="Operator stage models" onSubmit={submit} className="space-y-5">
    <header>
      <p className="font-meta text-[0.55rem] font-bold uppercase tracking-[0.14em] text-hero-red">Generation settings</p>
      <h1 className="mt-2 font-display text-3xl font-black tracking-tight">Stage models</h1>
      <p className="mt-3 max-w-2xl font-body text-sm leading-6 text-ink-muted">{settings.note}</p>
      <p className="mt-2 max-w-2xl font-body text-sm leading-6 text-ink-muted">Changing Draw requires a new edition or project for existing artwork. Saving does not start generation.</p>
    </header>
    <Surface border="soft" shadow="none" className="divide-y-2 divide-ink-black/10">
      {settings.stages.map((stage) => {
        const selected = draft[stage.id] ?? settings.selections[stage.id];
        return <div key={stage.id} className="grid gap-3 p-4 md:grid-cols-[minmax(0,1fr)_minmax(220px,360px)] md:items-center md:gap-8 md:p-5">
          <div>
            <label htmlFor={`operator-model-${stage.id}`} className="font-meta text-xs font-bold uppercase tracking-[0.08em]">{stage.label}</label>
            <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{stage.description}</p>
          </div>
          <div>
            <SelectField id={`operator-model-${stage.id}`} name={stage.id} value={selected} disabled={saving}
              onChange={(event) => { setDraft((current) => ({ ...current, [stage.id]: event.target.value })); setSaved(false); }}
              className="w-full bg-bristol font-body text-sm">
              {stage.model_ids.map((id) => <option key={id} value={id}>{byId.get(id)?.label ?? id}</option>)}
            </SelectField>
            <p className="mt-1 font-body text-xs text-ink-muted">{byId.get(selected)?.provider ?? "Unknown provider"}</p>
          </div>
        </div>;
      })}
    </Surface>
    <p className="font-body text-xs leading-5 text-ink-muted">Finish packages the book and has no separate model.</p>
    {error && <p role="alert" className="font-body text-sm text-hero-red">{error}</p>}
    {saved && <p role="status" className="font-body text-sm">Stage models saved for new jobs across all projects.</p>}
    <div className="flex flex-wrap gap-3">
      <Button type="submit" disabled={!changed || saving}>{saving ? "Saving…" : "Save stage models"}</Button>
      {changed && <Button type="button" variant="outline" disabled={saving} onClick={() => { setDraft({}); setError(null); }}>Discard changes</Button>}
    </div>
  </form>;
}
