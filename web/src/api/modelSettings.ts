import { apiFetch } from "./client";

export interface AccountModelSettings {
  enabled: boolean;
  funding?: string;
  codex_enabled?: boolean;
  warnings?: string[];
  funding_groups?: Array<{ stages: string[]; label: string }>;
  selections: Record<string, string>;
  stages: Array<{ id: string; label: string; model_ids: string[] }>;
  models: Array<{ id: string; label: string; kind: "text" | "image"; provider: string; vision: boolean; funding?: "api" | "codex_subscription"; available?: boolean; description?: string }>;
}

export function getAccountModelSettings() {
  return apiFetch<AccountModelSettings>("/account/model-settings");
}

export function updateAccountModelSettings(selections: Record<string, string>) {
  return apiFetch<AccountModelSettings>("/account/model-settings", {
    method: "PATCH",
    body: JSON.stringify({ selections }),
  });
}
