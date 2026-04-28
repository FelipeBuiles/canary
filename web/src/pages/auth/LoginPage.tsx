import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabase";
import { useAuth } from "../../hooks/useAuth";
import { Surface } from "../../components/ui/Surface";
import { Button } from "../../components/ui/Button";
import { FieldLabel, TextField } from "../../components/ui/Field";

export function LoginPage() {
  const { session, loading } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && session) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setSubmitting(false);
    if (error) {
      setError(error.message);
    } else {
      navigate("/", { replace: true });
    }
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
                autoComplete="current-password"
                required
              />
            </div>

            {error && (
              <p className="font-meta text-xs text-hero-red">{error}</p>
            )}

            <Button type="submit" fullWidth disabled={submitting} className="mt-2">
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </Surface>

        <p className="mt-4 text-center font-meta text-xs text-ink-black/60">
          No account?{" "}
          <Link to="/signup" className="text-ink-black underline">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
}
