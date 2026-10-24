import { useCallback, useEffect, useRef, useState } from "react";
import { operatorFetch, type HostStatus, type OperatorConnection } from "../api/operator";
import { Button } from "./ui/Button";
import { Surface } from "./ui/Surface";

const ACTIVE = new Set(["queued", "checking", "draining", "updating", "rebooting", "verifying"]);
type Action = "check" | "update" | "reboot";

export function HostMaintenancePanel({ connection }: { connection: OperatorConnection }) {
  const [status, setStatus] = useState<HostStatus | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [reviewedDigest, setReviewedDigest] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  // A poll that began before the POST returns stale status; only the submitted operation releases the controls.
  const submittedId = useRef<string | null>(null);
  const refresh = useCallback(async () => {
    try {
      const result = await operatorFetch<HostStatus>("/api/ops/backoffice/host", connection);
      setStatus(result);
      setError("");
      if (submittedId.current === null || result.operation?.request_id === submittedId.current) {
        submittedId.current = null;
        setAccepted(false);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not reach host maintenance.");
    }
  }, [connection]);
  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);
  const busy = pending || accepted || Boolean(status?.operation && ACTIVE.has(status.operation.phase));
  const plan = status?.plan;
  const freshPlan = plan && status.checked_at - plan.checked_at < 1800;

  async function submit(action: Action) {
    setPending(true);
    setConfirm(null);
    const requestId = crypto.randomUUID();
    try {
      const operation = await operatorFetch<NonNullable<HostStatus["operation"]>>("/api/ops/backoffice/host", connection, {
        method: "POST",
        body: JSON.stringify({ action, request_id: requestId, ...(action === "update" ? { plan_digest: reviewedDigest } : {}) }),
      });
      setStatus((previous) => previous ? { ...previous, operation } : previous);
      submittedId.current = requestId;
      setAccepted(true);
      setError("");
    } catch (failure) {
      setError(`${failure instanceof Error ? failure.message : "Host request failed."} The outcome may be unknown. Refresh status before trying again.`);
      submittedId.current = null;
      setAccepted(true);
    } finally {
      setPending(false);
    }
  }

  return <div className="space-y-6">
    <div><h1 className="font-display text-3xl font-black">Host maintenance</h1><p className="mt-2 max-w-prose font-body text-sm text-ink-muted">Monitor the Lightsail host and update its Ubuntu packages. Application image dependencies are updated through a rebuild and deployment.</p></div>
    {error && <div role="alert" className="border-2 border-hero-red bg-chip-red p-4 font-body text-sm"><p>{error}</p><p className="mt-2">During updates or reboot, this page may lose contact. Keep it open; status refreshes every 15 seconds. A failed recovery requires host access.</p></div>}
    <div className="flex flex-wrap gap-3"><Button variant="secondary" onClick={() => void refresh()}>Refresh status</Button><Button disabled={!status || Boolean(error) || busy || status.maintenance_hold} onClick={() => void submit("check")}>Check for updates</Button></div>
    {!status && !error && <p role="status">Loading host status…</p>}
    {status && <>
      <Surface className="p-5">
        <h2 className="font-display text-xl font-bold">Lightsail host</h2>
        <p className="mt-2 font-body text-sm">Checked {new Date(status.checked_at * 1000).toLocaleString()} · uptime {Math.floor(status.uptime_seconds / 3600)} hours</p>
        <dl className="mt-4 grid gap-4 font-body text-sm sm:grid-cols-2">
          <div><dt className="font-bold">Disk space</dt><dd>{(status.disk_free_bytes / 1024 ** 3).toFixed(1)} GiB free of {(status.disk_total_bytes / 1024 ** 3).toFixed(1)} GiB</dd></div>
          <div><dt className="font-bold">Load average · 1 / 5 / 15 min</dt><dd>{status.load.map((value) => value.toFixed(2)).join(" / ")}</dd></div>
          <div><dt className="font-bold">Restart</dt><dd>{status.reboot_required ? "Host reboot required" : "No package reboot flag"}</dd>{status.reboot_packages.length > 0 && <dd className="break-words">{status.reboot_packages.join(", ")}</dd>}</div>
          <div><dt className="font-bold">Maintenance hold</dt><dd>{status.maintenance_hold ? "Active — deployment is blocked" : "None"}</dd></div>
        </dl>
        <p className="mt-4 font-body text-sm"><strong>Application readiness:</strong> {status.readiness?.status ?? "unavailable"}{status.readiness?.checks && ` · ${Object.entries(status.readiness.checks).map(([name, value]) => `${name}: ${value}`).join(" · ")}`}</p>
        <h3 className="mt-6 font-body font-bold">Services</h3><dl className="mt-2 divide-y divide-ink-black/15 font-body text-sm">{Object.entries(status.services).map(([name, state]) => <div key={name} className="flex flex-wrap justify-between gap-2 py-2"><dt>{name}</dt><dd className="font-bold">{state}</dd></div>)}</dl>
        <h3 className="mt-6 font-body font-bold">Application container</h3>{status.containers === null ? <p className="mt-2 text-sm">Docker status unavailable.</p> : status.containers.length === 0 ? <p className="mt-2 text-sm">No Canary containers found.</p> : status.containers.map((container) => <div key={container.Names} className="mt-2 font-body text-sm"><p>{container.Names} · {container.State} · {container.Status}</p><p className="mt-1 break-all text-ink-muted">{container.Image}</p></div>)}
      </Surface>
      <Surface className="p-5"><h2 className="font-display text-xl font-bold">Package updates</h2>
        <p className="mt-2 font-body text-sm">{plan ? `Preview checked ${new Date(plan.checked_at * 1000).toLocaleString()}. Review within 30 minutes before applying.` : "Check for updates to refresh package lists and prepare a preview."}</p>
        <p className="mt-2 max-w-prose font-body text-sm text-ink-muted">This covers packages from the host’s configured APT repositories. It does not scan CVEs or update packages inside the application image. Package updates may leave other host services needing a restart even when no reboot flag is set.</p>
        {plan && <pre aria-label="Package update preview" className="mt-4 max-h-80 overflow-auto bg-surface-container p-3 text-xs">{plan.packages.length ? plan.packages.join("\n") : "No package upgrades in the current preview."}</pre>}
        <div className="mt-4 flex flex-wrap gap-3"><Button disabled={Boolean(error) || busy || status.maintenance_hold || !freshPlan || !plan?.packages.length} onClick={() => { setReviewedDigest(plan?.digest ?? null); setConfirm("update"); }}>Review package update</Button><Button variant="secondary" disabled={Boolean(error) || busy || status.maintenance_hold} onClick={() => setConfirm("reboot")}>Review host reboot</Button></div>
      </Surface>
      {confirm && <Surface className="p-5"><h2 className="font-display text-xl font-bold">{confirm === "update" ? "Apply these host updates?" : "Reboot the Lightsail host?"}</h2><p className="mt-2 max-w-prose font-body text-sm">New generation will pause while active work finishes. Canary will then stop. {confirm === "update" ? "Packages will be upgraded and Docker and Nginx restarted. A required host reboot is a separate action." : "The host will reboot and run its recovery check on startup."} Generation reopens only after the application passes verification. If verification fails, the host stays in maintenance for operator recovery.</p><div className="mt-4 flex flex-wrap gap-3"><Button disabled={Boolean(error) || busy || status.maintenance_hold || (confirm === "update" && (!freshPlan || reviewedDigest !== plan?.digest))} onClick={() => void submit(confirm)}>{confirm === "update" ? "Apply updates" : "Reboot host"}</Button><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button></div></Surface>}
      {status.operation && <Surface className="p-5"><h2 className="font-display text-xl font-bold">Latest operation</h2><p role="status" className="mt-2 font-body text-sm">{status.operation.action} · {status.operation.phase} · {new Date(status.operation.updated_at * 1000).toLocaleString()}</p>{status.operation.error && <p className="mt-2 font-body text-sm text-hero-red">{status.operation.error}. Inspect journalctl -u canary-host-maintenance and the maintenance hold before recovery.</p>}</Surface>}
    </>}
  </div>;
}
