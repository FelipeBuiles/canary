import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CreditsPage } from "../pages/CreditsPage";

const mocks = vi.hoisted(() => ({
  balanceError: false,
  historyError: false,
  packagesError: false,
  refetchBalance: vi.fn(),
  refetchHistory: vi.fn(),
  refetchPackages: vi.fn(),
  checkout: vi.fn(),
}));

vi.mock("../api/queries", () => ({
  useCreditBalance: () => ({
    data: mocks.balanceError ? undefined : { balance_credits: 1847 },
    isLoading: false,
    isError: mocks.balanceError,
    refetch: mocks.refetchBalance,
  }),
  useCreditHistory: () => ({
    data: mocks.historyError ? undefined : { pages: [{ runs: [], month_used_credits: 153 }] },
    isLoading: false,
    isError: mocks.historyError,
    refetch: mocks.refetchHistory,
    hasNextPage: false,
  }),
  useCreditPackages: () => ({
    data: mocks.packagesError ? undefined : {
      packages: [
        { id: "actual-small-pack", credits: 1200, price_cents: 1900 },
        { id: "actual-large-pack", credits: 3000, price_cents: 4500 },
      ],
    },
    isLoading: false,
    isError: mocks.packagesError,
    refetch: mocks.refetchPackages,
  }),
  usePricingReference: () => ({ data: { notes: ["Credit holds settle after work completes."] } }),
  useProjects: () => ({ data: [] }),
  useCreateCheckout: () => ({ mutate: mocks.checkout, isPending: false, isError: false }),
}));

vi.mock("../api/events", () => ({ trackProductEvent: vi.fn() }));

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider>
        <MemoryRouter initialEntries={["/credits"]}>
          <CreditsPage />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.balanceError = false;
  mocks.historyError = false;
  mocks.packagesError = false;
  localStorage.clear();
});

describe("credits page data and recovery", () => {
  it("shows the actual balance, monthly use, pack credits and prices", () => {
    renderPage();
    expect(screen.getByLabelText("1,847 credits")).toBeTruthy();
    expect(screen.getByLabelText("153 credits")).toBeTruthy();
    expect(screen.getByLabelText("1,200 credits")).toBeTruthy();
    expect(screen.getByLabelText("3,000 credits")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Buy $19" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Buy $45" })).toBeTruthy();
  });

  it("does not disguise a failed balance query as zero credits", () => {
    mocks.balanceError = true;
    renderPage();
    expect(screen.getByText("Balance unavailable.")).toBeTruthy();
    expect(screen.queryByLabelText("0 credits")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry balance" }));
    expect(mocks.refetchBalance).toHaveBeenCalledOnce();
    expect(mocks.checkout).not.toHaveBeenCalled();
  });

  it("does not disguise failed history as no transactions or zero monthly use", () => {
    mocks.historyError = true;
    renderPage();
    expect(screen.getByText(/Credit history could not be refreshed/)).toBeTruthy();
    expect(screen.queryByText(/No transactions yet/)).toBeNull();
    expect(screen.queryByLabelText("0 credits")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry history" }));
    expect(mocks.refetchHistory).toHaveBeenCalledOnce();
    expect(mocks.checkout).not.toHaveBeenCalled();
  });

  it("offers read-only recovery when pack prices cannot be loaded", () => {
    mocks.packagesError = true;
    renderPage();
    expect(screen.getByText("Credit packs could not be loaded.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Buy/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry credit packs" }));
    expect(mocks.refetchPackages).toHaveBeenCalledOnce();
    expect(mocks.checkout).not.toHaveBeenCalled();
  });

  it("passes the chosen pack's real ID to checkout only after a buy action", () => {
    renderPage();
    expect(mocks.checkout).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Buy $45" }));
    expect(mocks.checkout).toHaveBeenCalledExactlyOnceWith({ packageId: "actual-large-pack" });
  });
});
