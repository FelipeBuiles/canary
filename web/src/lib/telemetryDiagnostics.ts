/** Bounded diagnostics shared by the API client and telemetry, without payloads. */
export interface ApiObservation {
  request_id: string;
  trace_id: string;
  traceparent: string;
  route: string;
  method: string;
  started: number;
  browser_session_id?: string;
}

export type ErrorDiagnostics = Partial<Pick<ApiObservation, "request_id" | "trace_id" | "route" | "method" | "browser_session_id">> & {
  http_status?: number;
  latency_ms?: number;
  error_code?: string;
  job_id?: string;
  operation_id?: string;
  outcome?: "succeeded" | "failed";
};

const apiSegments = new Set("projects parts pages renders revisions checks recover run approve status events account feedback styles cast assets entities states references jobs operations export preflight download billing credits checkout portal lettering translations story-bible brief extraction adaptation plan draw finish source text select active correct redraw regenerate cancel retry history presets models settings usage labs image-comparison experiments variants health version bootstrap consent issues resolve accept dismiss".split(" "));
export const diagnosticMessages: Record<string, string> = {
  insufficient_credits: "Insufficient credits",
  cast_approval_rejected: "Cast approval prerequisites were not met",
  draw_preflight_rejected: "Draw preflight prerequisites were not met",
  network_error: "API connection failed",
};

export function apiRouteTemplate(path: string): string {
  const pathname = path.split(/[?#]/, 1)[0];
  if (!pathname.startsWith("/") || pathname.startsWith("//")) return "/api/other";
  return "/api" + pathname.split("/").slice(0, 16).map(segment =>
    segment === "" || apiSegments.has(segment) ? segment : ":id").join("/");
}

export function safeExceptionMessage(value: unknown, code?: unknown, type?: unknown): string {
  if (typeof code === "string" && Object.hasOwn(diagnosticMessages, code)) return diagnosticMessages[code];
  if (typeof value === "string") {
    if (["Failed to fetch", "Load failed", "NetworkError when attempting to fetch resource."].includes(value)) return "API connection failed";
    if (/^Cannot read propert(?:y|ies) of (?:undefined|null)/.test(value)) return "Cannot read a property of a missing value";
    if (value === "ResizeObserver loop completed with undelivered notifications.") return value;
  }
  if (type === "AbortError") return "Operation aborted";
  if (type === "ChunkLoadError") return "Application bundle failed to load";
  return "[redacted]";
}

let observer: ((properties: ErrorDiagnostics) => void) | undefined;
let sessionId: (() => string | undefined) | undefined;
export function observeApiRequests(callback: (properties: ErrorDiagnostics) => void, getSessionId: () => string | undefined): void {
  observer = callback;
  sessionId = getSessionId;
}

export function beginApiObservation(path: string, method: string): ApiObservation {
  const request_id = crypto.randomUUID();
  const trace_id = crypto.randomUUID().replaceAll("-", "");
  const span = crypto.randomUUID().replaceAll("-", "").slice(0, 16);
  let browser_session_id: string | undefined;
  try { browser_session_id = sessionId?.(); } catch { /* Optional recorder. */ }
  return { request_id, trace_id, traceparent: `00-${trace_id}-${span}-01`,
    route: apiRouteTemplate(path), method, started: performance.now(), browser_session_id };
}

export function finishApiObservation(request: ApiObservation, response?: Response, code?: string,
  result: { failed?: boolean; job_id?: unknown; operation_id?: unknown } = {}): ErrorDiagnostics {
  const opaqueId = (value: unknown) => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value) ? value : undefined;
  const diagnostics: ErrorDiagnostics = {
    request_id: response?.headers?.get("X-Request-ID") ?? request.request_id,
    trace_id: response?.headers?.get("X-Trace-ID") ?? request.trace_id,
    route: request.route, method: request.method, browser_session_id: request.browser_session_id,
    http_status: response?.status, latency_ms: Math.max(0, Math.round(performance.now() - request.started)),
    error_code: code,
    job_id: opaqueId(result.job_id), operation_id: opaqueId(result.operation_id),
    outcome: result.failed || !response?.ok ? "failed" : "succeeded",
  };
  try { observer?.(diagnostics); } catch { /* Diagnostics never change an API outcome. */ }
  return diagnostics;
}
