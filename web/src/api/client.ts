import { supabase } from "../lib/supabase";

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
  const { data: { session } } = await supabase.auth.getSession();
  const isFormData = options?.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}),
    ...(options?.headers as Record<string, string> | undefined),
  };
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    const body = await res.text();
    let message = body;
    let detail: unknown = body;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      detail = parsed.detail;
      if (typeof parsed.detail === "string") message = parsed.detail;
    } catch {
      // Keep the raw response body when the server did not return JSON.
    }
    if (res.status === 402) {
      const info = parseInsufficientCredits(detail);
      if (info) throw new InsufficientCreditsError(info);
    }
    throw new Error(`API ${res.status}: ${message}`);
  }
  return res.json();
}
