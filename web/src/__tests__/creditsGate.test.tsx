import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StageCostEstimate, StageInfo } from "../types/api";
import { I18nProvider } from "../i18n";

const run = vi.fn();
const buy = vi.fn();
const reloadEstimate = vi.fn();
let balance: number;
let estimate: StageCostEstimate | undefined;
let estimateError: boolean;
let estimateFetching: boolean;
let stageInfo: Partial<StageInfo>;
let checkoutError: Error | null;

vi.mock("../api/queries", () => ({
  useCreditBalance: () => ({ data: { balance_credits: balance }, isError: false }),
  useProjectStatus: () => ({ data: { stages: { extract: stageInfo } } }),
  useStageEstimate: () => ({ data: estimate, isError: estimateError, isFetching: estimateFetching, refetch: reloadEstimate }),
}));
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: run, isPending: false }) }));
vi.mock("../lib/creditsPurchase", () => ({
  useRecommendedPackage: () => ({ pkg: { id: "pack", credits: 100, price_cents: 500 }, isLoading: false }),
  useBuyCredits: () => ({ mutate: buy, isPending: false, error: checkoutError }),
  packageMeetsShortfall: (pkg: { credits: number }, shortfall: number) => pkg.credits >= shortfall,
}));

import { StagePlaceholder } from "../components/composites/StagePlaceholder";

function tree() {
  return <I18nProvider><StagePlaceholder project="demo" stage="extract" status={stageInfo.status ?? "pending"} allowPendingStart /></I18nProvider>;
}

beforeEach(() => {
  run.mockReset();
  buy.mockReset();
  reloadEstimate.mockReset();
  balance = 0;
  estimate = { stage: "extract", estimate_credits: 12, reserved_credits: 18, reservation_multiplier: 1.5, confidence: "usually_within_estimate" };
  estimateError = false;
  estimateFetching = false;
  checkoutError = null;
  stageInfo = { status: "failed", error_code: "insufficient_credits", required_credits: 100, balance_credits: 0 };
});

describe("Credit gate consent", () => {
  it("keeps a persisted failure paused after funding and resumes only after current-cost consent", () => {
    const { rerender } = render(tree());
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Resume/ })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: /Buy/ }));
    expect(buy).toHaveBeenCalledWith({ packageId: "pack" });
    expect(run).not.toHaveBeenCalled();

    balance = 18; // Current hold, not the stale persisted requirement of 100.
    rerender(tree());
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByLabelText("about 12 credits")).toBeTruthy();
    expect(within(dialog).getByLabelText("18 credits")).toBeTruthy();
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: /Resume/ }));
    expect(run).toHaveBeenCalledOnce();
    expect(run).toHaveBeenCalledWith("demo", "extract", expect.objectContaining({ rerun: false }));
  });

  it("does not spend when a persisted failure mounts already funded", () => {
    balance = 100;
    render(tree());
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    fireEvent.keyDown(screen.getByRole("alertdialog"), { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(run).not.toHaveBeenCalled();
  });

  it("hands a heuristic gate back to the estimated Start action without starting after funding", () => {
    stageInfo = { status: "pending" };
    const { rerender } = render(tree());
    expect(screen.queryByRole("button", { name: /Resume|Start/ })).toBeNull();
    balance = 12; // An estimate alone does not cover the hold.
    rerender(tree());
    expect(screen.queryByRole("button", { name: /Start/ })).toBeNull();
    balance = 18;
    rerender(tree());
    expect(run).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Resume/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Start/ }));
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByLabelText("about 12 credits")).toBeTruthy();
    expect(within(dialog).getByLabelText("18 credits")).toBeTruthy();
    expect(run).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: /Start/ }));
    expect(run).toHaveBeenCalledOnce();
  });

  it("blocks unknown costs and revokes confirmation when the current hold is no longer funded", () => {
    estimate = undefined;
    balance = 100;
    const { rerender } = render(tree());
    expect(screen.getByRole("button", { name: /Resume/ })).toHaveProperty("disabled", true);
    estimateError = true;
    rerender(tree());
    fireEvent.click(screen.getByRole("button", { name: /Retry estimate/ }));
    expect(reloadEstimate).toHaveBeenCalledOnce();
    expect(run).not.toHaveBeenCalled();

    estimateError = false;
    estimate = { stage: "extract", estimate_credits: 12, reserved_credits: 18, reservation_multiplier: 1.5, confidence: "usually_within_estimate" };
    rerender(tree());
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    balance = 12;
    rerender(tree());
    const confirm = within(screen.getByRole("alertdialog")).getByRole("button", { name: /Starting/ });
    expect(confirm).toHaveProperty("disabled", true);
    fireEvent.click(confirm);
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("keeps checkout and run errors actionable without an implicit retry", () => {
    checkoutError = new Error("Checkout unavailable");
    const { rerender } = render(tree());
    expect(screen.getByRole("alert").textContent).toContain("Checkout unavailable");
    expect(screen.getByRole("link", { name: /billing/ })).toHaveProperty("href", expect.stringContaining("/credits"));
    fireEvent.click(screen.getByRole("button", { name: /Buy/ }));
    expect(buy).toHaveBeenCalledOnce();
    checkoutError = null;
    balance = 18;
    run.mockImplementationOnce((_project, _stage, options) => options.onError(new Error("Source unavailable")));
    rerender(tree());
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: /Resume/ }));
    expect(screen.getByRole("alert").textContent).toContain("Source unavailable");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    balance = 30;
    rerender(tree());
    expect(run).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    expect(run).toHaveBeenCalledOnce();
  });
});
