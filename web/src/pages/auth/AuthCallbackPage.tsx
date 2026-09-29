import { useEffect, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { useI18n } from "../../i18n";
import { supabase } from "../../lib/supabase";
import { authDestination, authRetryPath, oauthSignupMetadata } from "../../lib/authContext";
import { recordAccountSeen } from "../../api/events";
import { BrandMark } from "../../components/BrandMark";

export function AuthCallbackPage() {
  const { session, loading } = useAuth();
  const { t } = useI18n();
  const { search, hash } = useLocation();
  const navigate = useNavigate();
  const completion = useRef<{ userId: string; promise: Promise<void> } | null>(null);
  const hasError = new URLSearchParams(hash.slice(1)).has("error")
    || new URLSearchParams(search).has("error");

  useEffect(() => {
    if (loading || !session || hasError) return;
    if (completion.current?.userId !== session.user.id) {
      completion.current = { userId: session.user.id, promise: (async () => {
        const metadata = oauthSignupMetadata(session.user, new URLSearchParams(search));
        if (metadata) {
          try { await supabase.auth.updateUser({ data: metadata }); }
          catch { /* Attribution must never block access to the studio. */ }
        }
        await recordAccountSeen();
      })() };
    }
    // Attribution continues in the background; analytics latency cannot hold up sign-in.
    void completion.current.promise;
    navigate(authDestination(new URLSearchParams(search)), { replace: true });
  }, [session, loading, hasError, search, navigate]);

  const failed = hasError || (!loading && !session);
  const retry = authRetryPath(new URLSearchParams(search));
  return (
    <main className="flex min-h-svh items-center justify-center bg-pulp-paper px-6 py-12">
      <div className="w-full max-w-md border-[2px] border-ink-black bg-bristol p-8 text-ink-black shadow-ink">
        <BrandMark className="mb-6 h-12 w-12" />
        <h1 className="font-display text-3xl font-black tracking-tight">
          {t(failed ? "Let’s try signing in again" : "Opening your studio")}
        </h1>
        <p role={failed ? "alert" : "status"} className="mt-4 font-body text-base leading-7 text-ink-muted">
          {t(failed
            ? "Google sign-in did not finish. Try again to continue."
            : "Finishing your sign-in…")}
        </p>
        {failed && <Link to={retry} className="mt-6 inline-flex min-h-12 items-center font-body font-bold text-hero-red underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4">{t("Back to sign in")}</Link>}
      </div>
    </main>
  );
}
