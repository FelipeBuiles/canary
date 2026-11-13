import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CardGrantOffer } from "../components/CardGrantOffer";
import type { CardGrantStatus } from "../api/cardGrant";

const grant = vi.hoisted(() => ({
  data: undefined as CardGrantStatus | undefined, opening: "available" as "available" | "used" | "off",
  start: vi.fn(), isError: false,
}));
vi.mock("../api/cardGrant", () => ({
  OFFER_QUERY_KEY: ["billing", "offer"],
  useAccountOffer: () => ({ data: grant.data && {
    card_grant: grant.data, free_opening: { status: grant.opening, max_characters: 20000 }, first_purchase_bonus_percent: 0,
  } }),
  useStartCardGrant: () => ({ mutate: grant.start, isPending: false, isError: grant.isError }),
}));

function setup(outcome: string | null = null) {
  return render(<QueryClientProvider client={new QueryClient()}><I18nProvider>
    <CardGrantOffer outcome={outcome} />
  </I18nProvider></QueryClientProvider>);
}
const open: CardGrantStatus = { enabled: true, available: true, claimed: false, credits: 1200, expiry_days: 30 };

beforeEach(() => { grant.data = undefined; grant.opening = "available"; grant.start.mockReset(); grant.isError = false; });

describe("Card grant offer", () => {
  it("shows nothing while the offer is off, unknown, or cannot be earned", () => {
    grant.opening = "off";
    for (const data of [undefined, { enabled: false, available: false, claimed: false },
      { ...open, available: false, reason: "opening_first" as const }, { ...open, available: false, reason: "ended" as const }]) {
      grant.data = data;
      const { container, unmount } = setup();
      expect(container.textContent).toBe("");
      unmount();
    }
  });

  it("says what earns the grant before the free opening is printed", () => {
    grant.data = { ...open, available: false, reason: "opening_first" };
    setup();
    expect(screen.getByText(/Once your free first pages are printed, verify a card here to get 1,200 credits/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Verify a card" })).toBeNull();
  });

  it("states the terms and starts the card check", () => {
    grant.data = open;
    setup("cancelled");
    expect(screen.getByText(/get 1,200 credits\. The card is not charged and not kept\..*expire after 30 days/)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Nothing was charged");
    fireEvent.click(screen.getByRole("button", { name: "Verify a card" }));
    expect(grant.start).toHaveBeenCalledTimes(1);
  });

  it("does not promise credits before the webhook has granted them", () => {
    grant.data = open;
    setup("success");
    expect(screen.getByRole("status").textContent).toContain("If it is new to Scenewright");
    expect(screen.queryByRole("button", { name: "Verify a card" })).toBeNull();
  });

  it("tells a claimed account when its unused credits expire", () => {
    grant.data = { ...open, available: false, claimed: true, expires_at: "2026-12-12T00:00:00+00:00" };
    setup("success");
    expect(screen.getByRole("status").textContent).toContain("Unused ones expire on");
    grant.data = { ...grant.data, expired: true };
    expect(setup().container.textContent).toBe("");
  });
});
