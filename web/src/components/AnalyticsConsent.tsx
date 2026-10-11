import { useSyncExternalStore } from "react";
import { Link, useLocation } from "react-router-dom";
import { useI18n } from "../i18n";
import { ga4MeasurementId, getGa4Consent, getServerGa4Consent, setGa4Consent, subscribeGa4Consent } from "../lib/ga4";
import { Button } from "./ui/Button";

const subscribeHydration = () => () => {};
const browserSnapshot = () => true;
const prerenderSnapshot = () => false;

export function AnalyticsConsent({ preferences = false }: { preferences?: boolean }) {
  // Avoid flashing a banner over prerendered pages before the stored choice is known.
  const hydrated = useSyncExternalStore(subscribeHydration, browserSnapshot, prerenderSnapshot);
  const consent = useSyncExternalStore(subscribeGa4Consent, getGa4Consent, getServerGa4Consent);
  const { pathname } = useLocation();
  const { t } = useI18n();
  // The privacy page renders its own inline preferences; avoid a duplicate banner there.
  const bannerHidden = consent !== null || pathname === "/legal/privacy";
  if (!hydrated || !ga4MeasurementId() || (!preferences && bannerHidden)) return null;
  return (
    <section aria-label={t("Google Analytics preferences")} className={preferences
      ? "my-6 border-2 border-ink-black bg-bristol p-5"
      : "fixed inset-x-3 bottom-3 z-[100] mx-auto max-w-3xl border-2 border-ink-black bg-bristol p-5 text-ink-black shadow-ink sm:inset-x-6"}>
      <h2 className="font-display text-lg font-bold">{t("Optional Google Analytics")}</h2>
      <p className="mt-2 font-body text-sm leading-6">{t("Allow Google Analytics to measure visits and completed signups? It uses analytics cookies. Your stories, artwork, and account details stay out of Google Analytics.")}</p>
      <p className="mt-2 font-body text-sm leading-6">
        <Link className="underline underline-offset-4 focus-visible:outline focus-visible:outline-2" to="/legal/privacy">{t("Privacy Policy")}</Link>
        {preferences && <> · {t(consent === "accepted" ? "Google Analytics is enabled." : "Google Analytics is disabled.")}</>}
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <Button variant="outline" size="sm" onClick={() => setGa4Consent("declined")}>{t("Decline Google Analytics")}</Button>
        <Button variant="outline" size="sm" onClick={() => setGa4Consent("accepted")}>{t("Allow Google Analytics")}</Button>
      </div>
    </section>
  );
}
