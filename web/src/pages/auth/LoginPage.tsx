import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabase";
import { useAuth } from "../../hooks/useAuth";
import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import { BrandMark } from "../../components/BrandMark";

type AuthMode = "signin" | "signup";

interface LoginPageProps {
  initialMode?: AuthMode;
}

function Field({
  label,
  ...inputProps
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="font-meta text-[0.6rem] font-bold uppercase tracking-[0.2em] text-ink-black/55">
        {label}
      </span>
      <input
        {...inputProps}
        className="mt-2 h-12 w-full border-b-[2px] border-ink-black/30 bg-surface-container px-4 font-body text-[0.95rem] text-ink-black outline-none transition-colors placeholder:text-ink-black/38 focus:border-hero-red"
      />
    </label>
  );
}

export function LoginPage({ initialMode = "signin" }: LoginPageProps) {
  const { session, loading } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [studioName, setStudioName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && session) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setSubmitting(true);

    if (mode === "signup") {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: { studio_name: studioName } },
      });
      setSubmitting(false);
      if (error) {
        setError(error.message);
        return;
      }
      setMessage(`Check ${email} for the confirmation link.`);
      return;
    }

    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setSubmitting(false);
    if (error) {
      setError(error.message);
    } else {
      navigate("/", { replace: true });
    }
  }

  async function handleForgotPassword() {
    setError(null);
    setMessage(null);
    if (!email) {
      setError("Enter your email above, then tap “Forgot password?” again.");
      return;
    }
    setSubmitting(true);
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });
    setSubmitting(false);
    if (error) {
      setError(error.message);
    } else {
      setMessage(`Check ${email} for a password-reset link.`);
    }
  }

  return (
    <div className="flex min-h-svh flex-col bg-ink-black text-pulp-paper">
      <header className="flex h-14 shrink-0 items-center border-b-[2px] border-ink-black bg-bristol px-4 text-ink-black">
        <div className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
          Scenewright
        </div>
        <div className="ml-3 bg-hero-red px-2.5 py-1 font-meta text-[0.54rem] font-bold tracking-[0.16em] text-bristol">
          BETA
        </div>
      </header>

      <main className="grid flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_520px]">
        {/* The pressroom stage */}
        <section className="relative flex flex-col justify-between overflow-hidden px-8 py-10 sm:px-14 lg:px-[4.8vw]">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(252,250,237,0.09)_1px,transparent_0)] [background-size:28px_28px]" />
          <div className="relative">
            <div className="flex items-center gap-4 text-pulp-paper">
              <BrandMark className="h-10 w-10 shrink-0" />
              <div className="font-meta text-[0.7rem] font-bold uppercase tracking-[0.48em] text-hero-red">
                Scenewright
              </div>
            </div>
            <h1 className="mt-[6vh] max-w-[10ch] font-display text-[clamp(3.4rem,6.8vw,7rem)] font-black uppercase leading-[0.84] tracking-[-0.04em] text-pulp-paper">
              Your novel, scene by scene.
            </h1>
            <p className="mt-8 max-w-[32rem] border-l-[4px] border-hero-red pl-7 text-[1.05rem] font-semibold leading-8 text-pulp-paper/65">
              Upload your manuscript. Scenewright drafts characters, storyboards each chapter, and lays out every panel — you direct every page, and the work stays yours.
            </p>
          </div>
          <div className="relative mt-12 font-meta text-[0.62rem] uppercase tracking-[0.22em] text-pulp-paper/40">
            © 2026 Scenewright
          </div>
        </section>

        {/* The printed sheet */}
        <section className="relative flex items-center justify-center px-6 pb-14 pt-4 lg:px-12 lg:py-12">
          <div className="relative w-full max-w-[400px]">
            <div aria-hidden className="absolute inset-0 translate-x-2 translate-y-2 bg-hero-red" />
            <div className="relative border-[3px] border-ink-black bg-bristol text-ink-black">
              <div className="grid grid-cols-2 border-b-[2px] border-ink-black">
                {([
                  ["signin", "Sign In"],
                  ["signup", "Create Account"],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => {
                      setMode(value);
                      setError(null);
                      setMessage(null);
                    }}
                    className={cn(
                      "min-h-12 font-meta text-[0.64rem] font-bold uppercase tracking-[0.18em] transition-colors",
                      mode === value
                        ? "bg-hero-red text-bristol"
                        : "bg-bristol text-ink-black/55 hover:text-ink-black",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <form onSubmit={handleSubmit} className="space-y-5 px-7 py-8">
                {mode === "signup" && (
                  <Field
                    label="Studio Name"
                    value={studioName}
                    onChange={(event) => setStudioName(event.target.value)}
                    autoComplete="organization"
                    required
                    placeholder="Inkwell Studio"
                  />
                )}

                <Field
                  label="Email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                  placeholder="you@example.com"
                />

                <Field
                  label="Password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "signup" ? "new-password" : "current-password"}
                  required
                  placeholder="••••••••"
                />

                {error && (
                  <p className="border-[2px] border-hero-red bg-chip-red/50 px-3 py-2 font-body text-sm font-semibold text-hero-red">
                    {error}
                  </p>
                )}
                {message && (
                  <p className="border-[2px] border-ink-black bg-chip-gold px-3 py-2 font-body text-sm font-semibold text-ink-black">
                    {message}
                  </p>
                )}

                <Button type="submit" size="md" fullWidth disabled={submitting} className="mt-2">
                  {submitting ? "WORKING…" : mode === "signup" ? "CREATE ACCOUNT" : "SIGN IN"}
                </Button>

                {mode === "signin" ? (
                  <button
                    type="button"
                    onClick={handleForgotPassword}
                    disabled={submitting}
                    className="mx-auto block pt-1 font-body text-[0.8rem] font-semibold text-ink-black/55 transition-colors hover:text-ink-black disabled:opacity-50"
                  >
                    Forgot password?
                  </button>
                ) : (
                  <p className="pt-1 text-center font-body text-[0.8rem] font-semibold text-ink-black/60">
                    500 free credits on signup. By creating an account you agree
                    to our{" "}
                    <Link to="/legal/terms" className="text-ink-black underline underline-offset-2">
                      Terms
                    </Link>{" "}
                    and{" "}
                    <Link to="/legal/privacy" className="text-ink-black underline underline-offset-2">
                      Privacy Policy
                    </Link>
                    .
                  </p>
                )}
              </form>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
