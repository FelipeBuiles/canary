import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { useInsufficientCreditsStore } from "../store/insufficientCredits";

let balance = 10;
const checkout = vi.fn();
vi.mock("../api/billing", () => ({ createCheckout: (...args: unknown[]) => checkout(...args) }));
vi.mock("../api/queries", () => ({
  useCreditBalance: () => ({ data: { balance_credits: balance } }),
  useCreditPackages: () => ({ data: { packages: [{ id: "small", credits: 100, price_cents: 1000 }] } }),
}));
import { InsufficientCreditsDialog } from "../components/InsufficientCreditsDialog";

function openDialog(retry: () => void) {
  useInsufficientCreditsStore.getState().show({
    actionLabel: "Draw page 4", onRetry: retry,
    info: { balance_credits: 10, required_credits: 50, shortfall_credits: 40, stage: "draw", action: "draw_page", message: "Insufficient credits" },
  });
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  const tree = <QueryClientProvider client={client}><I18nProvider><InsufficientCreditsDialog /></I18nProvider></QueryClientProvider>;
  const view = render(tree);
  return { ...view, refresh: () => view.rerender(<QueryClientProvider client={client}><I18nProvider><InsufficientCreditsDialog /></I18nProvider></QueryClientProvider>) };
}

beforeEach(() => {
  balance = 10;
  checkout.mockReset();
  useInsufficientCreditsStore.getState().close();
});

afterEach(() => {
  useInsufficientCreditsStore.getState().close();
  vi.restoreAllMocks();
});

describe("credit recovery consent", () => {
  it("keeps the named action paused after a topup until Resume is deliberately selected", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    const view = openDialog(retry);
    expect((screen.getByRole("button", { name: "Waiting for credits…" }) as HTMLButtonElement).disabled).toBe(true);
    balance = 100;
    act(() => view.refresh());
    expect(retry).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Resume Draw page 4" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("keeps the pending action and offers a recoverable checkout link when a popup is blocked", async () => {
    const user = userEvent.setup();
    checkout.mockResolvedValue({ url: "https://checkout.stripe.com/example" });
    vi.spyOn(window, "open").mockReturnValue(null);
    const retry = vi.fn();
    openDialog(retry);
    await user.click(screen.getByRole("button", { name: /100 credits.*Covers shortfall/i }));
    const link = await screen.findByRole("link", { name: "Open secure checkout" });
    expect(link.getAttribute("href")).toBe("https://checkout.stripe.com/example");
    expect(retry).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    vi.restoreAllMocks();
  });

  it("surfaces checkout failure without discarding the shortfall or pending action", async () => {
    const user = userEvent.setup();
    checkout.mockRejectedValue(new Error("Checkout unavailable"));
    const retry = vi.fn();
    openDialog(retry);
    await user.click(screen.getByRole("button", { name: /100 credits.*Covers shortfall/i }));
    expect((await screen.findByRole("alert")).textContent).toContain("Checkout unavailable");
    expect(screen.getByRole("heading", { name: "Draw page 4 needs more credits" })).toBeTruthy();
    expect(retry).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /View billing/ }).getAttribute("target")).toBe("_blank");
  });
});
