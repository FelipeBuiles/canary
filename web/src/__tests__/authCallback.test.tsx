import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { AuthCallbackPage } from "../pages/auth/AuthCallbackPage";

const mocks = vi.hoisted(() => ({ session: null as object | null, loading: false, updateUser: vi.fn(), recordAccountSeen: vi.fn() }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => mocks }));
vi.mock("../lib/supabase", () => ({ supabase: { auth: { updateUser: mocks.updateUser } } }));
vi.mock("../api/events", () => ({ recordAccountSeen: mocks.recordAccountSeen }));
function setup(url = "/auth/callback?sample=an-education&source=google") {
  render(<I18nProvider><MemoryRouter initialEntries={[url]}><Routes>
    <Route path="/auth/callback" element={<AuthCallbackPage />} />
    <Route path="/" element={<p>Studio home</p>} />
  </Routes></MemoryRouter></I18nProvider>);
}
beforeEach(() => {
  mocks.session = null; mocks.loading = false;
  mocks.updateUser.mockReset().mockResolvedValue({ error: null });
  mocks.recordAccountSeen.mockReset().mockResolvedValue(undefined);
});

it("offers a safe retry retaining the selected sample for cancelled Google sign-in", () => {
  setup("/auth/callback?sample=an-education&next=https://evil.example#error=access_denied");
  expect(screen.getByRole("alert").textContent).toContain("did not finish");
  expect(screen.getByRole("link", { name: "Back to sign in" }).getAttribute("href")).toBe("/login?sample=an-education");
  expect(mocks.updateUser).not.toHaveBeenCalled();
});

it("waits until Supabase has restored the Google session", () => {
  mocks.loading = true;
  setup();
  expect(screen.getByRole("status").textContent).toBe("Finishing your sign-in…");
  expect(mocks.recordAccountSeen).not.toHaveBeenCalled();
});

it("persists new OAuth attribution before recording the account and opening the studio", async () => {
  mocks.session = { user: { id: "author", created_at: new Date().toISOString(), app_metadata: { provider: "google" }, user_metadata: {} } };
  setup();
  await screen.findByText("Studio home");
  expect(mocks.updateUser).toHaveBeenCalledExactlyOnceWith({ data: { acquisition: { source: "google" } } });
  expect(mocks.recordAccountSeen).toHaveBeenCalledOnce();
  expect(mocks.updateUser.mock.invocationCallOrder[0]).toBeLessThan(mocks.recordAccountSeen.mock.invocationCallOrder[0]);
});

it("allows access even when best-effort attribution fails", async () => {
  mocks.session = { user: { id: "author", created_at: new Date().toISOString(), app_metadata: { provider: "google" }, user_metadata: {} } };
  mocks.updateUser.mockRejectedValue(new Error("Offline"));
  setup();
  await waitFor(() => expect(screen.getByText("Studio home")).toBeTruthy());
});

it("does not hold up studio access while attribution is slow", async () => {
  mocks.session = { user: { id: "author", created_at: new Date().toISOString(), app_metadata: { provider: "google" }, user_metadata: {} } };
  mocks.updateUser.mockReturnValue(new Promise(() => {}));
  setup();
  await screen.findByText("Studio home");
  expect(mocks.recordAccountSeen).not.toHaveBeenCalled();
});
