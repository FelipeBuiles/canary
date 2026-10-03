export type OperatorStripeMode = "sandbox" | "live" | "unconfigured" | "unknown";

export interface OperatorEnvironment {
  app_environment: string;
  stripe_mode: OperatorStripeMode;
  stripe_key_configured: boolean;
  webhook_configured: boolean;
  expected_stripe_mode: "sandbox" | "live";
  mode_matches_app: boolean | null;
  live_money_warning: string;
  safe_for_real_customers: boolean;
  application_version?: string;
  git_sha?: string;
}

export interface OperatorErrorPayload {
  source: string;
  stage: string;
  project_id?: string | null;
  project_name?: string | null;
  status: string;
  message: string;
  error_type?: string;
  occurred_at?: string | null;
}

export interface OperatorJobPayload {
  id: string;
  label: string;
  kind: string;
  status: "queued" | "running" | "complete" | "failed";
  project_id?: string | null;
  queued_at?: string | null;
  started_at?: string | null;
}

export interface OperatorProjectPayload {
  id: string;
  name: string;
  slug: string;
  created_at?: string | null;
  status: "idle" | "running" | "review" | "ready" | "error" | "stalled" | "complete";
  is_active: boolean;
  current_stage: string;
  errors: OperatorErrorPayload[];
  jobs: Array<OperatorJobPayload & { finished_at?: string | null; error?: string | null }>;
}

export interface OperatorUserPayload {
  id: string;
  name: string;
  email: string;
  initials: string;
  avatar_tone: "red" | "gold" | "blue" | "sage" | "ink";
  plan: string;
  status: "active" | "suspended" | "unconfirmed";
  projects: number;
  credits: number;
  last_seen: string;
  last_seen_at?: string | null;
  joined: string;
  joined_at?: string | null;
  current_stage: string;
  active_project?: OperatorProjectPayload | null;
  active_jobs: OperatorJobPayload[];
  errors: OperatorErrorPayload[];
  error_count: number;
  last_error?: OperatorErrorPayload | null;
  last_event: string;
  last_event_at?: string | null;
  spend: number;
  location: string;
  timezone: string;
  tags: string[];
  projects_detail: OperatorProjectPayload[];
  source: "live";
}

export interface OperatorSnapshot {
  environment: OperatorEnvironment;
  users: OperatorUserPayload[];
  overview: {
    user_count: number;
    active_users_30d: number;
    active_users_7d: number;
    project_count: number;
    projects_created_7d: number;
    projects_in_motion: number;
    running_jobs: number;
    queued_jobs: number;
    users_with_errors: number;
    errors_24h: number;
    ai_calls_7d: number;
    failed_ai_calls_7d: number;
    exports_7d: number;
    credits_granted_7d: number;
    credits_used_7d: number;
    provider_cost_usd_7d: number;
  };
  recent_errors: OperatorErrorPayload[];
  projects_in_motion: OperatorProjectPayload[];
  activity: Array<{
    id: string;
    tone: "red" | "gold" | "sage" | "blue" | "ink";
    title: string;
    detail: string;
    occurred_at?: string | null;
  }>;
  model_spend: Array<{ model: string; alias: string; calls: number; spend: number; share: number }>;
  data_as_of: string;
}

export interface OperatorConnection {
  baseUrl: string;
  token: string;
}

export interface OperatorModelSettings {
  reasoning_efforts: Record<string, string>;
  reasoning_options: Record<string, string[]>;
  text_reasoning_effort: string;
  text_reasoning_effort_options: string[];
  selections: Record<string, string>;
  models: Array<{ id: string; label: string; provider: string; kind: "text" | "image" }>;
  stages: Array<{ id: string; label: string; description: string; model_ids: string[] }>;
  note: string;
}

export interface GrantCreditsInput {
  amountCredits: number;
  reason: string;
  operator: string;
}

export interface GrantCreditsResponse {
  status: "granted";
  id: string;
  user_id: string;
  amount_credits: number;
  idempotent: boolean;
  stripe_charge: false;
  environment: OperatorEnvironment;
}

export class OperatorApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "OperatorApiError";
    this.status = status;
  }
}

const BASE_URL_KEY = "scenewright.operator.base-url";
const TOKEN_KEY = "scenewright.operator.token";
const DEFAULT_BASE_URL = (
  import.meta.env.VITE_BACKOFFICE_API_URL
  ?? import.meta.env.VITE_API_BASE_URL
  ?? ""
).trim().replace(/\/+$/, "");
const DEFAULT_TOKEN = (import.meta.env.VITE_BACKOFFICE_OPS_TOKEN ?? "").trim();

function storage(kind: "localStorage" | "sessionStorage"): Storage | null {
  try {
    return window[kind];
  } catch {
    return null;
  }
}

export function readOperatorConnection(): OperatorConnection {
  const baseUrl = storage("localStorage")?.getItem(BASE_URL_KEY)?.trim() || DEFAULT_BASE_URL;
  const token = storage("sessionStorage")?.getItem(TOKEN_KEY)?.trim() || DEFAULT_TOKEN;
  return { baseUrl: baseUrl.replace(/\/+$/, ""), token };
}

export function saveOperatorConnection(connection: OperatorConnection): void {
  storage("localStorage")?.setItem(BASE_URL_KEY, connection.baseUrl.trim().replace(/\/+$/, ""));
  storage("sessionStorage")?.setItem(TOKEN_KEY, connection.token.trim());
}

export function clearOperatorToken(): void {
  storage("sessionStorage")?.removeItem(TOKEN_KEY);
}

function operatorUrl(baseUrl: string, path: string): string {
  return `${baseUrl.trim().replace(/\/+$/, "")}${path}`;
}

export async function operatorFetch<T>(
  path: string,
  connection: OperatorConnection,
  options?: RequestInit,
): Promise<T> {
  const token = connection.token.trim();
  if (!token) {
    throw new OperatorApiError(0, "Enter the operations token to connect.");
  }

  const response = await fetch(operatorUrl(connection.baseUrl, path), {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Canary-Ops-Token": token,
      ...(options?.headers as Record<string, string> | undefined),
    },
  });
  if (response.ok) return response.json() as Promise<T>;

  let message = `Operator API returned ${response.status}.`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    // Keep the status message when the server returned a non-JSON body.
  }
  throw new OperatorApiError(response.status, message);
}

export function fetchOperatorSnapshot(
  connection = readOperatorConnection(),
): Promise<OperatorSnapshot> {
  return operatorFetch<OperatorSnapshot>("/api/ops/backoffice/", connection);
}

export function fetchOperatorModels(connection: OperatorConnection): Promise<OperatorModelSettings> {
  return operatorFetch<OperatorModelSettings>("/api/ops/backoffice/models", connection);
}

export function updateOperatorModels(
  selections: Record<string, string>,
  connection: OperatorConnection,
  reasoningEfforts: Record<string, string> = {},
): Promise<OperatorModelSettings> {
  return operatorFetch<OperatorModelSettings>("/api/ops/backoffice/models", connection, {
    method: "PATCH",
    body: JSON.stringify({ selections, reasoning_efforts: reasoningEfforts }),
  });
}

export function grantOperatorCredits(
  userId: string,
  input: GrantCreditsInput,
  connection = readOperatorConnection(),
): Promise<GrantCreditsResponse> {
  const idempotencyKey = `ui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  return operatorFetch<GrantCreditsResponse>(
    `/api/ops/backoffice/users/${encodeURIComponent(userId)}/credits`,
    connection,
    {
      method: "POST",
      body: JSON.stringify({
        amount_credits: input.amountCredits,
        reason: input.reason,
        operator: input.operator,
        idempotency_key: idempotencyKey,
      }),
    },
  );
}

export function fetchPublications(connection: OperatorConnection) {
  return operatorFetch<import("./publications").Publication[]>("/api/ops/publications", connection);
}

export interface CustomerFeedback {
  id: string;
  user_id: string;
  project_id: string | null;
  category: string;
  message: string;
  status: "new" | "reviewed" | "planned" | "resolved";
  created_at: string;
}
export function fetchFeedback(connection: OperatorConnection) {
  return operatorFetch<{ items: CustomerFeedback[] }>("/api/ops/backoffice/feedback", connection);
}
export function updateFeedback(connection: OperatorConnection, item: CustomerFeedback, status: CustomerFeedback["status"]) {
  return operatorFetch<CustomerFeedback>(`/api/ops/backoffice/feedback/${encodeURIComponent(item.user_id)}/${encodeURIComponent(item.id)}`, connection,
    { method: "PATCH", body: JSON.stringify({ status }) });
}
