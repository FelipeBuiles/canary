import { apiFetch } from "./client";
import type { CreditBalance, CreditHistoryPage, PricingReference } from "../types/api";

export async function getBalance(): Promise<CreditBalance> {
  return apiFetch<CreditBalance>("/credits/balance");
}

export async function getCreditHistory(offset = 0, limit = 30): Promise<CreditHistoryPage> {
  return apiFetch<CreditHistoryPage>(`/credits/history?offset=${offset}&limit=${limit}`);
}

export async function getPricingReference(): Promise<PricingReference> {
  return apiFetch<PricingReference>("/credits/pricing-reference");
}
