import { apiFetch } from "./client";
import type { CreditBalance, CreditTransaction } from "../types/api";

export async function getBalance(): Promise<CreditBalance> {
  return apiFetch<CreditBalance>("/credits/balance");
}

export async function getCreditHistory(): Promise<{ transactions: CreditTransaction[] }> {
  return apiFetch<{ transactions: CreditTransaction[] }>("/credits/history");
}
