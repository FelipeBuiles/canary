import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabase";
import { useAuth } from "../../hooks/useAuth";
import { Button } from "../../components/ui/Button";
import { BrandMark } from "../../components/BrandMark";

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
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // No session after load → the recovery token was missing/invalid/expired.
  // Send the user back to login so they can request a fresh link.
  if (!loading && !session) {
    return <Navigate to="/login" replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const { error } = await supabase.auth.updateUser({ password });
    setSubmitting(false);
    if (error) {
      setError(error.message);
    } else {
      setMessage("Password updated. Redirecting to sign in…");
      setTimeout(() => navigate("/login", { replace: true }), 1500);
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
            className="relative w-full space-y-5 border-[3px] border-ink-black bg-bristol p-8 text-ink-black"
          >
          <div className="flex flex-col items-center gap-3 pb-2 text-center">
            <BrandMark className="h-12 w-12" variant="primary" />
            <h1 className="font-display text-[1.4rem] font-black uppercase tracking-[-0.02em] text-ink-black">
              Set a new password
            </h1>
          </div>

          {error && (
            <p role="alert" className="border-[2px] border-hero-red bg-chip-red/50 px-3 py-2 text-center font-body text-[0.85rem] font-semibold text-hero-red">
              {error}
            </p>
          )}
          {message && (
            <p role="status" className="animate-register-stamp border-[2px] border-archive-sage bg-chip-sage px-3 py-2 text-center font-body text-[0.85rem] font-semibold text-archive-sage">
              {message}
            </p>
          )}

          <label className="block">
            <span className="font-meta text-[0.6rem] font-bold uppercase tracking-[0.2em] text-ink-black/55">
              New password
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
              minLength={6}
              placeholder="••••••••"
              className="ui-field mt-2 h-12"
            />
          </label>

          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "WORKING…" : "UPDATE PASSWORD"}
          </Button>
          </form>
        </div>
      </main>
    </div>
  );
}
