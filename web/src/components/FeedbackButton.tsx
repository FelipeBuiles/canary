import { useCallback, useRef, useState, type FormEvent } from "react";
import { apiFetch } from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { Button } from "./ui/Button";

export function FeedbackButton({ projectId }: { projectId?: string }) {
  const { user } = useAuth();
  return user ? <AccountFeedback key={user.id} projectId={projectId} /> : null;
}

function AccountFeedback({ projectId }: { projectId?: string }) {
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState("frustration");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const receipt = useRef<string | null>(null);
  const modal = useRef<HTMLDivElement>(null);
  const close = useCallback(() => { if (!busy) setOpen(false); }, [busy]);
  useDialogFocus(modal, { enabled: open, onClose: close });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!message.trim() || busy) return;
    setBusy(true); setError("");
    receipt.current ??= crypto.randomUUID();
    try {
      await apiFetch("/feedback", { method: "POST", body: JSON.stringify({ id: receipt.current, category, message, project_id: projectId ?? null }) });
      setSent(true); setMessage(""); receipt.current = null;
    } catch {
      setError("We couldn't save your feedback. Your message is still here; please try again.");
    } finally { setBusy(false); }
  }

  return <>
    <button type="button" onClick={() => { setOpen(true); setSent(false); }} className="font-meta text-[0.6rem] tracking-wider text-narrator-gold hover:text-bristol">GIVE FEEDBACK</button>
    {open && <div className="fixed inset-0 z-[120] flex items-center justify-center bg-ink-black/70 p-4">
      <div ref={modal} role="dialog" aria-modal="true" aria-labelledby="feedback-title" className="w-full max-w-lg border-2 border-ink-black bg-pulp-paper p-6 text-ink-black shadow-ink">
        <h2 id="feedback-title" className="font-display text-2xl font-bold">Help shape Scenewright</h2>
        {sent ? <p role="status" className="my-4">Thank you. Your feedback is saved for review.</p> : <form onSubmit={submit} className="mt-4 grid gap-4">
          <label className="grid gap-1 text-sm">What would you like to share?
            <select value={category} onChange={event => { setCategory(event.target.value); receipt.current = null; }} disabled={busy} className="border border-ink-black bg-bristol p-2">
              <option value="frustration">Something was frustrating</option><option value="feature">A feature I'd like</option><option value="praise">Something I liked</option><option value="other">Something else</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">Your feedback
            <textarea value={message} onChange={event => { setMessage(event.target.value); receipt.current = null; }} disabled={busy} required maxLength={3000} rows={5} className="border border-ink-black bg-bristol p-2" aria-describedby="feedback-privacy" />
          </label>
          <p id="feedback-privacy" className="text-sm text-ink-muted">Only the Scenewright team can read this. Please leave out manuscript text, passwords, and payment details.</p>
          {error && <p role="alert" className="text-sm text-hero-red">{error}</p>}
          <Button type="submit" disabled={busy || !message.trim()}>{busy ? "Sending…" : "Send feedback"}</Button>
        </form>}
        <Button variant="outline" onClick={close} disabled={busy} className="mt-3">Close</Button>
      </div>
    </div>}
  </>;
}
