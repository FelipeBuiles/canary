import { apiFetch } from "./client";
import type { CreditPackage } from "../types/api";

export async function getPackages(): Promise<{ packages: CreditPackage[] }> {
  return apiFetch<{ packages: CreditPackage[] }>("/billing/packages");
}

export async function createCheckout(packageId: string): Promise<{ url: string }> {
  return apiFetch<{ url: string }>("/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ package: packageId }),
  });
}
