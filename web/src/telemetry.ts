/**
 * Content-free errors, canonical page views, anonymous signup intent, and
 * content-masked click and session replay capture. Authenticated product
 * events retain their API path. Identity stays memory-only. Bounded attribution
 * tokens expire in browser storage after 24 hours; URLs are reduced to route templates.
 */
import type { PostHog, CaptureResult } from "posthog-js/dist/module.no-external";

let client: PostHog | undefined;
let loading: Promise<void> | undefined;
let account: string | null = null;
const tokenPattern = /^[A-Za-z0-9_./:{}@+-]{1,160}$/;
const campaignPattern = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const labelPattern = /^[A-Za-z0-9 ._-]{1,40}$/;
const pathPattern = /^\/[a-z/:_-]{0,80}$/;
const staticPaths = new Set([
  "/", "/samples", "/login", "/signup", "/reset-password", "/account", "/credits", "/backoffice",
  "/legal/terms", "/legal/privacy", "/legal/acceptable-use",
]);
const projectRooms = new Set(["story", "cast", "pages", "book", "styles", "settings"]);

export interface Acquisition {
  source: string;
  medium?: string;
  campaign?: string;
  referring_domain?: string;
}

function campaignToken(value: string | null | undefined): string | undefined {
  const token = value?.trim().toLowerCase();
  return token && campaignPattern.test(token) ? token : undefined;
}

function campaignParams(search: string): Partial<Record<"utm_source" | "utm_medium" | "utm_campaign", string>> {
  const params = new URLSearchParams(search);
  const result: Partial<Record<"utm_source" | "utm_medium" | "utm_campaign", string>> = {};
  for (const key of ["utm_source", "utm_medium", "utm_campaign"] as const) {
    const value = campaignToken(params.get(key));
    if (value) result[key] = value;
  }
  return result;
}

/** First-touch attribution: bounded campaign tokens and an external referring domain only. */
export function readAcquisition(location: { search: string; hostname: string }, referrer: string): Acquisition {
  const campaign = campaignParams(location.search);
  let referringDomain: string | undefined;
  try {
    const host = new URL(referrer).hostname.toLowerCase().replace(/^www\./, "");
    if (host !== location.hostname.toLowerCase().replace(/^www\./, "")) referringDomain = campaignToken(host);
  } catch { /* No or malformed referrer: direct. */ }
  const bookReferral = /^book-[a-f0-9]{32}$/.test(new URLSearchParams(location.search).get("ref") ?? "");
  const result: Acquisition = {
    source: campaign.utm_source ?? (bookReferral ? "book_referral" : referringDomain ?? "direct"),
  };
  if (campaign.utm_medium) result.medium = campaign.utm_medium;
  if (campaign.utm_campaign) result.campaign = campaign.utm_campaign;
  if (referringDomain) result.referring_domain = referringDomain;
  return result;
}

const acquisitionKey = "canary:acquisition:v1";
const acquisitionTtl = 24 * 60 * 60 * 1000;

/** No IDs, URLs, content or raw query strings; storage denial is non-blocking. */
export function firstTouchAcquisition(storage: Pick<Storage, "getItem" | "setItem">, current: Acquisition, now = Date.now()): Acquisition {
  try {
    const raw = JSON.parse(storage.getItem(acquisitionKey) ?? "null");
    if (raw && Number.isFinite(raw.created) && raw.created <= now && now - raw.created < acquisitionTtl
      && raw.value && typeof raw.value.source === "string" && campaignToken(raw.value.source)) {
      const value: Acquisition = { source: campaignToken(raw.value.source)! };
      for (const key of ["medium", "campaign", "referring_domain"] as const) {
        const token = typeof raw.value[key] === "string" ? campaignToken(raw.value[key]) : undefined;
        if (token) value[key] = token;
      }
      return value;
    }
  } catch { /* Malformed or inaccessible storage: use this visit. */ }
  const value: Acquisition = { source: campaignToken(current.source) ?? "direct" };
  for (const key of ["medium", "campaign", "referring_domain"] as const) {
    const token = campaignToken(current[key]);
    if (token) value[key] = token;
  }
  try { storage.setItem(acquisitionKey, JSON.stringify({ created: now, value })); } catch { /* Optional storage. */ }
  return value;
}

const firstTouch: Acquisition = (() => {
  if (typeof window === "undefined") return { source: "direct" };
  const current = readAcquisition(window.location, document.referrer);
  try { return firstTouchAcquisition(window.localStorage, current); } catch { return current; }
})();

export function getAcquisition(): Acquisition {
  return { ...firstTouch };
}

/** Route template for analytics: never project/book IDs, query strings, or unknown paths. */
export function canonicalPath(pathname: string, signedIn: boolean): string {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/") return signedIn ? "/library" : "/";
  if (staticPaths.has(path)) return path;
  if (/^\/read\/[^/]+$/.test(path)) return "/read/:id";
  const project = /^\/project\/[^/]+(?:\/([^/]+))?/.exec(path);
  if (project) return project[1] ? `/project/:id/${projectRooms.has(project[1]) ? project[1] : "other"}` : "/project/:id";
  return "/other";
}

/** Links become same-origin route templates; external destinations are redacted. */
export function canonicalUrl(value: string): string {
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin) return window.location.origin + "/external";
    return window.location.origin + canonicalPath(url.pathname, account !== null);
  } catch {
    return window.location.origin + "/other";
  }
}

/**
 * Autocapture elements chain without text, attribute values, or link targets:
 * tag names, classes, and positions only. The SDK already masks text and
 * attributes; this is the fail-closed second pass.
 */
function scrubElementsChain(chain: string): string | undefined {
  if (chain.length > 4000) return undefined;
  const tags = chain.match(/(?:^|;)(?:button|a|input|textarea|select|option|div|span)(?=[.:;]|$)/g);
  return tags?.map(tag => tag.replace(/^;/, "")).join(";");
}

/**
 * Replay frames keep masked DOM structure. URLs are reduced to route
 * templates and plugin frames (console and network) are dropped, since they
 * can carry request URLs or logged content.
 */
const replayTags = new Set("html head body title div span p main section article aside header footer nav button a label input textarea select option ul ol li h1 h2 h3 h4 h5 h6 form fieldset legend details summary dialog table thead tbody tr th td br hr link meta".split(" "));
const replayKeys = new Set("id parentId nextId previousId type source x y timeOffset width height scrollTop scrollLeft isChecked positions adds removes texts attributes node childNodes initialOffset isSVG isShadow isShadowHost rootId".split(" "));
const replayAttributes = new Set(["href", "src", "rel", "type", "role", "width", "height", "aria-expanded", "aria-selected", "aria-pressed", "aria-hidden", "disabled", "checked"]);

/** Fail closed after rrweb serialization too: input masking alone cannot protect DOM attributes. */
function scrubReplayValue(value: unknown): unknown {
  if (value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) return value;
  if (Array.isArray(value)) return value.map(scrubReplayValue);
  if (!value || typeof value !== "object") return undefined;
  const result: Record<string, unknown> = {};
  const object = value as Record<string, unknown>;
  for (const [key, item] of Object.entries(object)) {
    if (key === "tagName") result[key] = typeof item === "string" && replayTags.has(item) ? item : "div";
    else if (key === "textContent" || key === "text" || key === "value") {
      if (typeof item === "string") result[key] = maskReplayText(item);
    } else if (key === "attributes" && item && typeof item === "object" && !Array.isArray(item)) {
      result[key] = Object.fromEntries(Object.entries(item).filter(([name]) => replayAttributes.has(name))
        .map(([name, content]) => [name, typeof content === "string" ? maskReplayAttribute(name, content) : null]));
    } else if (replayKeys.has(key)) {
      const clean = scrubReplayValue(item);
      if (clean !== undefined) result[key] = clean;
    }
  }
  // No script, CSS, media, iframe, or custom-element child content is replayable.
  if (typeof object.tagName === "string" && !replayTags.has(object.tagName)) {
    result.attributes = {};
    result.childNodes = [];
  }
  return result;
}

export function scrubSnapshotData(data: unknown): unknown[] | undefined {
  if (!Array.isArray(data)) return undefined;
  return data.flatMap(frame => {
    if (!frame || typeof frame !== "object") return [];
    const item = frame as { type?: unknown; timestamp?: unknown; data?: Record<string, unknown> };
    const payload = item.data;
    if ("cv" in frame || typeof payload === "string") return [];
    if (typeof item.type !== "number" || ![0, 1, 2, 3, 4, 5].includes(item.type)) return [];
    const timestamp = typeof item.timestamp === "number" && Number.isFinite(item.timestamp) ? { timestamp: item.timestamp } : {};
    if (item.type === 4) {
      if (typeof payload?.href !== "string") return [];
      return [{ type: 4, ...timestamp, data: { ...scrubReplayValue(payload) as object, href: canonicalUrl(payload.href) } }];
    }
    if (item.type === 5) {
      const inner = payload?.payload as Record<string, unknown> | undefined;
      if (payload?.tag !== "$url_changed" || typeof inner?.href !== "string") return [];
      return [{ type: 5, ...timestamp, data: { tag: "$url_changed", payload: { href: canonicalUrl(inner.href) } } }];
    }
    if (item.type === 3 && (typeof payload?.source !== "number" || payload.source < 0 || payload.source > 6)) return [];
    return [{ type: item.type, ...timestamp, data: scrubReplayValue(payload) ?? {} }];
  });
}

/** All prose, including dynamic controls and opt-out markers, stays masked. */
export function maskReplayText(text: string, _element?: HTMLElement | null): string {
  void _element; // rrweb supplies the element; no element may opt out of masking.
  return text.replace(/\S/g, "*");
}

export function maskReplayAttribute(name: string, value: string): string {
  if (name === "href" || name === "src") {
    try {
      const url = new URL(value, window.location.origin);
      if (url.origin === window.location.origin) return window.location.origin + canonicalPath(url.pathname, account !== null);
    } catch { /* Redact malformed or external destinations. */ }
    return "[redacted]";
  }
  if ((name === "width" || name === "height") && /^\d{1,5}$/.test(value)) return value;
  if (["aria-expanded", "aria-selected", "aria-pressed", "aria-hidden", "disabled", "checked"].includes(name) && ["true", "false", ""].includes(value)) return value;
  if (name === "role" && ["button", "dialog", "tab", "tabpanel", "navigation", "status", "alert", "group", "listbox", "option"].includes(value)) return value;
  if (name === "type" && ["button", "submit", "text", "password", "email", "checkbox", "radio", "search", "number"].includes(value)) return value;
  if (name === "rel" && ["stylesheet", "preload"].includes(value)) return value;
  return "[redacted]";
}

export function scrubEvent(event: CaptureResult | null): CaptureResult | null {
  if (!event) return null;
  try {
    if (!["$exception", "$identify", "$create_alias", "$pageview", "signup_submitted", "$autocapture", "$rageclick",
      "$snapshot"].includes(event.event)) return null;
    const source = event.properties ?? {};
    const properties: Record<string, unknown> = {
      $geoip_disable: true,
      // Anonymous visitors stay personless; identified accounts keep profiles.
      $process_person_profile: typeof source.$process_person_profile === "boolean" ? source.$process_person_profile : true,
      environment: import.meta.env.VITE_CANARY_ENV ?? "development",
      release: import.meta.env.VITE_CANARY_VERSION ?? "unknown",
      $release_id: import.meta.env.VITE_CANARY_VERSION ?? "unknown",
      schema_version: 1,
    };
    // The SDK puts its public ingestion credential in event properties before
    // before_send. Rebuild it from configuration, never from arbitrary payloads.
    const projectToken = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN;
    if (projectToken) properties.token = projectToken;
    for (const key of ["distinct_id", "$device_id", "$anon_distinct_id", "$session_id", "$window_id", "$exception_fingerprint",
      "$insert_id", "$pageview_id", "$lib", "$lib_version", "$sdk_dist_channel", "$config_defaults", "$timezone"]) {
      if (typeof source[key] === "string" && tokenPattern.test(source[key])) properties[key] = source[key];
    }
    for (const key of ["$browser", "$browser_language", "$browser_language_prefix", "$os", "$os_version", "$device_type", "$browser_type"]) {
      if (typeof source[key] === "string" && labelPattern.test(source[key])) properties[key] = source[key];
    }
    for (const key of ["$browser_version", "$screen_height", "$screen_width", "$viewport_height", "$viewport_width",
      "$timezone_offset", "$time", "$initialization_time", "$configured_session_timeout_ms"]) {
      if (typeof source[key] === "number" && Number.isFinite(source[key])) properties[key] = source[key];
    }
    if (typeof source.$is_identified === "boolean") properties.$is_identified = source.$is_identified;
    if (event.event === "$snapshot") {
      const frames = scrubSnapshotData(source.$snapshot_data);
      if (!frames || typeof properties.$session_id !== "string" || typeof properties.$window_id !== "string") return null;
      properties.$snapshot_data = frames;
      for (const key of ["$snapshot_bytes", "$snapshot_source", "$lib", "$lib_version"]) {
        if (typeof source[key] === "number" || (typeof source[key] === "string" && tokenPattern.test(source[key]))) {
          properties[key] = source[key];
        }
      }
      return { event: event.event, uuid: event.uuid, timestamp: event.timestamp, properties };
    }
    // Keep navigation context for clicks, errors, and conversion events too.
    const currentPath = canonicalPath(window.location.pathname, account !== null);
    Object.assign(properties, {
      $pathname: currentPath,
      $current_url: window.location.origin + currentPath,
      $host: window.location.host,
    });
    if (typeof source.$session_entry_url === "string") {
      const entry = new URL(canonicalUrl(source.$session_entry_url));
      properties.$session_entry_url = entry.href;
      properties.$session_entry_host = entry.host;
      properties.$session_entry_pathname = entry.pathname;
    }
    for (const key of ["$referring_domain", "$session_entry_referring_domain"]) {
      const value = source[key];
      const domain = campaignToken(typeof value === "string" ? value.replace(/^www\./, "") : undefined);
      properties[key] = domain && domain !== window.location.hostname.replace(/^www\./, "") ? domain : "$direct";
    }
    if (event.event === "$autocapture" || event.event === "$rageclick") {
      const path = canonicalPath(window.location.pathname, account !== null);
      Object.assign(properties, {
        $pathname: path,
        $current_url: window.location.origin + path,
        $host: window.location.host,
      });
      if (typeof source.$event_type === "string" && labelPattern.test(source.$event_type)) properties.$event_type = source.$event_type;
      const chain = typeof source.$elements_chain === "string" ? scrubElementsChain(source.$elements_chain) : undefined;
      if (chain) properties.$elements_chain = chain;
    }
    if (event.event === "$pageview") {
      const path = source.canonical_path;
      if (typeof path !== "string" || !pathPattern.test(path)) return null;
      Object.assign(properties, {
        $pathname: path,
        $current_url: window.location.origin + path,
        $host: window.location.host,
      });
    }
    for (const key of ["utm_source", "utm_medium", "utm_campaign", "acquisition_source", "acquisition_medium",
      "acquisition_campaign", "referring_domain"]) {
      if (event.event !== "$exception" && typeof source[key] === "string" && campaignPattern.test(source[key])) {
        properties[key] = source[key];
      }
    }
    if (Array.isArray(source.$exception_list)) {
      properties.$exception_list = source.$exception_list.slice(0, 5).map((item: Record<string, unknown>) => {
        const stack = item.stacktrace as { frames?: Record<string, unknown>[] } | undefined;
        return {
          type: typeof item.type === "string" && ["Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "URIError", "EvalError", "DOMException", "AbortError", "ApiError", "InsufficientCreditsError", "ChunkLoadError"].includes(item.type) ? item.type : "Error",
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
    return { event: event.event, uuid: event.uuid, timestamp: event.timestamp, properties };
  } catch {
    return null;
  }
}

export function setTelemetryUser(userId: string | null): void {
  if (account === userId) return;
  const previous = account;
  account = userId;
  if (!client) return;
  // Signing in from an anonymous visit keeps that visit's page views; switching
  // or leaving an account starts a fresh anonymous identity.
  if (previous) client.reset();
  if (userId) client.identify(userId);
}

export function initTelemetry(): Promise<void> {
  if (loading) return loading;
  const key = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN;
  const host = import.meta.env.VITE_POSTHOG_HOST;
  if (!key || !["https://us.i.posthog.com", "https://eu.i.posthog.com"].includes(host)) return Promise.resolve();
  loading = (async () => {
    await import("posthog-js/dist/exception-autocapture");
    // The no-external build never fetches scripts; bundle the replay recorder.
    await import("posthog-js/dist/posthog-recorder");
    const { default: posthog } = await import("posthog-js/dist/module.no-external");
    posthog.init(key, {
      api_host: host,
      // Clicks and rage clicks keep tag/class structure only (see scrubEvent).
      autocapture: { capture_copied_text: false },
      mask_all_text: true,
      mask_all_element_attributes: true,
      session_recording: {
        maskAllInputs: true,
        maskTextSelector: "*",
        maskTextFn: maskReplayText,
        maskAttributeFn: maskReplayAttribute,
        // Manuscript art, generated pages, and uploads are never recorded.
        blockSelector: "img, picture, video, audio, canvas, svg, iframe, object, embed, [data-ph-block]",
        // before_send must see serialized nodes, not opaque packed DOM strings.
        compress_events: false,
        recordHeaders: false,
        recordBody: false,
        recordCrossOriginIframes: false,
      },
      capture_pageview: false,
      capture_pageleave: false,
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

export function trackPageview(pathname: string, signedIn: boolean): void {
  const properties = { canonical_path: canonicalPath(pathname, signedIn), ...campaignParams(window.location.search) };
  void initTelemetry().then(() => client?.capture("$pageview", properties));
}

export function trackSignupSubmitted(): void {
  const { source, medium, campaign, referring_domain } = firstTouch;
  const properties: Record<string, string> = { acquisition_source: source };
  if (medium) properties.acquisition_medium = medium;
  if (campaign) properties.acquisition_campaign = campaign;
  if (referring_domain) properties.referring_domain = referring_domain;
  void initTelemetry().then(() => client?.capture("signup_submitted", properties));
}

export function captureUiError(error: unknown): void {
  void initTelemetry().then(() => client?.captureException(error));
}
