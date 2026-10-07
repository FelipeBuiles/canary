import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { ErrorNotice } from "../components/composites/ErrorNotice";
import { I18nProvider, preloadLanguage } from "../i18n";
import { AuthApiError } from "@supabase/supabase-js";
import { errorDetails } from "../lib/errorPresentation";

function renderNotice(ui: ReactNode) {
  return render(<MemoryRouter><I18nProvider>{ui}</I18nProvider></MemoryRouter>);
}

afterEach(() => vi.unstubAllGlobals());

it("keeps a server exception collapsed and offers an explicit read retry", () => {
  const retry = vi.fn();
  const error = new ApiError(503, "RuntimeError: upstream gateway unavailable", "upstream_unavailable");
  error.diagnostics = { request_id: "request-123", trace_id: "trace-456" };
  renderNotice(<ErrorNotice error={error} operation="load" onRetry={retry} />);
  expect(screen.getByText("This could not be loaded.")).toBeTruthy();
  const details = screen.getByText("Technical details").closest("details")!;
  expect(details.open).toBe(false);
  expect(within(details).getByText(/RuntimeError/).textContent).toContain("Request: request-123");
  expect(retry).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(retry).toHaveBeenCalledOnce();
});

it("retains an application rejection's useful correction outside technical details", () => {
  renderNotice(<ErrorNotice error={new ApiError(400, "Select a visual direction first.")} operation="generate" />);
  expect(screen.getByText("Select a visual direction first.").closest("details")).toBeNull();
});

it("keeps credential validation useful without displaying an authentication code", () => {
  renderNotice(<ErrorNotice error={new AuthApiError("Invalid login credentials", 400, "invalid_credentials")} operation="auth" />);
  expect(screen.getByText("Invalid login credentials").closest("details")).toBeNull();
  expect(screen.getByText(/invalid_credentials/).closest("details")?.open).toBe(false);
});

it("does not show a proxy's JSON body as user-facing validation", () => {
  renderNotice(<ErrorNotice error={new ApiError(413, '{"error": "body_too_large"}')} operation="upload" />);
  expect(screen.getByText('{"error": "body_too_large"}', { exact: false }).closest("details")?.open).toBe(false);
});

it("keeps a bare API code inside technical details", () => {
  renderNotice(<ErrorNotice error={new ApiError(400, "invalid_request_error")} operation="generate" />);
  expect(screen.getByText(/invalid_request_error/).closest("details")?.open).toBe(false);
});

it("retains report identifiers when diagnostic text is truncated", () => {
  const error = new ApiError(500, "Large exception", "upstream_error");
  error.diagnostics = { request_id: "request-123" };
  const details = errorDetails(error, "Traceback line\n".repeat(2000));
  expect(details).toContain("Request: request-123");
  expect(details).toContain("upstream_error");
  expect(details.length).toBeLessThanOrEqual(12_000);
});

it("offers sign-in recovery when an authenticated API session expires", () => {
  renderNotice(<ErrorNotice error={new ApiError(401, "JWT expired")} operation="save" />);
  expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("/login");
  expect(screen.getByText("Your session has expired. Sign in to continue.")).toBeTruthy();
});

it("translates recovery guidance while retaining technical evidence", async () => {
  await preloadLanguage("fr");
  render(<MemoryRouter><I18nProvider pageLanguage="fr"><ErrorNotice error={new Error("Internal error")}
    operation="save" /></I18nProvider></MemoryRouter>);
  expect(screen.getByText("Vos modifications n’ont pas pu être enregistrées.")).toBeTruthy();
  expect(screen.getByText("Gardez vos modifications ici et réessayez de les enregistrer.")).toBeTruthy();
  expect(screen.getByText("Internal error").closest("details")?.open).toBe(false);
});

it("routes structured storage failures to project management", () => {
  renderNotice(<ErrorNotice error={new ApiError(413, "Quota exceeded", "storage_budget_exceeded")} operation="save" />);
  expect(screen.getByRole("heading", { name: "Account storage is full" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Manage projects" }).getAttribute("href")).toBe("/");
});

it("does not offer a retry for an action whose result is uncertain", () => {
  const retry = vi.fn();
  renderNotice(<ErrorNotice error={new ApiError(409, "This action may have been accepted.", "idempotency_indeterminate")}
    operation="generate" title="Drawing stopped" onRetry={retry} />);
  expect(screen.getByText("Check the earlier attempt")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  expect(retry).not.toHaveBeenCalled();
});

it("lets the author copy diagnostic identifiers without another request", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  renderNotice(<ErrorNotice error={new ApiError(500, "Request failed", "test_failure")} operation="save" />);
  fireEvent.click(screen.getByText("Technical details"));
  fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
  expect(await screen.findByText("Details copied.")).toBeTruthy();
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("HTTP 500"));
  expect(writeText).toHaveBeenCalledWith(expect.stringContaining("test_failure"));
});
