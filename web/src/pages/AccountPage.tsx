import { useState } from "react";
import { Mail, KeyRound } from "lucide-react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../hooks/useAuth";
import { useI18n } from "../i18n";
import { SettingsLayout } from "../components/ui/SettingsLayout";
import { Surface } from "../components/ui/Surface";
import { FieldLabel, TextField } from "../components/ui/Field";
import { Button } from "../components/ui/Button";

type FormMessage = { type: "ok" | "err"; text: string } | null;

export function AccountPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState("email");

  return (
    <SettingsLayout kicker={t("ACCOUNT // PREFERENCES")} title={t("Account")}
      subtitle={t("Manage your email address and password.")}
      tabs={[{ id: "email", label: t("Email") }, { id: "password", label: t("Password") }]}
      activeTab={activeTab} onTabChange={setActiveTab}>
      <div hidden={activeTab !== "email"}><EmailTab email={user?.email ?? ""} /></div>
      <div hidden={activeTab !== "password"}><PasswordTab /></div>
    </SettingsLayout>
  );
}

function Feedback({ message }: { message: FormMessage }) {
  if (!message) return null;
  return <p role={message.type === "err" ? "alert" : "status"}
    className={`px-4 py-3 font-body text-sm leading-6 ${message.type === "ok" ? "bg-chip-sage text-ink-black" : "bg-chip-red/40 text-hero-red"}`}>
    {message.text}
  </p>;
}

function EmailTab({ email }: { email: string }) {
  const { t } = useI18n();
  const [newEmail, setNewEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<FormMessage>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !newEmail.trim() || newEmail.trim() === email) return;
    setBusy(true);
    setMessage(null);
    try {
      const { error } = await supabase.auth.updateUser({ email: newEmail.trim() });
      if (error) throw error;
      setMessage({ type: "ok", text: t("Check your inbox to confirm the new email.") });
      setNewEmail("");
    } catch (error) {
      setMessage({ type: "err", text: error instanceof Error ? error.message : t("We couldn't update your email. Please try again.") });
    } finally {
      setBusy(false);
    }
  }

  return <Surface border="soft" shadow="none">
    <div className="space-y-6 p-5 sm:p-7">
      <header>
        <Mail size={24} aria-hidden="true" className="mb-4 text-hero-red" />
        <h2 className="font-display text-2xl font-black tracking-tight">{t("Your email address")}</h2>
        <p className="mt-2 font-body text-sm leading-6 text-ink-muted">{t("Keep your sign-in address up to date.")}</p>
      </header>
      <div className="bg-surface-container px-4 py-3">
        <p className="font-meta text-xs font-bold uppercase tracking-wider text-ink-muted">{t("Current email")}</p>
        <p className="mt-1 break-all font-body text-base font-semibold">{email}</p>
      </div>
      <form aria-label={t("Change email")} onSubmit={handleSubmit} className="space-y-5">
        <div>
          <FieldLabel htmlFor="account-email">{t("New email address")}</FieldLabel>
          <TextField id="account-email" name="email" type="email" autoComplete="email" required
            value={newEmail} onChange={(e) => setNewEmail(e.target.value)} disabled={busy}
            aria-describedby="account-email-hint" className="mt-2 bg-bristol" />
          <p id="account-email-hint" className="mt-2 font-body text-sm leading-6 text-ink-muted">{t("You'll need to confirm the new address via email.")}</p>
        </div>
        <Feedback message={message} />
        <Button type="submit" size="sm" disabled={busy || !newEmail.trim() || newEmail.trim() === email}>
          {t(busy ? "Updating…" : "Update email")}
        </Button>
      </form>
    </div>
  </Surface>;
}

function PasswordTab() {
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<FormMessage>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (password.length < 6) {
      setMessage({ type: "err", text: t("Password must be at least 6 characters.") });
      return;
    }
    if (password !== confirm) {
      setMessage({ type: "err", text: t("Passwords don't match.") });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      setMessage({ type: "ok", text: t("Password updated successfully.") });
      setPassword("");
      setConfirm("");
    } catch (error) {
      setMessage({ type: "err", text: error instanceof Error ? error.message : t("We couldn't update your password. Please try again.") });
    } finally {
      setBusy(false);
    }
  }

  return <Surface border="soft" shadow="none">
    <div className="space-y-6 p-5 sm:p-7">
      <header>
        <KeyRound size={24} aria-hidden="true" className="mb-4 text-hero-red" />
        <h2 className="font-display text-2xl font-black tracking-tight">{t("Change your password")}</h2>
        <p className="mt-2 font-body text-sm leading-6 text-ink-muted">{t("Choose a password you don't use elsewhere.")}</p>
      </header>
      <form aria-label={t("Change password")} onSubmit={handleSubmit} className="space-y-5">
        <div>
          <FieldLabel htmlFor="account-password">{t("New password")}</FieldLabel>
          <TextField id="account-password" name="password" type="password" autoComplete="new-password"
            required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy}
            aria-describedby="account-password-hint" className="mt-2 bg-bristol" />
          <p id="account-password-hint" className="mt-2 font-body text-sm text-ink-muted">{t("Minimum 6 characters.")}</p>
        </div>
        <div>
          <FieldLabel htmlFor="account-password-confirm">{t("Confirm new password")}</FieldLabel>
          <TextField id="account-password-confirm" name="password-confirm" type="password" autoComplete="new-password"
            required minLength={6} value={confirm} onChange={(e) => setConfirm(e.target.value)} disabled={busy}
            className="mt-2 bg-bristol" />
        </div>
        <Feedback message={message} />
        <Button type="submit" size="sm" disabled={busy || !password || !confirm || password !== confirm || password.length < 6}>
          {t(busy ? "Updating…" : "Update password")}
        </Button>
      </form>
    </div>
  </Surface>;
}
