import type { User } from "@supabase/supabase-js";
import type { Acquisition } from "../telemetry";
import { authRedirectUrl } from "./authRedirect";

const samplePattern = /^[a-z0-9-]{1,100}$/;
const referralPattern = /^book-[a-f0-9]{32}$/;
const campaignPattern = /^[a-z0-9][a-z0-9._-]{0,63}$/;

export function authDestination(params: URLSearchParams): string {
  const sample = params.get("sample");
  return sample && samplePattern.test(sample) ? `/?sample=${encodeURIComponent(sample)}` : "/";
}

export function signupMetadata(params: URLSearchParams, acquisition: Acquisition) {
  const ref = params.get("ref");
  return {
    acquisition,
    ...(ref && referralPattern.test(ref) ? { referred_by_book: ref.slice(5) } : {}),
  };
}

export function authRetryPath(params: URLSearchParams): string {
  const retry = new URLSearchParams(authDestination(params).split("?")[1]);
  const ref = params.get("ref");
  if (ref && referralPattern.test(ref)) retry.set("ref", ref);
  for (const key of ["source", "medium", "campaign"] as const) {
    const value = params.get(key);
    if (value && campaignPattern.test(value)) retry.set(`utm_${key}`, value);
  }
  return `/login${retry.size ? `?${retry}` : ""}`;
}

/** Carry only bounded, non-secret attribution across browsers and production origins. */
export function authCallbackUrl(params: URLSearchParams, acquisition: Acquisition): string {
  const callback = new URL(authRedirectUrl("/auth/callback"));
  callback.searchParams.set("signup_started_at", String(Date.now()));
  const sample = params.get("sample");
  const ref = params.get("ref");
  if (sample && samplePattern.test(sample)) callback.searchParams.set("sample", sample);
  if (ref && referralPattern.test(ref)) callback.searchParams.set("ref", ref);
  for (const key of ["source", "medium", "campaign", "referring_domain"] as const) {
    const value = acquisition[key];
    if (value && campaignPattern.test(value)) callback.searchParams.set(key, value);
  }
  return callback.toString();
}

/** OAuth cannot accept signup metadata. Fill it once for a freshly created account. */
export function oauthSignupMetadata(user: User, params: URLSearchParams, now = Date.now()) {
  const createdAt = Date.parse(user.created_at);
  const age = now - createdAt;
  const rawStarted = params.get("signup_started_at");
  const started = rawStarted && /^\d{13}$/.test(rawStarted) ? Number(rawStarted) : NaN;
  // A bounded advisory start time admits delayed callback returns only when
  // the account was created during this flow. It never grants authorization.
  const withinFlow = Number.isFinite(started) && started <= now
    && now - started <= 24 * 60 * 60_000 && createdAt >= started - 60_000;
  if (user.app_metadata.provider !== "google" || user.user_metadata.acquisition
      || !Number.isFinite(age) || age < 0 || (age > 10 * 60_000 && !withinFlow)) return null;
  const acquisition: Acquisition = { source: "direct" };
  for (const key of ["source", "medium", "campaign", "referring_domain"] as const) {
    const value = params.get(key);
    if (value && campaignPattern.test(value)) acquisition[key] = value;
  }
  const metadata = signupMetadata(params, acquisition);
  // Never overwrite an existing referral when linking a provider.
  if (user.user_metadata.referred_by_book) delete metadata.referred_by_book;
  return metadata;
}
