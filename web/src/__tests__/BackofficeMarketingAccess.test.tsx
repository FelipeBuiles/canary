import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { BackofficePage } from "../pages/BackofficePage";
import { fetchOperatorSnapshot } from "../api/operator";
import { fetchMarketingSnapshot } from "../api/marketing";
import { I18nProvider } from "../i18n";

vi.mock("../api/operator", async importOriginal => ({
  ...await importOriginal<typeof import("../api/operator")>(), fetchOperatorSnapshot: vi.fn(),
}));
vi.mock("../api/marketing", async importOriginal => ({
  ...await importOriginal<typeof import("../api/marketing")>(), fetchMarketingSnapshot: vi.fn(),
}));

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.mocked(fetchOperatorSnapshot).mockReset().mockRejectedValue(new Error("Supabase unavailable"));
  vi.mocked(fetchMarketingSnapshot).mockReset().mockResolvedValue({ drafts: [], reports: [], facts: [], issues: [], canarySha: undefined });
});

function page() {
  return render(<MemoryRouter><I18nProvider><BackofficePage /></I18nProvider></MemoryRouter>);
}

it("opens the local Marketing desk with its own authenticated request without loading Supabase", async () => {
  const user = userEvent.setup();
  page();
  await user.type(screen.getByLabelText("Server URL", { exact: false }), "http://127.0.0.1:8000");
  await user.type(screen.getByLabelText("Operations token"), "local-operator");
  await user.click(screen.getByRole("button", { name: "Open local Marketing" }));
  await screen.findByText("No draft drafts. Skills save new copy under marketing/drafts/.");
  expect(fetchMarketingSnapshot).toHaveBeenCalledWith({ baseUrl: "http://127.0.0.1:8000", token: "local-operator" }, expect.any(AbortSignal));
  expect(fetchOperatorSnapshot).not.toHaveBeenCalled();
  expect(screen.queryByRole("navigation", { name: "Backoffice sections" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  expect(await screen.findByRole("button", { name: "Connect" })).toBeTruthy();
  expect(sessionStorage.getItem("scenewright.operator.token")).toBeNull();
});

it("still opens Marketing after the operator connection fails", async () => {
  const user = userEvent.setup();
  sessionStorage.setItem("scenewright.operator.token", "local-operator");
  page();
  await screen.findByText("Supabase unavailable");
  await user.click(screen.getByRole("button", { name: "Open local Marketing" }));
  await screen.findByRole("region", { name: "Marketing desk" });
  await waitFor(() => expect(fetchMarketingSnapshot).toHaveBeenCalledTimes(1));
  expect(fetchOperatorSnapshot).toHaveBeenCalledTimes(1);
});

it("does not offer local Marketing for a remote API or an empty operations token", async () => {
  const user = userEvent.setup();
  page();
  expect(screen.getByRole("button", { name: "Open local Marketing" }).matches(":disabled")).toBe(true);
  await user.type(screen.getByLabelText("Server URL", { exact: false }), "https://scenewright.ink");
  expect(screen.queryByRole("button", { name: "Open local Marketing" })).toBeNull();
  expect(fetchMarketingSnapshot).not.toHaveBeenCalled();
});

it("does not expose workspace data when the marketing API rejects the token", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchMarketingSnapshot).mockRejectedValue(new Error("Invalid operations token"));
  page();
  await user.type(screen.getByLabelText("Operations token"), "invalid-token");
  await user.click(screen.getByRole("button", { name: "Open local Marketing" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("No draft drafts. Skills save new copy under marketing/drafts/.")).toBeNull();
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  expect(fetchOperatorSnapshot).not.toHaveBeenCalled();
});
