import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { ApiError } from "../api/client";
import { PageCheckRecovery } from "../components/pages/PageCheckRecovery";

const api = vi.hoisted(() => ({ recover: vi.fn(), estimate: vi.fn(), preflight: vi.fn() }));
vi.mock("../api/pages", () => ({
  recoverPageChecks: api.recover, getPageCheckEstimate: api.estimate, runFinishPreflight: api.preflight,
}));
const incomplete = { pages: [{ page_number: 1, status: "checked" }, { page_number: 2, status: "requires_ocr" }] };
beforeEach(() => {
  vi.resetAllMocks();
  api.preflight.mockResolvedValue({});
  api.estimate.mockResolvedValue({ paid_pages: 1, estimated_credits: 1, reserved_credits: 1,
    pages: [{ page_number: 2, render_image_sha256: "art-2" }] });
});

it.each([
  new TypeError("Connection lost"),
  new ApiError(409, "This action may have been accepted.", "idempotency_indeterminate"),
])("reconciles partial saved checks after an uncertain paid response: %s", async (error) => {
  api.recover.mockResolvedValueOnce(incomplete).mockRejectedValueOnce(error).mockResolvedValue(incomplete);
  render(<QueryClientProvider client={new QueryClient()}><I18nProvider>
    <PageCheckRecovery project="demo" unchecked={2} />
  </I18nProvider></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Check pages" }));
  fireEvent.click(await screen.findByRole("button", { name: "CHECK PAGES" }));
  await screen.findByText(/The earlier check was interrupted/);
  expect(api.recover.mock.calls).toEqual([
    ["demo", false, {}], ["demo", true, { 2: "art-2" }], ["demo", false, {}],
  ]);
  expect(screen.queryByRole("alertdialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Refresh saved checks" }));
  await waitFor(() => expect(api.recover).toHaveBeenCalledTimes(4));
  expect(api.recover.mock.calls[3]).toEqual(["demo", false, {}]);
  await screen.findByText(/The interrupted check may still be charged/);
  expect(api.estimate).toHaveBeenCalledTimes(2);
  expect(api.recover).toHaveBeenCalledTimes(4);
  api.recover.mockResolvedValue({ pages: [{ page_number: 1, status: "checked" }, { page_number: 2, status: "checked" }] });
  fireEvent.click(screen.getByRole("button", { name: "CHECK PAGES" }));
  await screen.findByText("All pages checked.");
  expect(api.recover.mock.calls[4]).toEqual(["demo", true, { 2: "art-2" }, expect.any(String)]);
  expect(screen.queryByText(/Export still works/)).toBeNull();
});
