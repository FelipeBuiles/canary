import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const estimate = vi.fn();
const generate = vi.fn();
vi.mock("../api/pages", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/pages")>(),
  getCompletePageEstimate: (...args: unknown[]) => estimate(...args),
}));
vi.mock("../api/queries", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/queries")>(),
  useGenerateCompletePage: () => ({ mutate: generate, isPending: false, error: null, reset: vi.fn() }),
}));

import { StaleRenderRedraw } from "../components/pages/StaleRenderRedraw";

describe("StaleRenderRedraw", () => {
  it("explains a re-planned page and draws it fresh only after the estimate is confirmed", async () => {
    estimate.mockResolvedValue({ estimate_credits: 4, reserved_credits: 5, reservation_multiplier: 1.25, confidence: "variable" });
    generate.mockImplementation((_vars, options) => options.onSuccess({ job: { id: "job-16" } }));
    const queued = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider><StaleRenderRedraw project="demo" pageNumber={16} onJobQueued={queued} /></I18nProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("Page re-planned — redraw needed")).toBeTruthy();
    expect(estimate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Redraw page 16" }));
    const drawer = await screen.findByRole("alertdialog");
    await waitFor(() => expect(within(drawer).getByText(/~4 credits/)).toBeTruthy());
    expect(estimate).toHaveBeenCalledWith("demo", 16);
    expect(generate).not.toHaveBeenCalled();

    fireEvent.click(within(drawer).getByRole("button", { name: "Redraw page 16" }));
    expect(generate).toHaveBeenCalledWith({ project: "demo", pageNumber: 16 }, expect.anything());
    expect(queued).toHaveBeenCalledWith("job-16");
  });
});
