import { ApiError, InsufficientCreditsError } from "../api/errors";
import { isAuthError } from "@supabase/supabase-js";
import { isStorageLimitError } from "./storageLimit";

export type ErrorOperation = "load" | "save" | "generate" | "estimate" | "delete" | "approve" | "export" | "preview" | "upload" | "auth";

const operationCopy = {
  load: ["This could not be loaded.", "Try loading this again."],
  save: ["Your changes could not be saved.", "Keep your changes here and try saving again."],
  generate: ["This attempt needs attention.", "Check progress before trying again. An earlier attempt may still be running."],
  estimate: ["The cost could not be loaded.", "Retry the estimate before confirming any work."],
  delete: ["This could not be deleted.", "Check whether it is still listed before trying to delete it again."],
  approve: ["Approval could not be confirmed.", "Check the latest project status before approving again."],
  export: ["The export could not be created.", "Check the available downloads before creating another export."],
  preview: ["The preview could not be created.", "Adjust your changes and try the preview again."],
  upload: ["The upload could not be completed.", "Check whether the upload finished before trying again."],
  auth: ["This account request could not be completed.", "Check your details and try again."],
} as const;

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : typeof error === "string" ? error : "";
}

/** Presentation only: this never submits, retries, or clears a paid action. */
export function describeError(error: unknown, operation: ErrorOperation, storedCode?: string | null) {
  const code = storedCode ?? (error instanceof ApiError ? error.code : undefined);
  const [title, recovery] = operationCopy[operation];
  if (isStorageLimitError(errorMessage(error), code)) return { kind: "storage" as const, title, recovery };
  if (code === "idempotency_indeterminate") return {
    kind: "ordinary" as const,
    title: "Check the earlier attempt",
    recovery: "This action may already have started. Check the project's progress before trying again.",
    uncertain: true,
    specific: true,
  };
  if (error instanceof InsufficientCreditsError) return {
    kind: "ordinary" as const, specific: true, title: "Not enough credits", recovery: "Add credits before continuing.", href: "/credits", linkLabel: "Get credits",
  };
  if (error instanceof ApiError && error.status === 401) return {
    kind: "ordinary" as const, specific: true, title: "Please sign in again", recovery: "Your session has expired. Sign in to continue.", href: "/login", linkLabel: "Sign in",
  };
  if ((error instanceof ApiError || isAuthError(error)) && error.status === 429) return {
    kind: "ordinary" as const, specific: true, title: "Please wait a moment", recovery: "Too many requests arrived at once. Wait a moment before trying again.",
  };
  if (/^(?:Failed to fetch|NetworkError|Network request failed|Load failed|Connection (?:lost|interrupted))/i.test(errorMessage(error))) return {
    kind: "ordinary" as const, specific: true, title: "The connection was interrupted",
    recovery: operation === "generate" || operation === "approve" || operation === "upload"
      ? "Check progress before trying again. An earlier attempt may still be running."
      : "Check your connection and try again.",
  };
  // Expected application rejections often carry the exact correction the
  // author needs. Keep that copy, but never promote a JSON body or traceback.
  const message = errorMessage(error);
  const status = error instanceof ApiError || isAuthError(error) ? error.status : undefined;
  const rejection = status != null && status >= 400 && status < 500
    && message.length <= 600 && !/^\s*(?:[[<{]|API \d+:|Traceback|\w*Error:|Exception:)/.test(message)
    && !/^[a-z][a-z\d]*_[a-z\d_]+$/i.test(message.trim());
  return { kind: "ordinary" as const, title, recovery, message: rejection ? message : undefined };
}

/** Only bounded error text and diagnostic identifiers belong in a support report. */
export function errorDetails(error: unknown, extra?: string | null, storedCode?: string | null): string {
  const lines: Array<string | null | undefined> = [];
  const code = error instanceof ApiError || isAuthError(error) ? error.code : undefined;
  if (storedCode && storedCode !== code) lines.push(storedCode);
  if (error instanceof ApiError || isAuthError(error)) {
    if (error.status != null) lines.push(`HTTP ${error.status}`);
    lines.push(error.code);
  }
  if (error instanceof ApiError) {
    if (error.diagnostics?.request_id) lines.push(`Request: ${error.diagnostics.request_id}`);
    if (error.diagnostics?.trace_id) lines.push(`Trace: ${error.diagnostics.trace_id}`);
  }
  // Preserve report identifiers even when an exception or traceback is long.
  lines.push(errorMessage(error), extra);
  return lines.filter(Boolean).join("\n\n").slice(0, 12_000);
}
