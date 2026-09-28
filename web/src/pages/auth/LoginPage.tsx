import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { supabase } from "../../lib/supabase";
import { useAuth } from "../../hooks/useAuth";
import { Button } from "../../components/ui/Button";
import { BrandMark } from "../../components/BrandMark";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";
import { getAcquisition, trackSignupSubmitted } from "../../telemetry";

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
      <span className="font-meta text-xs font-bold uppercase tracking-[0.1em] text-ink-muted">
        {label}
      </span>
      <input
        {...inputProps}
        className="mt-2 h-12 w-full border-b-[2px] border-ink-black/30 bg-surface-container px-4 font-body text-base text-ink-black outline-none transition-colors placeholder:text-ink-soft focus:border-hero-red focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red disabled:opacity-60"
      />
    </label>
  );
}

export function LoginPage({ initialMode = "signin" }: LoginPageProps) {
  const { session, loading } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sample = searchParams.get("sample");
  const sampleDestination = sample && /^[a-z0-9-]{1,100}$/.test(sample)
    ? `/?sample=${encodeURIComponent(sample)}` : "/";
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [studioName, setStudioName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && session) {
    return <Navigate to={sampleDestination} replace />;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting || loading) return;
    setError(null);
    setMessage(null);
    setSubmitting(true);
    try {
      if (mode === "signup") {
        const reference = searchParams.get("ref");
        const referral = reference && /^book-[a-f0-9]{32}$/.test(reference)
          ? { referred_by_book: reference.slice(5) }
          : {};
        const { error } = await supabase.auth.signUp({
          email: email.trim(), password,
          options: {
            // First-touch attribution survives the email-confirmation hop.
            data: { studio_name: studioName, ...referral, acquisition: getAcquisition() },
            ...(sampleDestination !== "/" ? { emailRedirectTo: `${window.location.origin}${sampleDestination}` } : {}),
          },
        });
        if (error) throw error;
        trackSignupSubmitted();
        setMessage(t("Check {email} for the confirmation link.", { email: email.trim() }));
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
        if (error) throw error;
        navigate(sampleDestination, { replace: true });
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : t("We couldn't complete that request. Please try again."));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleForgotPassword() {
    if (submitting || loading) return;
    setError(null);
    setMessage(null);
    if (!email.trim()) {
      setError(t("Enter your email above, then tap “Forgot password?” again."));
      return;
    }
    setSubmitting(true);
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (error) throw error;
      setMessage(t("Check {email} for a password-reset link.", { email: email.trim() }));
    } catch (error) {
      setError(error instanceof Error ? error.message : t("We couldn't send the reset link. Please try again."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-svh flex-col bg-ink-black text-pulp-paper">
      <header className="flex h-14 shrink-0 items-center gap-2.5 border-b-[2px] border-ink-black bg-bristol px-4 text-ink-black">
        <BrandMark className="h-8 w-8 shrink-0" variant="micro" />
        <div className="font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.03em]">
          Scenewright
        </div>
        <div className="ml-3 bg-hero-red px-2.5 py-1 font-meta text-[0.54rem] font-bold tracking-[0.16em] text-bristol">
          BETA
        </div>
      </header>

      <main className="grid flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_520px]">
        {/* The pressroom stage */}
        <section className="relative order-2 flex flex-col justify-between overflow-hidden px-6 py-8 sm:px-14 lg:order-1 lg:px-[4.8vw] lg:py-10">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(252,250,237,0.09)_1px,transparent_0)] [background-size:28px_28px]" />
          <div className="relative">
            <div className="hidden items-center gap-4 text-pulp-paper lg:flex">
              <BrandMark className="h-12 w-12 shrink-0" variant="reversed" />
              <div className="font-meta text-sm font-bold uppercase tracking-[0.24em] text-narrator-gold">
                Scenewright
              </div>
            </div>
            <h1 className="max-w-[15ch] font-display text-3xl font-black uppercase leading-[0.95] tracking-[-0.04em] text-pulp-paper lg:mt-[6vh] lg:max-w-[10ch] lg:text-[clamp(3.4rem,6.8vw,6rem)]">
              Your novel, scene by scene.
            </h1>
            <p className="mt-5 max-w-[32rem] text-base font-semibold leading-7 text-pulp-paper/80 lg:mt-8 lg:bg-bristol/8 lg:px-5 lg:py-4">
              Upload your manuscript. Scenewright shapes the adaptation, plans the book, and draws complete comic pages — you review every page, and we claim no ownership over what you make.
            </p>
          </div>
          <div className="relative mt-8 font-meta text-xs uppercase tracking-[0.1em] text-pulp-paper/70">
            © 2026 Scenewright
          </div>
        </section>

        {/* The printed sheet */}
        <section className="relative order-1 flex items-center justify-center px-6 pb-6 pt-8 lg:order-2 lg:px-12 lg:py-12">
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
                    aria-pressed={mode === value}
                    disabled={submitting || loading}
                    onClick={() => {
                      setMode(value);
                      setError(null);
                      setMessage(null);
                    }}
                    className={cn(
                      "min-h-12 px-2 font-meta text-xs font-bold uppercase tracking-[0.1em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-ink-black disabled:opacity-60",
                      mode === value
                        ? "bg-hero-red text-bristol"
                        : "bg-bristol text-ink-black/55 hover:text-ink-black",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <form aria-label={t(mode === "signup" ? "Create account" : "Sign in")} onSubmit={handleSubmit} className="space-y-5 px-5 py-7 sm:px-7 sm:py-8">
                <div>
                  <h2 className="font-display text-2xl font-black tracking-tight">{t(mode === "signup" ? "Create your studio" : "Welcome back")}</h2>
                  <p className="mt-2 font-body text-sm leading-6 text-ink-muted">{t(mode === "signup" ? "Give your stories a place to take shape." : "Sign in to pick up where you left off.")}</p>
                </div>
                {mode === "signup" && (
                  <Field
                    label={t("Studio Name")}
                    disabled={submitting || loading}
                    value={studioName}
                    onChange={(event) => setStudioName(event.target.value)}
                    autoComplete="organization"
                    required
                    placeholder="Inkwell Studio"
                  />
                )}

                <Field
                  label={t("Email")}
                  disabled={submitting || loading}
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                  placeholder="you@example.com"
                />

                <Field
                  label={t("Password")}
                  disabled={submitting || loading}
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "signup" ? "new-password" : "current-password"}
                  required
                  placeholder="••••••••"
                />

                {error && (
                  <p role="alert" className="bg-chip-red/50 px-3 py-2 font-body text-sm font-semibold text-hero-red">
                    {error}
                  </p>
                )}
                {message && (
                  <p role="status" className="bg-chip-gold px-3 py-2 font-body text-sm font-semibold text-ink-black">
                    {message}
                  </p>
                )}

                <Button type="submit" size="md" fullWidth disabled={submitting || loading} className="mt-2">
                  {t(submitting ? "WORKING…" : mode === "signup" ? "CREATE ACCOUNT" : "SIGN IN")}
                </Button>

                {mode === "signin" ? (
                  <button
                    type="button"
                    onClick={handleForgotPassword}
                    disabled={submitting || loading}
                    className="mx-auto block min-h-11 px-3 pt-1 font-body text-sm font-semibold text-ink-muted transition-colors hover:text-ink-black disabled:opacity-50"
                  >
                    Forgot password?
                  </button>
                ) : (
                  <p className="pt-1 text-center font-body text-[0.8rem] font-semibold text-ink-black/60">
                    No subscription. Credits never expire. By creating an
                    account you agree to our{" "}
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
