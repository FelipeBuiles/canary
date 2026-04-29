import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { supabase } from "../../lib/supabase";
import { useAuth } from "../../hooks/useAuth";
import { cn } from "../../lib/cn";

type AuthMode = "signin" | "signup";

interface LoginPageProps {
  initialMode?: AuthMode;
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

  return (
    <div className="min-h-screen bg-ink-black text-pulp-paper">
      <header className="fixed inset-x-0 top-0 z-10 flex h-12 items-center border-b border-pulp-paper/10 bg-bristol px-6 text-ink-black">
        <div className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
          PULP
        </div>
        <div className="ml-3 bg-hero-red px-2.5 py-1 font-meta text-[0.56rem] font-bold tracking-[0.18em] text-bristol">
          BETA
        </div>
      </header>

      <main className="grid min-h-screen grid-cols-1 pt-12 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section className="relative flex min-h-[48rem] flex-col justify-between overflow-hidden border-r border-pulp-paper/10 px-8 py-14 sm:px-14 lg:px-[4.8vw]">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(252,250,237,0.035)_1px,transparent_0)] [background-size:28px_28px]" />
          <div className="relative">
            <div className="font-meta text-[0.7rem] font-bold uppercase tracking-[0.48em] text-hero-red">
              PULP
            </div>
            <h1 className="mt-[13vh] max-w-[6ch] font-display text-[clamp(5.4rem,10vw,10.5rem)] font-black uppercase leading-[0.82] tracking-[-0.045em] text-pulp-paper">
              YOUR STORY. IN PANELS.
            </h1>
            <p className="mt-14 max-w-[32rem] border-l-[4px] border-hero-red pl-7 text-[1.05rem] font-semibold leading-8 text-pulp-paper/42">
              Upload a novel. PULP extracts characters, plans compositions, and draws every panel -- a full comic pipeline powered by AI.
            </p>
          </div>
          <div className="relative font-meta text-[0.62rem] uppercase tracking-[0.22em] text-pulp-paper/18">
            © 2026 Pulp Studio
          </div>
        </section>

        <section className="flex items-center justify-center px-7 py-12 lg:px-10">
          <div className="w-full">
            <div className="grid grid-cols-2 border-b border-pulp-paper/10">
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
                    "min-h-12 border-b-[3px] font-meta text-[0.68rem] font-bold uppercase tracking-[0.2em] transition-colors",
                    mode === value
                      ? "border-hero-red text-pulp-paper"
                      : "border-transparent text-pulp-paper/28 hover:text-pulp-paper/60",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="mt-9 space-y-5">
              {mode === "signup" && (
                <label className="block">
                  <span className="font-meta text-[0.6rem] font-bold uppercase tracking-[0.2em] text-pulp-paper/32">
                    Studio Name
                  </span>
                  <input
                    value={studioName}
                    onChange={(event) => setStudioName(event.target.value)}
                    autoComplete="organization"
                    required
                    className="mt-2 h-13 w-full border border-pulp-paper/16 bg-pulp-paper/[0.055] px-4 font-body text-[0.95rem] text-pulp-paper outline-none transition-colors placeholder:text-pulp-paper/22 focus:border-hero-red"
                    placeholder="Inkwell Studio"
                  />
                </label>
              )}

              <label className="block">
                <span className="font-meta text-[0.6rem] font-bold uppercase tracking-[0.2em] text-pulp-paper/32">
                  Email
                </span>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                  className="mt-2 h-13 w-full border border-pulp-paper/16 bg-pulp-paper/[0.055] px-4 font-body text-[0.95rem] text-pulp-paper outline-none transition-colors placeholder:text-pulp-paper/22 focus:border-hero-red"
                  placeholder="you@example.com"
                />
              </label>

              <label className="block">
                <span className="font-meta text-[0.6rem] font-bold uppercase tracking-[0.2em] text-pulp-paper/32">
                  Password
                </span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "signup" ? "new-password" : "current-password"}
                  required
                  className="mt-2 h-13 w-full border border-pulp-paper/16 bg-pulp-paper/[0.055] px-4 font-body text-[0.95rem] text-pulp-paper outline-none transition-colors placeholder:text-pulp-paper/22 focus:border-hero-red"
                  placeholder="••••••••"
                />
              </label>

              {error && <p className="font-body text-sm text-hero-red">{error}</p>}
              {message && <p className="font-body text-sm text-pulp-paper/58">{message}</p>}

              <button
                type="submit"
                disabled={submitting}
                className="mt-6 flex h-14 w-full items-center justify-center bg-hero-red px-5 font-meta text-[0.72rem] font-bold uppercase tracking-[0.24em] text-bristol transition-colors hover:bg-[#8a1019] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "Working..." : mode === "signup" ? "Create Account" : "Sign In"}
              </button>

              {mode === "signin" ? (
                <button
                  type="button"
                  className="mx-auto block pt-1 font-body text-[0.8rem] font-semibold text-pulp-paper/22 transition-colors hover:text-pulp-paper/48"
                >
                  Forgot password?
                </button>
              ) : (
                <p className="pt-1 text-center font-body text-[0.8rem] font-semibold text-pulp-paper/34">
                  500 free credits on signup.
                </p>
              )}
            </form>
          </div>
        </section>
      </main>
    </div>
  );
}
