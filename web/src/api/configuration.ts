import type { OperatorConnection } from "./operator";

export type ConfigEvent = { seq: number; phase: string; kind: string; at: number; error?: string; checks?: Record<string, unknown>; activity?: Record<string, unknown>; deadline?: number };
export type ConfigPlan = { plan_id: string; digest: string; baseline: string; image: string; bundle_sha256: string; changes: Record<string, { before: string; after: string }>; secret_changes: Record<string, string>; checks: Record<string, unknown>; activity: Record<string, unknown>; restart_required: boolean; plan_expires_at: number; authorization_expires_at: number | null; effective_expires_at: number; recovery_verification: string | null };
export type ConfigOperation = { request_id: string; seq?: number; phase: string; error?: string; plan: ConfigPlan | null; receipt: Record<string, unknown> | null };
export type ConfigStatus = { checked_at: number; revision: string; image: string; bundle_sha256: string; loader_sha256: string; observation: { observed_at?: number; source_sha?: string; match: string; stale: boolean }; schema: Record<string, { type: string; description: string; backoffice: string; default?: string }>; values: Record<string, string>; secret_names: string[]; operation: ConfigOperation | null; maintenance_hold: boolean };

export class ConfigError extends Error {
  code: string;
  requestId?: string;
  constructor(code: string, requestId?: string) { super(code); this.code = code; this.requestId = requestId; }
}

export async function configRequest<T>(connection: OperatorConnection, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${connection.baseUrl.trim().replace(/\/+$/, "")}/api/ops/backoffice/config/${path}`, {
    method: body ? "POST" : "GET", headers: { "Content-Type": "application/json", "X-Canary-Ops-Token": connection.token.trim() },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (response.ok) return response.json() as Promise<T>;
  let code = `http_${response.status}`;
  let requestId: string | undefined;
  try {
    const payload = await response.json();
    if (typeof payload.detail?.code === "string") code = payload.detail.code;
    if (typeof payload.detail?.request_id === "string") requestId = payload.detail.request_id;
  } catch { /* A restarting app may return Nginx's fixed maintenance text. */ }
  throw new ConfigError(code, requestId);
}

async function encoded(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let result = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) result += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(result);
}

export async function uploadBundle(connection: OperatorConnection, bundle: File, manifest: File, signature: File): Promise<string> {
  if (bundle.size > 2 * 1024 * 1024 || manifest.size > 4096 || signature.size > 16384) throw new ConfigError("upload_too_large");
  const result = await configRequest<{ bundle_id: string }>(connection, "bundles", {
    bundle: await encoded(bundle), manifest: JSON.parse(await manifest.text()), signature: await encoded(signature),
  });
  return result.bundle_id;
}
