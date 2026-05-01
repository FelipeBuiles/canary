import { useState } from "react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../hooks/useAuth";
import { SettingsLayout } from "../components/ui/SettingsLayout";
import { Card } from "../components/ui/Card";
import { TextField } from "../components/ui/Field";
import { Button } from "../components/ui/Button";

const TABS = [
  { id: "email", label: "Email" },
  { id: "password", label: "Password" },
];

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-3 border-b border-ink-black/10 py-4 last:border-b-0 md:grid-cols-[220px_1fr] md:items-start md:gap-6">
      <div>
        <div className="font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/55">{label}</div>
        {hint && (
          <p className="mt-1.5 text-[0.72rem] leading-5 text-ink-black/55">{hint}</p>
        )}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function AccountPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState("email");

  return (
    <SettingsLayout
      kicker="ACCOUNT // PREFERENCES"
      title="Account"
      subtitle="Manage your email address and password."
      tabs={TABS}
      activeTab={activeTab}
      onTabChange={setActiveTab}
    >
      {activeTab === "email" && <EmailTab email={user?.email ?? ""} />}
      {activeTab === "password" && <PasswordTab />}
    </SettingsLayout>
  );
}

function EmailTab({ email }: { email: string }) {
  const [newEmail, setNewEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!newEmail.trim() || newEmail === email) return;
    setBusy(true);
    setMessage(null);
    const { error } = await supabase.auth.updateUser({ email: newEmail.trim() });
    setBusy(false);
    if (error) {
      setMessage({ type: "err", text: error.message });
    } else {
      setMessage({ type: "ok", text: "Check your inbox to confirm the new email." });
      setNewEmail("");
    }
  }

  return (
    <Card className="px-5">
      <Row label="CURRENT EMAIL">
        <span className="font-body text-[0.88rem] font-semibold">{email}</span>
      </Row>
      <Row label="CHANGE EMAIL" hint="You'll need to confirm the new address via email.">
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 max-w-sm">
          <TextField
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="new@example.com"
            disabled={busy}
            className="bg-bristol"
          />
          <Button type="submit" size="sm" disabled={busy || !newEmail.trim() || newEmail === email}>
            {busy ? "Updating…" : "Update Email"}
          </Button>
          {message && (
            <p className={message.type === "ok" ? "text-archive-sage" : "text-hero-red"}>
              {message.text}
            </p>
          )}
        </form>
      </Row>
    </Card>
  );
}

function PasswordTab() {
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 6) {
      setMessage({ type: "err", text: "Password must be at least 6 characters." });
      return;
    }
    if (password !== confirm) {
      setMessage({ type: "err", text: "Passwords don't match." });
      return;
    }
    setBusy(true);
    setMessage(null);
    supabase.auth.updateUser({ password }).then(({ error }) => {
      setBusy(false);
      if (error) {
        setMessage({ type: "err", text: error.message });
      } else {
        setMessage({ type: "ok", text: "Password updated successfully." });
        setCurrent("");
        setPassword("");
        setConfirm("");
      }
    });
  }

  const canSubmit = password && confirm && password === confirm && password.length >= 6;

  return (
    <Card className="px-5">
      <Row label="CURRENT PASSWORD" hint="Enter your current password to authorize the change.">
        <TextField
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          placeholder="Current password"
          className="max-w-sm bg-bristol"
        />
      </Row>
      <Row label="NEW PASSWORD" hint="Minimum 6 characters.">
        <TextField
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="New password"
          className="max-w-sm bg-bristol"
        />
      </Row>
      <Row label="CONFIRM PASSWORD">
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 max-w-sm">
          <TextField
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Confirm new password"
            disabled={busy}
            className="bg-bristol"
          />
          <Button type="submit" size="sm" disabled={busy || !canSubmit}>
            {busy ? "Updating…" : "Update Password"}
          </Button>
          {message && (
            <p className={message.type === "ok" ? "text-archive-sage" : "text-hero-red"}>
              {message.text}
            </p>
          )}
        </form>
      </Row>
    </Card>
  );
}
