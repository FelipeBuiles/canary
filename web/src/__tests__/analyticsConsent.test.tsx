import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AnalyticsConsent } from "../components/AnalyticsConsent";
import { I18nProvider } from "../i18n";

const mocks = vi.hoisted(() => ({ consent: null as string | null, enabled: true, set: vi.fn() }));
vi.mock("../lib/ga4", () => ({
  getGa4Consent: () => mocks.consent, getServerGa4Consent: () => null,
  ga4MeasurementId: () => mocks.enabled ? "G-R9Q5LX1E00" : undefined,
  subscribeGa4Consent: () => () => {}, setGa4Consent: mocks.set,
}));
function view(preferences = false) {
  return <I18nProvider><MemoryRouter><AnalyticsConsent preferences={preferences} /></MemoryRouter></I18nProvider>;
}
beforeEach(() => { mocks.consent = null; mocks.enabled = true; mocks.set.mockReset(); });
it("offers equally accessible allow and decline choices with a privacy link", () => {
  const { rerender } = render(view());
  fireEvent.click(screen.getByRole("button", { name: "Decline Google Analytics" }));
  expect(mocks.set).toHaveBeenCalledWith("declined");
  expect(screen.getByRole("link", { name: "Privacy Policy" }).getAttribute("href")).toBe("/legal/privacy");
  mocks.consent = "declined";
  rerender(view());
  expect(screen.queryByRole("region")).toBeNull();
  rerender(view(true));
  expect(screen.getByText(/Google Analytics is disabled/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Allow Google Analytics" }));
  expect(mocks.set).toHaveBeenCalledWith("accepted");
});
it("does not show a banner when the integration is disabled", () => {
  mocks.enabled = false;
  render(view());
  expect(screen.queryByRole("region")).toBeNull();
});
