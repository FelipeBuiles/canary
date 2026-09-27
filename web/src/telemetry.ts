/** Content-free errors only. Product events retain their authenticated API path. */
import type { PostHog, CaptureResult } from "posthog-js/dist/module.no-external";

let client: PostHog | undefined;
let loading: Promise<void> | undefined;
let account: string | null = null;
const tokenPattern = /^[A-Za-z0-9_./:{}@+-]{1,160}$/;

export function scrubEvent(event: CaptureResult | null): CaptureResult | null {
  if (!event) return null;
  try {
    if (!["$exception", "$identify", "$create_alias"].includes(event.event)) return null;
    const source = event.properties ?? {};
    const properties: Record<string, unknown> = {
      $geoip_disable: true,
      $process_person_profile: true,
      environment: import.meta.env.VITE_CANARY_ENV ?? "development",
      release: import.meta.env.VITE_CANARY_VERSION ?? "unknown",
      $release_id: import.meta.env.VITE_CANARY_VERSION ?? "unknown",
      schema_version: 1,
    };
    for (const key of ["distinct_id", "$device_id", "$anon_distinct_id", "$session_id", "$window_id", "$exception_fingerprint"]) {
      if (typeof source[key] === "string" && tokenPattern.test(source[key])) properties[key] = source[key];
    }
    if (Array.isArray(source.$exception_list)) {
      properties.$exception_list = source.$exception_list.slice(0, 5).map((item: Record<string, unknown>) => {
        const stack = item.stacktrace as { frames?: Record<string, unknown>[] } | undefined;
        return {
          type: typeof item.type === "string" && tokenPattern.test(item.type) ? item.type : "Error",
          value: "[redacted]",
          stacktrace: { frames: (stack?.frames ?? []).slice(-40).map(frame => {
            const clean: Record<string, unknown> = {};
            for (const key of ["lineno", "colno", "in_app", "platform"]) clean[key] = frame[key];
            // Retain deployed asset path/chunk IDs for source maps, never queries or external URLs.
            if (typeof frame.filename === "string") {
              const url = new URL(frame.filename, window.location.origin);
              if (url.origin === window.location.origin && /^\/assets\/[A-Za-z0-9_.-]+\.js$/.test(url.pathname)) clean.filename = url.pathname;
            }
            for (const key of ["function", "module", "chunk_id"]) {
              if (typeof frame[key] === "string" && tokenPattern.test(frame[key])) clean[key] = frame[key];
            }
            return clean;
          }) },
        };
      });
      properties.$exception_message = "[redacted]";
    }
    return { ...event, properties };
  } catch {
    return null;
  }
}

export function setTelemetryUser(userId: string | null): void {
  if (account === userId) return;
  account = userId;
  if (!client) return;
  client.reset();
  if (userId) client.identify(userId);
}

export function initTelemetry(): Promise<void> {
  if (loading) return loading;
  const key = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN;
  const host = import.meta.env.VITE_POSTHOG_HOST;
  if (!key || !["https://us.i.posthog.com", "https://eu.i.posthog.com"].includes(host)) return Promise.resolve();
  loading = (async () => {
    await import("posthog-js/dist/exception-autocapture");
    const { default: posthog } = await import("posthog-js/dist/module.no-external");
    posthog.init(key, {
      api_host: host,
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      disable_session_recording: true,
      disable_surveys: true,
      enable_heatmaps: false,
      capture_dead_clicks: false,
      capture_exceptions: { capture_unhandled_errors: true, capture_unhandled_rejections: true, capture_console_errors: false },
      person_profiles: "identified_only",
      persistence: "memory",
      ip: false,
      before_send: scrubEvent,
    });
    client = posthog;
    if (account) posthog.identify(account);
  })().catch(() => { /* Telemetry must not prevent the application from loading. */ });
  return loading;
}

export function captureUiError(error: unknown): void {
  void initTelemetry().then(() => client?.captureException(error));
}
