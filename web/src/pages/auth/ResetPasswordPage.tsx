import { ErrorNotice } from "../../components/composites/ErrorNotice";
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabase";
import { useAuth } from "../../hooks/useAuth";
import { Button } from "../../components/ui/Button";
import { BrandMark } from "../../components/BrandMark";
import { useI18n } from "../../i18n";

/**
 * Landing page for the Supabase password-recovery flow.
 *
 * `supabase.auth.resetPasswordForEmail` sends a link carrying a recovery token;
 * clicking it lands here with the token in the URL hash, which supabase-js
 * exchanges for a short-lived session (captured by `useAuth`'s
 * `onAuthStateChange` listener). This page then collects a new password and
 * calls `updateUser` to commit it.
 */
export function ResetPasswordPage() {
  const { session, loading } = useAuth();
  const navigate = useNavigate();
  const { t } = useI18n();
  const redirectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (redirectTimer.current) clearTimeout(redirectTimer.current); }, []);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<Error | string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // No session after load → the recovery token was missing/invalid/expired.
  // Send the user back to login so they can request a fresh link.
  if (!loading && !session) {
    return <Navigate to="/login" replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting || loading || !session || message) return;
    if (password.length < 6) {
      setError(t("Password must be at least 6 characters."));
      return;
    }
    if (password !== confirm) {
      setError(t("Passwords don't match."));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      setMessage(t("Password updated. Redirecting to sign in…"));
      setPassword("");
      setConfirm("");
      redirectTimer.current = setTimeout(() => navigate("/login", { replace: true }), 1500);
    } catch (error) {
      setError(error instanceof Error ? error : new Error(t("We couldn't update your password. Please try again.")));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-svh flex-col bg-ink-black text-pulp-paper">
      <header className="flex h-14 shrink-0 items-center border-b-[2px] border-ink-black bg-bristol px-4 text-ink-black">
        <Link to="/" className="flex items-center gap-2.5">
          <BrandMark className="h-8 w-8 shrink-0" variant="micro" />
          <span className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
            Scenewright
          </span>
        </Link>
      </header>

      <main className="relative flex flex-1 items-center justify-center overflow-hidden px-6 py-12">
        <div aria-hidden="true" className="absolute inset-y-[8%] right-0 w-[45%] bg-[radial-gradient(circle_at_1px_1px,rgba(252,250,237,0.1)_1px,transparent_0)] [background-size:22px_22px]" />
        <div className="relative w-full max-w-sm">
          <div aria-hidden="true" className="absolute inset-0 translate-x-2 translate-y-2 bg-hero-red" />
          <form
            onSubmit={handleSubmit}
            aria-label={t("Set a new password")}
            className="relative w-full space-y-5 border-[3px] border-ink-black bg-bristol p-6 text-ink-black sm:p-8"
          >
          <div className="flex flex-col items-center gap-3 pb-2 text-center">
            <BrandMark className="h-12 w-12" variant="primary" />
            <h1 className="font-display text-[1.4rem] font-black uppercase tracking-[-0.02em] text-ink-black">
              {t("Set a new password")}
            </h1>
            <p className="font-body text-sm leading-6 text-ink-muted">{t("Choose a password you don't use elsewhere.")}</p>
          </div>

          {error && (typeof error === "string" ? <p role="alert" className="bg-chip-red/50 px-3 py-2 text-center font-body text-[0.85rem] font-semibold text-hero-red">{error}</p> : <ErrorNotice error={error} operation="auth" />)}
          {message && (
            <p role="status" className="bg-chip-sage px-3 py-2 text-center font-body text-[0.85rem] font-semibold text-ink-black">
              {message}
            </p>
          )}

          <label className="block">
            <span className="font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-muted">
              {t("New password")}
            </span>
            <input
              type="password"
              disabled={submitting || loading || !!message}
              aria-describedby="reset-password-hint"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
              minLength={6}
              placeholder="••••••••"
              className="ui-field mt-2 h-12"
            />
          </label>

          <p id="reset-password-hint" className="font-body text-sm text-ink-muted">{t("Minimum 6 characters.")}</p>
          <label className="block">
            <span className="font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-muted">{t("Confirm new password")}</span>
            <input type="password" autoComplete="new-password" required minLength={6}
              value={confirm} onChange={(event) => setConfirm(event.target.value)}
              disabled={submitting || loading || !!message} className="ui-field mt-2 h-12" />
          </label>
          <Button type="submit" className="w-full" disabled={submitting || loading || !!message}>
            {t(submitting ? "WORKING…" : "UPDATE PASSWORD")}
          </Button>
          </form>
        </div>
      </main>
    </div>
  );
}
