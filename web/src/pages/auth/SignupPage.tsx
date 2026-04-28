import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { supabase } from "../../lib/supabase";
import { useAuth } from "../../hooks/useAuth";
import { Surface } from "../../components/ui/Surface";
import { Button } from "../../components/ui/Button";
import { FieldLabel, TextField } from "../../components/ui/Field";

export function SignupPage() {
  const { session, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (!loading && session) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const { error } = await supabase.auth.signUp({ email, password });
    setSubmitting(false);
    if (error) {
      setError(error.message);
    } else {
      setConfirming(true);
    }
  }

  if (confirming) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-pulp-paper p-4">
        <div className="w-full max-w-sm text-center">
          <Surface tone="bristol" shadow="ink" padding="lg">
            <p className="font-display text-lg font-bold text-ink-black">Check your email</p>
            <p className="mt-2 font-meta text-xs text-ink-black/70">
              We sent a confirmation link to <strong>{email}</strong>. Click it to activate your
              account.
            </p>
            <div className="mt-4">
              <Link to="/login">
                <Button variant="outline" fullWidth>Back to sign in</Button>
              </Link>
            </div>
          </Surface>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-pulp-paper p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="font-display text-4xl font-black tracking-tight text-ink-black">
            PULP
          </h1>
          <p className="mt-1 font-meta text-xs tracking-widest text-ink-black/50 uppercase">
            Novel to Comic
          </p>
        </div>

        <Surface tone="bristol" shadow="ink" padding="lg">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <TextField
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <TextField
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </div>

            {error && (
              <p className="font-meta text-xs text-hero-red">{error}</p>
            )}

            <Button type="submit" fullWidth disabled={submitting} className="mt-2">
              {submitting ? "Creating account…" : "Create account"}
            </Button>
          </form>
        </Surface>

        <p className="mt-4 text-center font-meta text-xs text-ink-black/60">
          Already have an account?{" "}
          <Link to="/login" className="text-ink-black underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
