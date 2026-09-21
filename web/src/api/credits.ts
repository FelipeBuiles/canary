import { apiFetch } from "./client";
import type { CreditBalance, CreditHistoryPage, PricingReference } from "../types/api";

export async function getBalance(): Promise<CreditBalance> {
  return apiFetch<CreditBalance>("/credits/balance");
}

export async function getCreditHistory(offset = 0, limit = 30, project?: string): Promise<CreditHistoryPage> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (project) params.set("project_id", project);
  return apiFetch<CreditHistoryPage>(`/credits/history?${params.toString()}`);
}

export async function getPricingReference(): Promise<PricingReference> {
  return apiFetch<PricingReference>("/credits/pricing-reference");
}
