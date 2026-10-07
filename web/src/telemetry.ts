/**
 * Content-free errors, canonical page views, anonymous signup intent, and
 * content-masked click and session replay capture. Authenticated product
 * events retain their API path. Identity persists in first-party localStorage. Bounded attribution
 * tokens expire in browser storage after 24 hours; URLs are reduced to route templates.
 */
import type { PostHog, CaptureResult } from "posthog-js/dist/module.no-external";
import { apiRouteTemplate, observeApiRequests, safeExceptionMessage, type ErrorDiagnostics } from "./lib/telemetryDiagnostics";
import { applicationStylesheet, replayClasses, replayStylesheet, replayText, safeReplayLabel } from "./lib/replayPrivacy";
import { afterPageLoad } from "./lib/afterPageLoad";

let client: PostHog | undefined;
let loading: Promise<void> | undefined;
let account: string | null = null;
let authKnown = false;
const tokenPattern = /^[A-Za-z0-9_./:{}@+-]{1,160}$/;
const campaignPattern = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const labelPattern = /^[A-Za-z0-9 ._-]{1,40}$/;
const pathPattern = /^\/[a-z/:_-]{0,80}$/;
const staticPaths = new Set([
  "/", "/library", "/samples", "/login", "/signup", "/reset-password", "/account", "/credits", "/backoffice",
  "/legal/terms", "/legal/privacy", "/legal/acceptable-use",
  "/es", "/fr", "/how-it-works", "/pricing", "/about", "/guides/turn-a-novel-into-a-comic", "/examples/kaitlin-out-of-space",
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
const replayTags = new Set("html head body title style div span p main section article aside header footer nav button a label input textarea select option ul ol li h1 h2 h3 h4 h5 h6 form fieldset legend details summary dialog table thead tbody tr th td br hr link meta".split(" "));
const replayKeys = new Set("id parentId nextId previousId type source x y timeOffset width height scrollTop scrollLeft isChecked positions adds removes texts attributes node childNodes initialOffset isSVG isShadow isShadowHost rootId".split(" "));
const replayAttributes = new Set(["href", "src", "class", "rel", "type", "role", "width", "height", "aria-expanded", "aria-selected", "aria-pressed", "aria-hidden", "disabled", "checked"]);
const replayLabels = new Map<number, string>();

/** Fail closed after rrweb serialization too: input masking alone cannot protect DOM attributes. */
function scrubReplayValue(value: unknown, label?: string): unknown {
  if (value === null || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) return value;
  if (Array.isArray(value)) return value.map(item => scrubReplayValue(item, label));
  if (!value || typeof value !== "object") return undefined;
  const result: Record<string, unknown> = {};
  const object = value as Record<string, unknown>;
  const attributes = object.attributes as Record<string, unknown> | undefined;
  const declaredLabel = attributes && safeReplayLabel(attributes["data-ph-safe-label"]);
  const nodeLabel = declaredLabel ?? (typeof object.id === "number" ? replayLabels.get(object.id) : undefined) ?? label;
  if (typeof object.id === "number" && nodeLabel && replayLabels.size < 20000) replayLabels.set(object.id, nodeLabel);
  if (object.tagName === "style") {
    const css = replayStylesheet(attributes?.["data-vite-dev-id"]);
    return { type: 2, id: object.id, tagName: "style", attributes: {}, childNodes: css ? [{ type: 3, id: (object.childNodes as { id?: number }[] | undefined)?.[0]?.id, textContent: css }] : [] };
  }
  for (const [key, item] of Object.entries(object)) {
    if (key === "tagName") result[key] = typeof item === "string" && replayTags.has(item) ? item : "div";
    else if (key === "textContent" || key === "text" || key === "value") {
      // rrweb input events (source 5) always stay masked, even inside a labelled control.
      if (typeof item === "string") result[key] = replayText(item, object.source === 5 ? undefined : nodeLabel);
    } else if (key === "attributes" && item && typeof item === "object" && !Array.isArray(item)) {
      result[key] = Object.fromEntries(Object.entries(item).filter(([name]) => replayAttributes.has(name))
        .flatMap(([name, content]) => {
          const clean = typeof content === "string" ? maskReplayAttribute(name, content) : null;
          return name === "class" && clean === "[redacted]" ? [] : [[name, clean]];
        }));
    } else if (replayKeys.has(key)) {
      const clean = scrubReplayValue(item, nodeLabel);
      if (clean !== undefined) result[key] = clean;
    }
  }
  // Scripts, media, iframes, and custom-element child content stay blocked.
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
    if (item.type === 2) replayLabels.clear();
    if (item.type === 3 && Array.isArray(payload?.removes)) {
      for (const removed of payload.removes) if (typeof removed?.id === "number") replayLabels.delete(removed.id);
    }
    return [{ type: item.type, ...timestamp, data: scrubReplayValue(payload) ?? {} }];
  });
}

/** Only an explicitly labelled, literal application control can expose text. */
export function maskReplayText(text: string, _element?: HTMLElement | null): string {
  const marker = _element?.closest("[data-ph-safe-label]");
  if (_element?.closest("[data-ph-block], input, textarea, select, [contenteditable]")) return replayText(text);
  return replayText(text, safeReplayLabel(marker?.getAttribute("data-ph-safe-label")));
}

export function maskReplayAttribute(name: string, value: string): string {
  if (name === "data-ph-safe-label") return safeReplayLabel(value) ?? "[redacted]";
  if (name === "data-vite-dev-id") return replayStylesheet(value) ? value : "[redacted]";
  if (name === "href" || name === "src") {
    const stylesheet = name === "href" && applicationStylesheet(value);
    if (stylesheet) return stylesheet;
    try {
      const url = new URL(value, window.location.origin);
      if (url.origin === window.location.origin) return window.location.origin + canonicalPath(url.pathname, account !== null);
    } catch { /* Redact malformed or external destinations. */ }
    return "[redacted]";
  }
  if (name === "class") return replayClasses(value) ?? "[redacted]";
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
      "$snapshot", "$web_vitals", "api_request_completed"].includes(event.event)) return null;
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
    for (const key of ["request_id", "browser_session_id", "job_id", "operation_id", "trace_id", "span_id"]) {
      const value = source[key];
      if (typeof value === "string" && /^(?:[a-f0-9]{32}|[a-f0-9]{16}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/.test(value)) properties[key] = value;
    }
    if (typeof source.route === "string" && /^\/api(?:\/[a-z-]+|\/:id){0,16}$/.test(source.route)
      && source.route === apiRouteTemplate(source.route.slice(4))) properties.route = source.route;
    if (typeof source.method === "string" && ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].includes(source.method)) properties.method = source.method;
    if (typeof source.http_status === "number" && Number.isInteger(source.http_status) && source.http_status >= 100 && source.http_status <= 599) properties.http_status = source.http_status;
    if (typeof source.latency_ms === "number" && Number.isFinite(source.latency_ms) && source.latency_ms >= 0) properties.latency_ms = source.latency_ms;
    if (typeof source.error_code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(source.error_code)) properties.error_code = source.error_code;
    if (source.outcome === "succeeded" || source.outcome === "failed") properties.outcome = source.outcome;
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
    if (event.event === "$web_vitals") {
      // Entries/attribution can expose manuscript text, private image URLs or
      // DOM selectors. Retain numeric measurements only.
      let measurements = 0;
      for (const metric of ["LCP", "INP", "CLS", "FCP"] as const) {
        const key = `$web_vitals_${metric}_value`;
        const value = source[key];
        if (typeof value !== "number" || !Number.isFinite(value) || value < 0) continue;
        properties[key] = value;
        measurements++;
      }
      if (!measurements) return null;
      // Measurements can flush after navigation: preserve their sanitized URL.
      if (typeof source.$current_url === "string") {
        const url = canonicalUrl(source.$current_url);
        properties.$current_url = url;
        properties.$pathname = new URL(url).pathname;
      }
    }
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
          value: safeExceptionMessage(item.value, properties.error_code, item.type),
          stacktrace: { frames: (stack?.frames ?? []).slice(-40).map(frame => {
            const clean: Record<string, unknown> = {};
            for (const key of ["lineno", "colno", "in_app", "platform"]) clean[key] = frame[key];
            // Retain deployed asset path/chunk IDs for source maps, never queries or external URLs.
            if (typeof frame.filename === "string") {
              const url = new URL(frame.filename, window.location.origin);
              if (url.origin === window.location.origin && (/^\/assets\/[A-Za-z0-9_.-]+\.js$/.test(url.pathname)
                || /^\/src\/[A-Za-z0-9_/-]+\.(?:tsx?|jsx?)$/.test(url.pathname))) clean.filename = url.pathname;
            }
            for (const key of ["function", "module", "chunk_id"]) {
              if (typeof frame[key] === "string" && tokenPattern.test(frame[key])) clean[key] = frame[key];
            }
            return clean;
          }) },
        };
      });
      properties.$exception_message = safeExceptionMessage(source.$exception_message, properties.error_code);
    }
    return { event: event.event, uuid: event.uuid, timestamp: event.timestamp, properties };
  } catch {
    return null;
  }
}

export function setTelemetryUser(userId: string | null): void {
  if (authKnown && account === userId) return;
  authKnown = true;
  const previous = account;
  account = userId;
  if (!client) return;
  // Merge the persistent visit on sign-in; reset the device on account changes
  // so the next account cannot inherit the previous account's visits.
  if (previous || (client.get_property("$user_state") === "identified" && client.get_distinct_id() !== userId)) client.reset(true);
  if (userId) client.identify(userId);
}

export function initTelemetry(): Promise<void> {
  if (loading) return loading;
  const key = import.meta.env.VITE_POSTHOG_PROJECT_TOKEN;
  const host = import.meta.env.VITE_POSTHOG_HOST;
  if (!key || !["https://us.i.posthog.com", "https://eu.i.posthog.com"].includes(host)) return Promise.resolve();
  loading = (async () => {
    await new Promise<void>(resolve => { afterPageLoad(resolve); });
    // The no-external build never fetches scripts; bundle the replay recorder.
    const [, , , { default: posthog }] = await Promise.all([
      import("posthog-js/dist/exception-autocapture"),
      import("posthog-js/dist/posthog-recorder"),
      import("posthog-js/dist/web-vitals"),
      import("posthog-js/dist/module.no-external"),
    ]);
    let persistentIdentity = false;
    try {
      const probeKey = "canary:telemetry-storage-test";
      window.localStorage.setItem(probeKey, "1");
      persistentIdentity = window.localStorage.getItem(probeKey) === "1";
      window.localStorage.removeItem(probeKey);
    } catch { /* Use memory without anonymous merging when storage is denied. */ }
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
        // Load only our scrubbed build stylesheet links in the replay player.
        inlineStylesheet: false,
      },
      capture_pageview: false,
      capture_pageleave: false,
      capture_performance: { web_vitals: true, web_vitals_attribution: false, network_timing: false },
      disable_surveys: true,
      enable_heatmaps: false,
      capture_dead_clicks: false,
      capture_exceptions: { capture_unhandled_errors: true, capture_unhandled_rejections: true, capture_console_errors: false },
      person_profiles: "identified_only",
      persistence: persistentIdentity ? "localStorage" : "memory",
      reuseAnonymousId: !persistentIdentity,
      save_referrer: false,
      save_campaign_params: false,
      get_current_url: () => canonicalUrl(window.location.href),
      disable_capture_url_hashes: true,
      ip: false,
      before_send: scrubEvent,
    });
    client = posthog;
    observeApiRequests(properties => posthog.capture("api_request_completed", properties), () => posthog.get_session_id());
    if (authKnown && posthog.get_property("$user_state") === "identified" && posthog.get_distinct_id() !== account) posthog.reset(true);
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
  const value = error as { status?: number; code?: string; diagnostics?: ErrorDiagnostics; name?: string } | null;
  const properties = { ...value?.diagnostics, http_status: value?.status ?? value?.diagnostics?.http_status,
    error_code: value?.code ?? (value?.name === "InsufficientCreditsError" ? "insufficient_credits" : value?.diagnostics?.error_code) };
  void initTelemetry().then(() => client?.captureException(error, properties));
}
