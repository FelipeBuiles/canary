import { supabase } from "../lib/supabase";
import { accountEpoch, assertAccountEpoch, trackAccountRequest } from "../lib/accountEpoch";
import { pendingAction } from "./paidAction";
import { isCastReviewBlocker } from "../lib/castCheckpoint";
import { beginApiObservation, finishApiObservation, type ErrorDiagnostics } from "../lib/telemetryDiagnostics";

const BASE = "/api";

export interface InsufficientCreditsInfo {
  balance_credits: number;
  required_credits: number;
  shortfall_credits: number;
  stage: string | null;
  action: string | null;
  message: string;
}

export class InsufficientCreditsError extends Error {
  diagnostics?: ErrorDiagnostics;
  readonly insufficientCredits: InsufficientCreditsInfo;
  constructor(info: InsufficientCreditsInfo) {
    super(info.message);
    this.name = "InsufficientCreditsError";
    this.insufficientCredits = info;
  }
}

export function isInsufficientCreditsError(err: unknown): err is InsufficientCreditsError {
  return err instanceof InsufficientCreditsError;
}

/**
 * A non-2xx response, carrying the status so callers and the retry policy can
 * branch on it. The message keeps the historic `API <status>: <detail>` shape
 * because existing callers match on it.
 */
export class ApiError extends Error {
  diagnostics?: ErrorDiagnostics;
  readonly status: number;
  readonly code?: string;
  constructor(status: number, message: string, code?: string) {
    super(`API ${status}: ${message}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** A missing artifact is the normal pre-stage state, not a failure to retry. */
export function isNotFoundError(err: unknown): boolean {
  if (err instanceof ApiError) return err.status === 404;
  return err instanceof Error && err.message.startsWith("API 404:");
}

/** The request got no response: the connection or the server is down. */
export function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError
    && (err as { diagnostics?: ErrorDiagnostics }).diagnostics?.error_code === "network_error";
}

function parseInsufficientCredits(detail: unknown): InsufficientCreditsInfo | null {
  if (!detail || typeof detail !== "object") return null;
  const d = detail as Record<string, unknown>;
  if (d.error !== "insufficient_credits") return null;
  return {
    balance_credits: typeof d.balance_credits === "number" ? d.balance_credits : 0,
    required_credits: typeof d.required_credits === "number" ? d.required_credits : 0,
    shortfall_credits: typeof d.shortfall_credits === "number" ? d.shortfall_credits : 0,
    stage: typeof d.stage === "string" ? d.stage : null,
    action: typeof d.action === "string" ? d.action : null,
    message: typeof d.message === "string" ? d.message : "Insufficient credits",
  };
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const epoch = accountEpoch();
  const { data: { session } } = await supabase.auth.getSession();
  assertAccountEpoch(epoch);
  const method = options?.method?.toUpperCase() ?? "GET";
  // Provider-free Finish checks are safe to recompute after an interruption.
  // Do not retain a paid-action receipt that would block an explicit retry.
  const isFinishCheck = method === "POST" && /^\/projects\/[^/]+(?:\/parts\/[^/]+)?\/export\/preflight(?:\?|$)/.test(path);
  let isCachedPageCheck = false;
  if (method === "POST" && /^\/projects\/[^/]+(?:\/parts\/[^/]+)?\/pages\/checks\/recover(?:\?|$)/.test(path)
    && typeof options?.body === "string") {
    try { isCachedPageCheck = JSON.parse(options.body)?.allow_paid === false; } catch { /* Server validates malformed bodies. */ }
  }
  const action = session && !isFinishCheck && !isCachedPageCheck && !["GET", "HEAD", "OPTIONS"].includes(method) && path.startsWith("/projects/")
    ? await pendingAction(session.user.id, method, path, options?.body)
    : null;
  assertAccountEpoch(epoch);
  const controller = new AbortController();
  const untrack = trackAccountRequest(controller);
  const isFormData = options?.body instanceof FormData;
  const observation = beginApiObservation(path, method);
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}),
    ...(options?.headers as Record<string, string> | undefined),
    ...(action ? { "Idempotency-Key": action.key } : {}),
    "X-Request-ID": observation.request_id,
    traceparent: observation.traceparent,
    ...(observation.browser_session_id ? { "X-Canary-Session-ID": observation.browser_session_id } : {}),
  };
  let response: Response | undefined;
  try {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    signal: options?.signal ? AbortSignal.any([options.signal, controller.signal]) : controller.signal,
    headers,
  });
  response = res;
  assertAccountEpoch(epoch);
  if (!res.ok) {
    const body = await res.text();
    assertAccountEpoch(epoch);
    // Unknown 409s may be indeterminate; keep their receipts. Other 4xx
    // responses rejected the action.
    if (res.status < 500 && res.status !== 409) action?.complete();
    let message = body;
    let detail: unknown = body;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      detail = parsed.detail;
      if (typeof parsed.detail === "string") message = parsed.detail;
      if (parsed.detail && typeof parsed.detail === "object") {
        const detailMessage = (parsed.detail as { message?: unknown }).message;
        if (typeof detailMessage === "string") message = detailMessage;
      }
    } catch {
      // Keep the raw response body when the server did not return JSON.
    }
    // Adapt's approval gate runs before job creation or provider submission.
    // Release this definite rejection, including a replay saved before the
    // user approved the brief. A subsequent explicit click is a new action.
    // Do not generalize this to other conflicts: they may follow side effects.
    if (res.status === 409 && method === "POST"
      && /^\/projects\/[^/]+(?:\/parts\/[^/]+)?\/run(?:\?|$)/.test(path)
      && detail === "Adapt requires an approved adaptation brief") {
      action?.complete();
    }
    // Cast readiness gates precede approval and job dispatch. A corrected
    // prerequisite is a new explicit action, including an older saved 409.
    const isCastApproval = method === "POST" && /^\/projects\/[^/]+(?:\/parts\/[^/]+)?\/approve\/cast$/.test(path);
    const castRejected = (typeof detail === "object" && detail !== null
      && (detail as { code?: unknown }).code === "cast_approval_rejected")
      || (typeof detail === "string" && isCastReviewBlocker(detail));
    if (res.status === 409 && isCastApproval && castRejected) action?.complete();
    if (res.status === 402) {
      const info = parseInsufficientCredits(detail);
      if (info) throw new InsufficientCreditsError(info);
    }
    // Draw preflight precedes edition creation, holds, and job dispatch.
    // Recognize the exact historical rejection too, so saved receipts recover.
    // Unknown conflicts still retain their keys to prevent duplicate submissions.
    const isDrawStart = /^\/projects\/[^/]+(?:\/parts\/[^/]+)?\/run(?:\?|$)/.test(path)
      && new URLSearchParams(path.split("?")[1]).get("stage") === "draw";
    const definiteDrawRejection = typeof detail === "object" && detail !== null
      && (detail as { code?: unknown }).code === "draw_preflight_rejected";
    const legacyDrawOverflow = typeof detail === "string"
      && /^Page \d+ requires \d+ approved references, but this edition supports \d+\. Replan this page before drawing; identity references will not be silently dropped\.$/.test(detail);
    if (res.status === 409 && method === "POST" && isDrawStart
      && (definiteDrawRejection || legacyDrawOverflow)) {
      action?.complete();
    }
    const code = typeof detail === "object" && detail !== null
      && typeof (detail as { code?: unknown }).code === "string"
      ? (detail as { code: string }).code : undefined;
    throw new ApiError(res.status, message, code);
  }
  const result = await res.json();
  assertAccountEpoch(epoch);
  action?.complete();
  finishApiObservation(observation, res, undefined, result && typeof result === "object" ? {
    job_id: result.job_id, operation_id: result.operation_id,
  } : {});
  return result;
  } catch (error) {
    if (epoch === accountEpoch() && !controller.signal.aborted && !options?.signal?.aborted) {
      const code = error instanceof InsufficientCreditsError ? "insufficient_credits"
        : error instanceof ApiError ? error.code : !response ? "network_error" : undefined;
      const diagnostics = finishApiObservation(observation, response, code, { failed: true });
      if (error instanceof Error) {
        try { Object.assign(error, { diagnostics }); } catch { /* Frozen external errors. */ }
      }
    }
    throw error;
  } finally {
    untrack();
  }
}
