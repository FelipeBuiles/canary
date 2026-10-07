import type { ErrorDiagnostics } from "../lib/telemetryDiagnostics";

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
 * branch on it. The message is readable UI copy; status and code remain
 * available to retry policies and diagnostics.
 */
export class ApiError extends Error {
  diagnostics?: ErrorDiagnostics;
  readonly status: number;
  readonly code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

