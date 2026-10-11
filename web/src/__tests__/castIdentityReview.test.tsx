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

function mount(redrawing = new Set<string>()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const resume = vi.fn();
  const show = vi.fn();
  const use = vi.fn();
  render(<QueryClientProvider client={client}><I18nProvider>
    <CastIdentityReview projectId="demo" characters={[{ id: "a", name: "Armitage" }, { id: "b", name: "Rice" }]}
      locations={[{ id: "parlour", name: "Parlour" }]}
      onResume={resume} onShowCharacter={show} onUseSuggestion={use} busy={false} redrawing={redrawing} />
  </I18nProvider></QueryClientProvider>);
  return { resume, show, use };
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

it("hands a suggestion to the chosen character without starting work", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ status: "current", issues: [
    { character_ids: ["a"], concern: "scale", evidence: "Too tall", suggestion: "Scale Armitage down" },
    { character_ids: ["a", "b"], concern: "lookalike", evidence: "Same jaw", suggestion: "Give Rice a broader face" },
  ] });
  const { resume, use } = mount();
  await userEvent.click(await screen.findByText("2 notes to review"));
  await userEvent.click(screen.getAllByRole("button", { name: "Use this suggestion · Armitage" })[0]);
  expect(use).toHaveBeenLastCalledWith("character", "a", "Scale Armitage down");
  expect(screen.getByRole("button", { name: "Use this suggestion · Rice" }).textContent).toContain("Use for Rice");
  await userEvent.click(screen.getByRole("button", { name: "Use this suggestion · Rice" }));
  expect(use).toHaveBeenLastCalledWith("character", "b", "Give Rice a broader face");
  expect(resume).not.toHaveBeenCalled();
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

it("marks a note fine for the current sheets and hides it", async () => {
  const note = { character_ids: ["a"], concern: "presentation", evidence: "Too tall", suggestion: "Scale Armitage down" };
  vi.mocked(apiFetch).mockImplementation(async (_path, options) => (options?.method === "POST"
    ? { status: "current", issues: [], dismissed: 1, reviewing: false }
    : { status: "current", issues: [note], dismissed: 0, reviewing: false }));
  const { use } = mount();
  await userEvent.click(await screen.findByText("1 note to review"));
  await userEvent.click(screen.getByRole("button", { name: "This looks right" }));
  expect(apiFetch).toHaveBeenCalledWith("/projects/demo/cast/review/dismiss", {
    method: "POST", body: JSON.stringify({ character_ids: ["a"], location_ids: [], concern: "presentation" }),
  });
  expect(await screen.findByText(/You marked 1 note as fine/)).toBeTruthy();
  expect(screen.queryByText("Too tall")).toBeNull();
  expect(use).not.toHaveBeenCalled();
});

it("says what the check is doing while it runs and offers no resume", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ status: "stale", issues: [], dismissed: 0, reviewing: true, characters: 4 });
  mount();
  expect(await screen.findByText(/Comparing 4 character sheets for lookalikes/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "RESUME CAST" })).toBeNull();
});

it("hides a note while its character is being redrawn and says the check will run again", async () => {
  vi.mocked(apiFetch).mockResolvedValue({ status: "current", dismissed: 0, reviewing: false, issues: [
    { character_ids: ["a"], concern: "presentation", evidence: "Too tall", suggestion: "Scale Armitage down" }] });
  mount(new Set(["a"]));
  expect(await screen.findByText(/Redrawing Armitage\. The check runs again/)).toBeTruthy();
  expect(screen.queryByText("Too tall")).toBeNull();
  expect(screen.queryByRole("button", { name: "RESUME CAST" })).toBeNull();
});

it("links a plate's style note to the plate and hands its suggestion to that plate", async () => {
  const note = { character_ids: [], location_ids: ["parlour"], concern: "style",
    evidence: "Flat digital shading", suggestion: "Use torn paper collage layers" };
  vi.mocked(apiFetch).mockImplementation(async (_path, options) => (options?.method === "POST"
    ? { status: "current", issues: [], dismissed: 1, reviewing: false }
    : { status: "current", issues: [note], dismissed: 0, reviewing: false }));
  const { use, resume } = mount();
  await userEvent.click(await screen.findByText("1 note to review"));
  expect(screen.getByRole("link", { name: "Parlour" }).getAttribute("href")).toBe("#cast-location-parlour");
  await userEvent.click(screen.getByRole("button", { name: "Use this suggestion · Parlour" }));
  expect(use).toHaveBeenLastCalledWith("location", "parlour", "Use torn paper collage layers");
  await userEvent.click(screen.getByRole("button", { name: "This looks right" }));
  expect(apiFetch).toHaveBeenCalledWith("/projects/demo/cast/review/dismiss", {
    method: "POST", body: JSON.stringify({ character_ids: [], location_ids: ["parlour"], concern: "style" }),
  });
  expect(resume).not.toHaveBeenCalled();
});
