import { useCallback, useEffect, useRef, useState } from "react";
import { ConfigError, configRequest, uploadBundle, type ConfigEvent, type ConfigOperation, type ConfigPlan, type ConfigStatus } from "../api/configuration";
import type { OperatorConnection } from "../api/operator";
import { Button } from "./ui/Button";
import { Surface } from "./ui/Surface";

const DONE = new Set(["complete", "plan_ready", "rejected", "rejected_busy", "failed", "needs_inspection"]);
const keyFor = (connection: OperatorConnection) => `canary-config-operation:${connection.baseUrl}`;
const date = (seconds?: number) => seconds ? new Date(seconds * 1000).toLocaleString() : "not observed";
const recovery = (id: string) => `python3 scripts/canary_config.py status --target production --operation ${id}`;
const isDefiniteRejection = (failure: unknown) => failure instanceof ConfigError
  && !["request_outcome_unknown", "configuration_failed", "worker_launch_unknown"].includes(failure.code)
  && !failure.code.startsWith("http_5");

export function EnvironmentPanel({ connection }: { connection: OperatorConnection }) {
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [operation, setOperation] = useState<ConfigOperation | null>(null);
  const [plan, setPlan] = useState<ConfigPlan | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [log, setLog] = useState<ConfigEvent[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [files, setFiles] = useState<Record<string, File | undefined>>({});
  const [lastContact, setLastContact] = useState<number>();
  const [hostOffset, setHostOffset] = useState(0);
  const [selectedId, setSelectedId] = useState(() => sessionStorage.getItem(keyFor(connection)) ?? "");
  const selected = useRef(selectedId);
  const sequence = useRef(0);
  const edited = useRef(false);
  const version = useRef(0);
  const [previewRevision, setPreviewRevision] = useState(-1);
  const [draftRevision, setDraftRevision] = useState(0);
  const [awaiting, setAwaiting] = useState(false);
  const pendingPreview = useRef("");
  const failures = useRef(0);
  const activePoll = useRef(false);

  const select = useCallback((id: string) => {
    selected.current = id;
    setSelectedId(id);
    sessionStorage.setItem(keyFor(connection), id);
    sequence.current = 0;
    activePoll.current = Boolean(id);
    setLog([]);
  }, [connection]);

  const refresh = useCallback(async () => {
    const id = selected.current;
    try {
      const current = await configRequest<ConfigStatus>(connection, `status${id ? `?operation=${id}` : ""}`);
      if (id !== selected.current) return; // A poll predating submission cannot unlock it.
      setStatus(current);
      setHostOffset(current.checked_at - Date.now() / 1000);
      if (!edited.current) setValues(current.values);
      if (current.operation) {
        setOperation(current.operation);
        activePoll.current = !DONE.has(current.operation.phase);
        if (!id) select(current.operation.request_id);
        if (current.operation.request_id === pendingPreview.current && current.operation.phase === "plan_ready") setPlan(current.operation.plan);
        if (DONE.has(current.operation.phase)) setAwaiting(false);
      }
      const currentId = id || current.operation?.request_id;
      if (currentId) {
        const batch = await configRequest<{ events: ConfigEvent[]; after: number }>(connection, `events?operation=${currentId}&after=${sequence.current}`);
        if (currentId !== selected.current) return;
        const incoming = batch.events.filter(event => event.seq > sequence.current);
        setLog(previous => [...previous, ...incoming]);
        sequence.current = batch.after;
        if (current.operation?.seq && batch.after < current.operation.seq) activePoll.current = true;
      }
      setLastContact(current.checked_at);
      setError("");
      failures.current = 0;
    } catch (failure) {
      if (id !== selected.current) return;
      failures.current += 1;
      setError(failure instanceof Error ? failure.message : "Contact lost");
    }
  }, [connection, select]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (disposed) return;
      await refresh();
      if (disposed) return;
      let delay = activePoll.current ? 2500 : 15000;
      if (failures.current) delay = Math.min(15000, 2500 * 2 ** Math.min(failures.current, 3));
      timer = setTimeout(poll, delay);
    };
    timer = setTimeout(poll, 0);
    return () => { disposed = true; clearTimeout(timer); };
  }, [refresh]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(timer); }, []);

  function change() {
    edited.current = true;
    version.current += 1;
    setDraftRevision(version.current);
    setPlan(null);
    setConfirm(false);
  }
  async function preview() {
    setPending(true);
    setError("");
    const id = crypto.randomUUID();
    select(id);
    pendingPreview.current = id;
    setPreviewRevision(version.current);
    setAwaiting(true);
    let submitted = false;
    try {
      let bundleId: string | undefined;
      if (files.bundle || files.manifest || files.signature) {
        if (!files.bundle || !files.manifest || !files.signature) throw new Error("Attach ciphertext, manifest and signature together.");
        bundleId = await uploadBundle(connection, files.bundle, files.manifest, files.signature);
      }
      const patch = Object.fromEntries(Object.entries(values).filter(([key, value]) => status?.schema[key].backoffice === "editable" && status.values[key] !== value));
      const request: { request_id: string; patch: Record<string, string>; bundle_id?: string } = { request_id: id, patch };
      if (bundleId) request.bundle_id = bundleId;
      submitted = true;
      setOperation(await configRequest<ConfigOperation>(connection, "plan", request));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Preview not confirmed");
      if (!submitted || isDefiniteRejection(failure)) { setAwaiting(false); pendingPreview.current = ""; select(""); }
    } finally { setPending(false); }
  }
  async function apply() {
    if (!plan) return;
    const id = crypto.randomUUID();
    select(id); // Keep the UUID even if POST loses its reply.
    setAwaiting(true);
    setPending(true);
    setConfirm(false);
    try { setOperation(await configRequest<ConfigOperation>(connection, "apply", { request_id: id, plan_id: plan.plan_id, plan_digest: plan.digest })); }
    catch (failure) {
      const code = failure instanceof Error ? failure.message : "request_outcome_unknown";
      setError(code);
      if (isDefiniteRejection(failure)) { setAwaiting(false); select(plan.plan_id); }
    } finally { setPending(false); }
  }

  const busy = pending || awaiting || Boolean(operation && !DONE.has(operation.phase));
  const hostNow = now + hostOffset;
  const stale = !status || status.observation.stale || hostNow - (status.observation.observed_at ?? 0) > 30;
  const blocked = busy || Boolean(error) || stale || status?.observation.match !== "match" || status?.maintenance_hold;
  const expired = plan && hostNow >= plan.effective_expires_at;
  const expiryReason = plan && plan.authorization_expires_at !== null && plan.authorization_expires_at < plan.plan_expires_at ? "authorization_expired" : "plan_expired";
  const canApply = Boolean(plan && !blocked && !expired && previewRevision === draftRevision && plan.baseline === status?.revision);

  return <div className="space-y-5">
    <header><h1 className="font-display text-3xl font-black">Environment</h1><p>Preview and approve configuration changes. Generation drains before Canary restarts.</p></header>
    <p role="status">Last heard from host: {date(lastContact)}{operation ? ` · ${operation.phase}` : ""}</p>
    {error && <div role="alert"><p>{error}</p>{error === 'host_agent_unavailable' ? <p>The proxy could not connect to the host agent; this attempt sent no request. Refresh to check access before submitting again.</p> : <p>Contact may be lost while Canary restarts. Current host state is unknown until refreshed. An uncertain apply is observed by its original ID; it is never automatically submitted again.</p>}{selectedId && <code>{recovery(selectedId)}</code>}</div>}
    <Button variant="secondary" onClick={() => void refresh()}>Refresh environment</Button>
    {status && <>
      <Surface className="p-5"><h2>Current deployment</h2>
        <dl>{Object.entries({ Revision: status.revision, Image: status.image, Source: status.observation.source_sha ?? "unknown", Bundle: status.bundle_sha256, Loader: status.loader_sha256, "Running state": `${status.observation.match}${stale ? " (stale)" : ""}`, "Observed at": date(status.observation.observed_at) }).map(([key, value]) => <div key={key}><dt>{key}</dt><dd className="break-all">{value}</dd></div>)}</dl>
        <p>Secret names: {status.secret_names.join(", ") || "None observed"}</p>
      </Surface>
      <Surface className="space-y-3 p-5"><h2>Public settings</h2>
        {Object.entries(status.schema).map(([key, rule]) => <label className="block" key={key}><span>{key}{rule.backoffice === "ssh_only" ? " (SSH only)" : ""}</span><p>{rule.description}</p>{rule.type === "boolean" ? <select aria-label={key} disabled={Boolean(blocked || rule.backoffice !== "editable")} value={values[key] ?? "false"} onChange={event => { change(); setValues(previous => ({ ...previous, [key]: event.target.value })); }}><option value="false">false</option><option value="true">true</option></select> : <input aria-label={key} readOnly value={values[key] ?? ""} />}</label>)}
      </Surface>
      <Surface className="space-y-3 p-5"><h2>Signed secret bundle (optional)</h2><p>Prepare and sign on your operator machine. Upload encrypted ciphertext only. Operations-token rotation requires SSH.</p>
        {(["bundle", "manifest", "signature"] as const).map(name => <label className="block" key={name}>{name}<input aria-label={name} type="file" disabled={Boolean(blocked)} onChange={event => { change(); setFiles(previous => ({ ...previous, [name]: event.target.files?.[0] })); }} /></label>)}
      </Surface>
      <Button disabled={Boolean(blocked)} onClick={() => void preview()}>Preview changes</Button>
    </>}
    {plan && <Surface className="space-y-3 p-5"><h2>Review plan</h2><p className="break-all">Digest: {plan.digest}</p>
      {Object.entries(plan.changes).map(([key, value]) => <p key={key}>{key}: {value.before} → {value.after}</p>)}
      {Object.entries(plan.secret_changes).map(([key, value]) => <p key={key}>{key}: {value}</p>)}
      <p>{plan.restart_required ? "Restart required" : "No-op: no restart"}</p>
      <p>{expired ? expiryReason : `Expires in ${Math.max(0, Math.ceil(plan.effective_expires_at - hostNow))} seconds (${expiryReason.replace("_expired", "")} deadline)`}</p>
      {plan.baseline !== status?.revision && <p>baseline_changed — create a fresh preview.</p>}
      <pre>{JSON.stringify({ prerequisites: plan.checks, activity: plan.activity }, null, 2)}</pre>
      {plan.recovery_verification && <p>{plan.recovery_verification}</p>}
      <p>If Canary does not return, use operator SSH and the status command shown here. Keep your operator access available.</p>
      <Button disabled={!canApply} onClick={() => setConfirm(true)}>Review apply</Button>
      {confirm && <div><p>{plan.restart_required ? "Generation stops accepting new work and Canary restarts. Drain deadline: 30 minutes." : "Record this no-op; no restart is required."} Approve only this digest and the changed names shown above.</p><Button disabled={!canApply} onClick={() => void apply()}>Apply this plan</Button><Button variant="secondary" onClick={() => setConfirm(false)}>Cancel</Button></div>}
    </Surface>}
    {selectedId && <p>Operation: {selectedId}<br /><code>{recovery(selectedId)}</code></p>}
    {log.length > 0 && <Surface className="p-5"><h2>Operation timeline</h2><ol>{log.map((event, index) => {
      const unconfirmed = event.kind === "intent" && !log.slice(index + 1).some(next => next.phase === event.phase && next.kind === "result");
      return <li key={event.seq}>{date(event.at)} · {event.phase} · {unconfirmed ? "unconfirmed" : event.kind}{event.error ? ` · ${event.error}` : ""}{event.deadline && <p>Deadline: {date(event.deadline)}</p>}{(event.activity || event.checks) && <pre>{JSON.stringify(event.activity ?? event.checks, null, 2)}</pre>}</li>;
    })}</ol></Surface>}
    {operation?.receipt && <Surface className="p-5"><h2>Receipt</h2><pre className="overflow-auto">{JSON.stringify(operation.receipt, null, 2)}</pre></Surface>}
    {operation?.error && <p role="alert">{operation.phase}: {operation.error}. {operation.phase.startsWith('rejected') ? 'No change was applied. Refresh state and preview once the conflict is resolved.' : 'Inspect the host with the status command before recovery. Do not clear maintenance or repeat an uncertain apply.'}</p>}
  </div>;
}
