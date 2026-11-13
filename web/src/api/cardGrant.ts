import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

/** The card-verified first-chapter grant. */
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

/** The account's free opening, before any upload. `available` can still be refused per upload. */
export interface FreeOpeningStatus {
  status: "available" | "used" | "off";
  max_characters?: number;
}

/** The free offer as it stands for this account, as `GET /billing/offer` reports it. */
export interface AccountOffer {
  free_opening: FreeOpeningStatus;
  card_grant: CardGrantStatus;
  /** Set only while the next purchase would earn the bonus. */
  first_purchase_bonus_percent: number;
}

export const OFFER_QUERY_KEY = ["billing", "offer"] as const;

export function useAccountOffer() {
  return useQuery({
    queryKey: OFFER_QUERY_KEY,
    queryFn: () => apiFetch<AccountOffer>("/billing/offer"),
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

/** Characters as words for a reader, rounded down to a round figure (about six characters a word). */
export function approximateWords(characters: number): number {
  const words = characters / 6;
  return words >= 1000 ? Math.floor(words / 500) * 500 : Math.floor(words / 100) * 100;
}
