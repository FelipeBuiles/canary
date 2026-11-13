import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { OFFER_QUERY_KEY, useAccountOffer, useStartCardGrant } from "../api/cardGrant";
import { useI18n } from "../i18n";
import { Button } from "./ui/Button";
import { Surface } from "./ui/Surface";

/** The first-chapter grant on the credits page. Renders nothing where the offer is off or cannot be earned. */
export function CardGrantOffer({ outcome }: { outcome: string | null }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const { data: offer } = useAccountOffer();
  const data = offer?.card_grant;
  const start = useStartCardGrant();
  const refreshed = useRef(false);

  useEffect(() => {
    if (outcome !== "success" || refreshed.current) return;
    refreshed.current = true;
    // The grant arrives by webhook, a moment after Stripe returns the author.
    const ids = [500, 2000, 4000].map((delay) => setTimeout(() => {
      void qc.invalidateQueries({ queryKey: ["credits"] });
      void qc.invalidateQueries({ queryKey: OFFER_QUERY_KEY });
    }, delay));
    return () => ids.forEach(clearTimeout);
  }, [outcome, qc]);

  if (!data?.enabled) return null;
  const credits = (data.credits ?? 0).toLocaleString();

  if (data.claimed) {
    if (data.expired || !data.expires_at) return null;
    return (
      <Surface tone="pulp" shadow="none" padding="md" className="mb-8" role="status">
        <p className="font-body text-sm font-semibold text-ink-black">
          {t("Your first-chapter credits are in your balance. Unused ones expire on {date}.", {
            date: new Date(data.expires_at).toLocaleDateString(),
          })}
        </p>
      </Surface>
    );
  }

  if (outcome === "success") {
    return (
      <Surface tone="pulp" shadow="none" padding="md" className="mb-8" role="status">
        <p className="font-body text-sm font-semibold text-ink-black">
          {t("Card verified. If it is new to Scenewright, your credits appear here shortly.")}
        </p>
      </Surface>
    );
  }

  if (!data.available) {
    // Not yet earned: say what earns it, while the free opening can still be had.
    if (data.reason !== "opening_first" || !offer || offer.free_opening.status === "off") return null;
    return (
      <Surface tone="pulp" shadow="none" padding="md" className="mb-8">
        <h2 className="font-display text-xl font-black tracking-tight text-ink-black">
          {t("Credits for a first chapter, after your opening")}
        </h2>
        <p className="mt-2 max-w-[44rem] font-body text-sm leading-6 text-ink-muted">
          {t("Once your free first pages are printed, verify a card here to get {credits} credits for a first chapter. The card is not charged. One per person and card; unused credits expire after {days} days.", {
            credits, days: data.expiry_days ?? 30,
          })}
        </p>
      </Surface>
    );
  }
  return (
    <Surface tone="pulp" shadow="paper" padding="md" className="mb-8">
      <h2 className="font-display text-xl font-black tracking-tight text-ink-black">
        {t("Your first chapter is on us")}
      </h2>
      <p className="mt-2 max-w-[44rem] font-body text-sm leading-6 text-ink-black">
        {t("Verify a card and get {credits} credits. The card is not charged and not kept. One grant per card; unused credits expire after {days} days.", {
          credits, days: data.expiry_days ?? 30,
        })}
      </p>
      <Button size="sm" className="mt-4" disabled={start.isPending} onClick={() => start.mutate()}>
        {t("Verify a card")}
      </Button>
      {start.isError && (
        <p role="alert" className="mt-3 font-body text-sm text-hero-red">
          {t("The card check could not be opened. Please try again.")}
        </p>
      )}
      {outcome === "cancelled" && (
        <p role="status" className="mt-3 font-body text-sm text-ink-muted">
          {t("The card check was cancelled. Nothing was charged.")}
        </p>
      )}
    </Surface>
  );
}
