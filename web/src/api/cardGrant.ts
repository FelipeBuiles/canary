import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

/** The card-verified first-chapter grant, as `GET /billing/card-grant` reports it. */
export interface CardGrantStatus {
  enabled: boolean;
  available: boolean;
  claimed: boolean;
  reason?: "claimed" | "ended" | "seats_taken" | "opening_first" | null;
  credits?: number;
  expiry_days?: number;
  expires_at?: string | null;
  expired?: boolean;
}

export function useCardGrant() {
  return useQuery({
    queryKey: ["billing", "card-grant"],
    queryFn: () => apiFetch<CardGrantStatus>("/billing/card-grant"),
    staleTime: 60_000,
    retry: false,
  });
}

export function useStartCardGrant() {
  return useMutation({
    mutationFn: () => apiFetch<{ url: string }>("/billing/card-grant/checkout", { method: "POST" }),
    onSuccess: ({ url }) => {
      window.location.href = url;
    },
  });
}
