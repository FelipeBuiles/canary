import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { CastIdentityReview } from "../components/composites/CastIdentityReview";
import { I18nProvider } from "../i18n";
import { apiFetch } from "../api/client";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; vi.resetAllMocks(); });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const resume = vi.fn();
  const show = vi.fn();
  render(<QueryClientProvider client={client}><I18nProvider>
    <CastIdentityReview projectId="demo" characters={[{ id: "a", name: "Armitage" }, { id: "b", name: "Rice" }]}
      onResume={resume} onShowCharacter={show} busy={false} />
  </I18nProvider></QueryClientProvider>);
  return { resume, show };
}

it("shows visual evidence with character links and never starts work on entry", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ status: "current", issues: [{ character_ids: ["a", "b"],
    concern: "lookalike", evidence: "Matching jaw and nose", suggestion: "Give Rice a broader face" }] });
  const { resume, show } = mount();
  const summary = await screen.findByText("1 note to review");
  expect(summary.closest("details")?.open).toBe(false);
  await userEvent.click(summary);
  expect(summary.closest("details")?.open).toBe(true);
  expect(screen.getByText("Matching jaw and nose")).toBeTruthy();
  expect(screen.getByText("Suggested adjustment")).toBeTruthy();
  const link = screen.getByRole("link", { name: "Rice" });
  expect(link.getAttribute("href")).toBe("#cast-character-b");
  await userEvent.click(link);
  expect(show).toHaveBeenCalledOnce();
  expect(resume).not.toHaveBeenCalled();
  expect(apiFetch).toHaveBeenCalledWith("/projects/demo/cast/review");
});

it("does not present stale findings as current and requires deliberate review", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ status: "stale", issues: [{ character_ids: ["a"], evidence: "Old concern" }] });
  const { resume } = mount();
  const button = await screen.findByRole("button", { name: "RESUME CAST" });
  expect(screen.queryByText("Old concern")).toBeNull();
  expect(resume).not.toHaveBeenCalled();
  await userEvent.click(button);
  expect(resume).toHaveBeenCalledOnce();
});

it("does not call an empty report verified quality", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ status: "current", issues: [] });
  mount();
  expect(await screen.findByText(/not a guarantee of visual accuracy/)).toBeTruthy();
});

it("shows a failed read without claiming a clean cast", async () => {
  vi.mocked(apiFetch).mockRejectedValue(new Error("offline"));
  mount();
  expect(await screen.findByText(/Could not load the cast review/)).toBeTruthy();
  expect(screen.queryByText(/No identity problems/)).toBeNull();
});
