import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { FreeOpeningBanner } from "../components/FreeOpeningBanner";
import type { FreeOpeningStatus } from "../api/cardGrant";

const offer = vi.hoisted(() => ({ opening: undefined as FreeOpeningStatus | undefined }));
vi.mock("../api/cardGrant", async (original) => ({
  ...(await original<typeof import("../api/cardGrant")>()),
  useAccountOffer: () => ({ data: offer.opening && {
    free_opening: offer.opening, first_purchase_bonus_percent: 0,
    card_grant: { enabled: false, available: false, claimed: false },
  } }),
}));

const view = () => render(<I18nProvider><FreeOpeningBanner /></I18nProvider>);

beforeEach(() => { offer.opening = undefined; localStorage.clear(); });

describe("Free opening banner", () => {
  it("tells a new account its opening is free, with the length in words", () => {
    offer.opening = { status: "available", max_characters: 20000 };
    view();
    expect(screen.getByRole("heading", { name: "Your opening is on us" })).toBeTruthy();
    expect(screen.getByText(/up to about 3,000 words/)).toBeTruthy();
  });

  it("stays away once used, while off, and after it is dismissed", () => {
    for (const opening of [undefined, { status: "used" as const, max_characters: 20000 }, { status: "off" as const }]) {
      offer.opening = opening;
      const { container, unmount } = view();
      expect(container.textContent).toBe("");
      unmount();
    }
    offer.opening = { status: "available", max_characters: 20000 };
    const { unmount } = view();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("heading")).toBeNull();
    unmount();
    const { container } = view();
    expect(container.textContent).toBe("");
  });
});
