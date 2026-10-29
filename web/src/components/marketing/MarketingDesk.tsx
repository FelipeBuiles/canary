import { useCallback, useEffect, useRef, useState } from "react";
import { fetchMarketingSnapshot, transitionMarketingDraft } from "../../api/marketing";
import type { OperatorConnection } from "../../api/operator";
import type { MarketingDraft, MarketingSnapshot, MarketingStatus, MarketingTransition } from "../../types/marketing";
import { Button } from "../ui/Button";
import { Surface } from "../ui/Surface";
import { ErrorNotice } from "../composites/ErrorNotice";
import { cn } from "../../lib/cn";

type View = MarketingStatus | "reports";
type DeskState =
  | { status: "loading"; snapshot?: MarketingSnapshot }
  | { status: "ready"; snapshot: MarketingSnapshot }
  | { status: "failed"; snapshot?: MarketingSnapshot; error: unknown };
const CHARACTER_LIMITS: Partial<Record<MarketingDraft["meta"]["channel"], number>> = { x: 280, bluesky: 300 };
const VIEWS: { key: View; label: string }[] = [
  { key: "draft", label: "Drafts" }, { key: "approved", label: "Approved" },
  { key: "published", label: "Published" }, { key: "rejected", label: "Rejected" },
  { key: "reports", label: "Plans & reports" },
];

export function MarketingDesk({ connection }: { connection: OperatorConnection }) {
  const [state, setState] = useState<DeskState>({ status: "loading" });
  const [view, setView] = useState<View>("draft");
  const [selected, setSelected] = useState<string>();
  const requestId = useRef(0);
  const mutation = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (mutation.current) return;
    const id = ++requestId.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setState(current => ({ status: "loading", snapshot: current.snapshot }));
    try {
      const snapshot = await fetchMarketingSnapshot(connection, controller.current.signal);
      if (id === requestId.current) setState({ status: "ready", snapshot });
    } catch (error) {
      if (id === requestId.current) setState(current => ({ status: "failed", snapshot: current.snapshot, error }));
    }
  }, [connection]);
  useEffect(() => {
    const requests = requestId;
    const timer = window.setTimeout(() => void refresh(), 0);
    const focus = () => void refresh();
    window.addEventListener("focus", focus);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("focus", focus);
      ++requests.current;
      controller.current?.abort();
    };
  }, [refresh]);

  async function act(draft: MarketingDraft, transition: MarketingTransition) {
    if (state.status !== "ready" || mutation.current) return;
    mutation.current = true;
    const id = ++requestId.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setState({ status: "loading", snapshot: state.snapshot });
    try {
      const snapshot = await transitionMarketingDraft(connection, { path: draft.path, revision: draft.revision, transition }, controller.current.signal);
      if (id !== requestId.current) return;
      setState({ status: "ready", snapshot });
      setView(transition.to);
      setSelected(draft.path);
    } catch (error) {
      if (id === requestId.current) setState(current => ({ status: "failed", snapshot: current.snapshot, error }));
    } finally { mutation.current = false; }
  }

  const snap = state.snapshot;
  const drafts = snap?.drafts.filter(d => d.meta.status === view) ?? [];
  const draft = drafts.find(d => d.path === selected) ?? drafts[0];
  const report = snap?.reports.find(r => r.path === selected) ?? snap?.reports[0];
  return <section className="min-w-0 space-y-5" aria-label="Marketing desk">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="font-display text-3xl font-black">Marketing</h1><p className="mt-2 max-w-prose font-body text-sm text-ink-muted">Review local drafts and research. Approval never posts anything. Copy approved text, post it yourself, then record where it went.</p></div>
      <Button variant="outline" disabled={state.status === "loading"} onClick={() => void refresh()}>Refresh desk</Button>
    </div>
    {state.status === "loading" && <p role="status" className="font-body text-sm">Loading the local workspace…</p>}
    {state.status === "failed" && <ErrorNotice error={state.error} operation="load" title="The marketing desk needs attention" recovery="Displayed data may be stale. Refresh before reviewing or retrying a change. Marketing is available only on a local development backend." onRetry={() => void refresh()} retryLabel="Refresh desk" />}
    {snap && <>
      <p className="font-meta text-xs text-ink-muted">Local files · Canary {snap.canarySha?.slice(0, 8) ?? "not synced"} · {snap.facts.length} facts</p>
      <nav aria-label="Marketing views" className="flex flex-wrap gap-2">
        {VIEWS.map(item => <Button key={item.key} size="sm" variant={view === item.key ? "secondary" : "outline"} aria-pressed={view === item.key} onClick={() => { setView(item.key); setSelected(undefined); }}>
          {item.label} <span>{item.key === "reports" ? snap.reports.length : snap.drafts.filter(d => d.meta.status === item.key).length}</span>
        </Button>)}
      </nav>
      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(220px,0.7fr)_minmax(0,2fr)]">
        <div className="min-w-0 space-y-5">
          <Surface border="soft" shadow="none" className="p-3">
            <h2 className="sr-only">{view === "reports" ? "Reports" : "Drafts"}</h2>
            <ul className="space-y-2">
              {view === "reports" && snap.reports.map(item => <li key={item.path}><button className={cn("w-full break-words p-3 text-left font-body text-sm hover:bg-surface-container", item.path === report?.path && "bg-surface-container font-bold")} aria-current={item.path === report?.path ? "true" : undefined} onClick={() => setSelected(item.path)}>{item.title}</button></li>)}
              {view !== "reports" && drafts.map(item => <li key={item.path}><button className={cn("w-full break-words p-3 text-left font-body text-sm hover:bg-surface-container", item.path === draft?.path && "bg-surface-container font-bold")} aria-current={item.path === draft?.path ? "true" : undefined} onClick={() => setSelected(item.path)}><span className="mb-1 block text-xs text-ink-muted">{item.meta.channel}{item.issues.length || !item.approvalCurrent ? " · Needs review" : ""}</span>{item.meta.title}</button></li>)}
            </ul>
            {(view === "reports" ? snap.reports.length === 0 : drafts.length === 0) && <p className="p-3 font-body text-sm text-ink-muted">{view === "reports" ? "No reports yet. Ask Pi to run the marketing-plan skill." : `No ${view} drafts. Skills save new copy under marketing/drafts/.`}</p>}
          </Surface>
          {snap.issues.length > 0 && <Surface border="soft" shadow="none" className="space-y-3 p-4"><h2 className="font-body font-bold">Workspace issues</h2>{snap.issues.map(issue => <p key={issue.path + issue.message} className="break-words font-body text-sm"><span className="font-bold">{issue.level === "error" ? "Blocked" : "Warning"}</span> · {issue.path}<br />{issue.message}</p>)}</Surface>}
        </div>
        {view === "reports" && report && <Surface border="soft" shadow="none" className="min-w-0 p-5 md:p-7"><h2 className="font-display text-2xl font-bold">{report.title}</h2><p className="mt-2 break-all font-meta text-xs text-ink-muted">{report.path} · Read-only</p><article className="mt-6 max-w-[75ch] whitespace-pre-wrap break-words font-body text-sm leading-7">{report.body.trim()}</article></Surface>}
        {view !== "reports" && draft && <DraftPanel key={draft.path + draft.revision} draft={draft} snap={snap} disabled={state.status !== "ready"} act={act} />}
      </div>
    </>}
  </section>;
}

function DraftPanel({ draft, snap, disabled, act }: { draft: MarketingDraft; snap: MarketingSnapshot; disabled: boolean; act: (draft: MarketingDraft, transition: MarketingTransition) => Promise<void> }) {
  const [confirmation, setConfirmation] = useState<"reject" | "publish" | null>(null);
  const [reason, setReason] = useState("");
  const [url, setUrl] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const { meta } = draft;
  const limit = CHARACTER_LIMITS[meta.channel];
  const length = [...draft.body.trim()].length;
  const blocked = snap.issues.some(i => i.level === "error") || draft.issues.some(i => i.level === "error" && !i.message.startsWith("edited after approval"));
  async function copy() {
    try { await navigator.clipboard.writeText(draft.body.trim()); setCopyStatus("Text copied."); }
    catch { setCopyStatus("Could not copy. Select and copy the text above."); }
  }
  return <Surface border="soft" shadow="none" className="min-w-0 p-5 md:p-7">
    <p className="break-all font-meta text-xs text-ink-muted">{meta.kind} · {meta.channel} · {draft.path}</p>
    <h2 className="mt-3 font-display text-2xl font-bold">{meta.title}</h2>
    {meta.target && <a className="mt-3 block break-all font-body text-sm underline underline-offset-4" href={meta.target} target="_blank" rel="noreferrer">{meta.target}</a>}
    {draft.issues.map(issue => <p className="mt-4 break-words font-body text-sm text-hero-red" key={issue.message}>{issue.message}</p>)}
    {!draft.approvalCurrent && <p className="mt-4 font-body text-sm font-bold">{meta.status === "published" ? "This published record differs from current copy or evidence. It remains history; write a new draft for updated claims." : "Copy or supporting evidence changed. Review the current facts and approve again before posting."}</p>}
    <article className="mt-6 max-w-[75ch] whitespace-pre-wrap break-words font-body text-sm leading-7">{draft.body.trim()}</article>
    <p className={cn("mt-4 font-meta text-xs text-ink-muted", limit !== undefined && length > limit && "text-hero-red")}>{length}{limit ? ` / ${limit}` : ""} characters</p>
    <fieldset disabled={disabled} className="mt-5 flex flex-wrap gap-3" aria-label="Draft actions">
      <Button variant="outline" onClick={() => void copy()}>Copy text</Button>
      {meta.status !== "published" && (meta.status !== "approved" || !draft.approvalCurrent) && <Button disabled={blocked} onClick={() => void act(draft, { to: "approved" })}>Approve</Button>}
      {meta.status === "approved" && draft.approvalCurrent && <Button disabled={blocked} onClick={() => setConfirmation("publish")}>I posted it</Button>}
      {meta.status !== "published" && meta.status !== "rejected" && <Button variant="outline" onClick={() => setConfirmation("reject")}>Reject</Button>}
      {meta.status !== "draft" && meta.status !== "published" && <Button variant="outline" onClick={() => void act(draft, { to: "draft" })}>Back to draft</Button>}
    </fieldset>
    <p role="status" className="mt-2 font-body text-sm">{copyStatus}</p>
    {confirmation && <form className="mt-5 space-y-3 bg-surface-container p-4" onSubmit={event => {
      event.preventDefault();
      if (confirmation === "reject") {
        void act(draft, { to: "rejected", reason: reason.trim() });
        return;
      }
      const transition: MarketingTransition = { to: "published" };
      const publicationUrl = url.trim();
      if (publicationUrl) transition.url = publicationUrl;
      void act(draft, transition);
    }}>
      <label className="block font-body text-sm font-bold" htmlFor="marketing-confirmation">{confirmation === "reject" ? "Why reject this draft?" : "Where did you post it? Optional URL"}</label>
      <input id="marketing-confirmation" className="min-h-11 w-full border-2 border-ink-black/25 bg-bristol px-3 font-body text-sm" type={confirmation === "publish" ? "url" : "text"} required={confirmation === "reject"} maxLength={confirmation === "reject" ? 8192 : 2048} value={confirmation === "reject" ? reason : url} onChange={event => confirmation === "reject" ? setReason(event.target.value) : setUrl(event.target.value)} />
      <div className="flex flex-wrap gap-3"><Button type="submit" disabled={disabled || (confirmation === "reject" && !reason.trim())}>{confirmation === "reject" ? "Confirm rejection" : "Record publication"}</Button><Button variant="outline" disabled={disabled} onClick={() => setConfirmation(null)}>Cancel</Button></div>
    </form>}
    <section className="mt-8 space-y-3"><h3 className="font-body font-bold">Facts cited</h3>
      {meta.facts.length === 0 && <p className="font-body text-sm text-ink-muted">None. Product claims need a fact from marketing/knowledge/facts.yaml.</p>}
      {meta.facts.map(id => { const fact = snap.facts.find(f => f.id === id); return <div key={id} className="font-body text-sm leading-6"><p><code>{id}</code> · {fact?.statement ?? "Unknown fact"}</p>{fact && <><blockquote className="mt-1 text-ink-muted">{fact.quote}</blockquote><p className="break-words text-xs text-ink-muted">{fact.sources.join(", ")}</p></>}</div>; })}
    </section>
    {meta.sources.length > 0 && <section className="mt-7"><h3 className="font-body font-bold">Sources</h3>{meta.sources.map(source => <a key={source} className="mt-2 block break-all font-body text-sm underline underline-offset-4" href={source} target="_blank" rel="noreferrer">{source}</a>)}</section>}
    {meta.status === "rejected" && <p className="mt-6 font-body text-sm">Rejected · {meta.reason}</p>}
    {meta.status === "published" && <p className="mt-6 font-body text-sm">Published {meta.published.at}{meta.published.url && <> · <a href={meta.published.url} className="underline">{meta.published.url}</a></>}</p>}
  </Surface>;
}
