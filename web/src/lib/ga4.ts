/** Optional acquisition analytics. Never queue visits made before consent. */
import { canonicalPath } from "../telemetry";
import { publicPages } from "./publicPages";

type Consent = "accepted" | "declined" | null;
type Command = (...args: unknown[]) => void;
type GoogleWindow = Window & { dataLayer?: unknown[]; gtag?: Command };
const consentKey = "scenewright:ga4-consent:v1";
const listeners = new Set<() => void>();
let consent: Consent = readConsent();
let loaded = false;
let script: HTMLScriptElement | undefined;
let command: Command | undefined;
let currentPage: Record<string, string> | undefined;
let previousLocation: string | undefined;
let lastSent: string | undefined;
let pendingPages: Record<string, string>[] = [];

function readConsent(): Consent {
  try {
    const value = localStorage.getItem(consentKey);
    return value === "accepted" || value === "declined" ? value : null;
  } catch { return null; }
}

export function ga4MeasurementId(): string | undefined {
  const id = import.meta.env.VITE_GA4_MEASUREMENT_ID as string | undefined;
  return import.meta.env.VITE_CANARY_ENV === "production" && /^G-[A-Z0-9]+$/.test(id ?? "") ? id : undefined;
}

export const getGa4Consent = () => consent;
export const getServerGa4Consent = () => null;
export function subscribeGa4Consent(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function removeCookies() {
  // Our stream uses the default _ga cookie prefix, path /, and host-only cookies.
  try {
    for (const cookie of document.cookie.split(";")) {
      const name = cookie.trim().split("=")[0];
      if (name === "_ga" || name.startsWith("_ga_")) document.cookie = `${name}=; Max-Age=0; Path=/`;
    }
  } catch { /* Cookie access denial must not prevent withdrawing consent. */ }
}

export function setGa4Consent(value: Exclude<Consent, null>): void {
  if (value === consent) return;
  applyConsent(value, true);
}

function applyConsent(value: Consent, persist: boolean): void {
  consent = value;
  if (persist && value) {
    try { localStorage.setItem(consentKey, value); } catch { /* This visit only. */ }
  }
  const id = ga4MeasurementId();
  if (id) Object.assign(window, { [`ga-disable-${id}`]: value !== "accepted" });
  pendingPages = [];
  if (value === "accepted") {
    if (currentPage && !loaded) pendingPages.push(currentPage);
    start();
  }
  else {
    command?.("consent", "update", { analytics_storage: "denied" });
    removeCookies();
    // A decline before the current page was sent must not suppress it after re-acceptance.
    if (lastSent !== currentPage?.page_location) lastSent = undefined;
  }
  listeners.forEach(listener => listener());
}

function sendCurrentPage() {
  if (!loaded || consent !== "accepted" || !currentPage || !command) return;
  // Update global defaults too: automatic engagement events must use safe URLs/titles.
  command("set", currentPage);
  if (lastSent === currentPage.page_location) return;
  command("event", "page_view", { ...currentPage, send_to: ga4MeasurementId() });
  lastSent = currentPage.page_location;
}

function configure() {
  if (consent !== "accepted" || !command || !currentPage) return;
  command("consent", "update", { analytics_storage: "granted" });
  const firstPage = pendingPages[0] ?? currentPage;
  command("set", firstPage);
  command("config", ga4MeasurementId(), {
    send_page_view: false, cookie_domain: "none",
    allow_google_signals: false, allow_ad_personalization_signals: false,
  });
  for (const page of pendingPages) {
    if (lastSent === page.page_location) continue;
    command("set", page);
    command("event", "page_view", { ...page, send_to: ga4MeasurementId() });
    lastSent = page.page_location;
  }
  pendingPages = [];
  sendCurrentPage();
}

function start() {
  const id = ga4MeasurementId();
  if (!id || consent !== "accepted" || !currentPage) return;
  Object.assign(window, { [`ga-disable-${id}`]: false });
  if (loaded) { configure(); return; }
  if (script) return;
  const google = window as GoogleWindow;
  const layer = google.dataLayer = google.dataLayer ?? [];
  // Google's dataLayer distinguishes gtag command Arguments from ordinary arrays.
  // eslint-disable-next-line prefer-rest-params
  command = google.gtag = function () { layer.push(arguments); } as Command;
  command("consent", "default", {
    analytics_storage: "denied", ad_storage: "denied", ad_user_data: "denied", ad_personalization: "denied",
  });
  command("js", new Date());
  script = document.createElement("script");
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${id}`;
  script.onload = () => { loaded = true; configure(); listeners.forEach(listener => listener()); };
  script.onerror = () => { script?.remove(); script = undefined; };
  document.head.append(script);
}

export function trackGa4Pageview(pathname: string, signedIn: boolean): void {
  const path = canonicalPath(pathname, signedIn);
  const location = window.location.origin + path;
  let referrer = previousLocation === location ? currentPage?.page_referrer ?? "" : previousLocation ?? "";
  if (!previousLocation) {
    try { referrer = new URL(document.referrer).origin + "/"; } catch { /* Direct visit. */ }
  }
  const params = new URLSearchParams(window.location.search);
  const campaign: Record<string, string> = {};
  for (const [query, field] of [["utm_source", "campaign_source"], ["utm_medium", "campaign_medium"], ["utm_campaign", "campaign_name"]]) {
    const value = params.get(query)?.trim().toLowerCase();
    if (value && /^[a-z0-9][a-z0-9._-]{0,63}$/.test(value)) campaign[field] = value;
  }
  // Empty fields prevent old campaign overrides following a later navigation.
  currentPage = {
    page_location: location, page_title: publicPages[path]?.title ?? "Scenewright comic studio",
    page_referrer: referrer, campaign_source: "", campaign_medium: "", campaign_name: "",
    campaign_id: "", campaign_term: "", campaign_content: "", ...campaign,
  };
  if (previousLocation !== location) previousLocation = location;
  if (consent === "accepted") {
    if (loaded) sendCurrentPage();
    else {
      if (pendingPages.at(-1)?.page_location !== location) pendingPages.push(currentPage);
      start();
    }
  }
}

export const ga4Ready = () => !!ga4MeasurementId() && consent === "accepted" && loaded;
export function trackGa4Signup(): void {
  if (ga4Ready()) command?.("event", "sign_up", { send_to: ga4MeasurementId() });
}

// A choice made in another tab applies here too, without replaying earlier visits.
if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key === consentKey || event.key === null) {
    const value = readConsent();
    if (value !== consent) applyConsent(value, false);
  }
});
