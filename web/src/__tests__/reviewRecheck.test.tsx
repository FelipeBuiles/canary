import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { ApiError } from "../api/errors";

const estimate = vi.fn();
const recheck = vi.fn();
vi.mock("../api/pages", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/pages")>(),
  getReviewRecheckEstimate: (...args: unknown[]) => estimate(...args),
  recheckReviews: (...args: unknown[]) => recheck(...args),
}));

import { ReviewRecheck } from "../components/pages/ReviewRecheck";

function renderNotice() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider><ReviewRecheck project="demo" /></I18nProvider>
    </QueryClientProvider>,
  );
}

describe("ReviewRecheck", () => {
  it("prices the re-check before spending, then runs it once confirmed", async () => {
    estimate.mockResolvedValue({ estimate_credits: 89, reserved_credits: 112, reservation_multiplier: 1.25, confidence: "variable", phases: ["adapt", "plan"] });
    recheck.mockResolvedValue({ status: "current" });
    renderNotice();

    expect(screen.getByRole("region", { name: "Drawing paused" })).toBeTruthy();
    expect(estimate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Re-check script and plan" }));
    const drawer = await screen.findByRole("alertdialog");
    await waitFor(() => expect(within(drawer).getByText(/~89 credits/)).toBeTruthy());
    expect(recheck).not.toHaveBeenCalled();

    fireEvent.click(within(drawer).getByRole("button", { name: "Re-check script and plan" }));
    await waitFor(() => expect(recheck).toHaveBeenCalledWith("demo"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("keeps a review that found a problem visible in the sheet", async () => {
    estimate.mockResolvedValue({ estimate_credits: 89, reserved_credits: 112, reservation_multiplier: 1.25, confidence: "variable", phases: ["adapt", "plan"] });
    recheck.mockRejectedValue(new ApiError(409, "The review found a problem, so drawing stays paused. The escape loses its cause."));
    renderNotice();

    fireEvent.click(screen.getByRole("button", { name: "Re-check script and plan" }));
    const drawer = await screen.findByRole("alertdialog");
    await waitFor(() => expect(within(drawer).getByText(/~89 credits/)).toBeTruthy());
    fireEvent.click(within(drawer).getByRole("button", { name: "Re-check script and plan" }));

    const alert = await within(drawer).findByRole("alert");
    expect(alert.textContent).toContain("The escape loses its cause.");
  });
});
