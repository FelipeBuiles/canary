import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { MarketingDesk } from "../components/marketing/MarketingDesk";
import { fetchMarketingSnapshot, localMarketingAvailable, transitionMarketingDraft } from "../api/marketing";
import { I18nProvider } from "../i18n";
import type { MarketingSnapshot } from "../types/marketing";

vi.mock("../api/marketing", async importOriginal => ({
  ...await importOriginal<typeof import("../api/marketing")>(),
  fetchMarketingSnapshot: vi.fn(), transitionMarketingDraft: vi.fn(),
}));
const connection = { baseUrl: "http://127.0.0.1:8000", token: "operator" };
const fixture: MarketingSnapshot = {
  drafts: [{ path: "drafts/blog/example.md", body: "Public copy only", revision: "a".repeat(64), approvalCurrent: true, issues: [], meta: { kind: "article", channel: "blog", title: "A chapter first", facts: ["novel"], sources: [], created: "2026-10-27", status: "draft" } }],
  reports: [{ path: "intel/reports/2026-10-27-plan.md", title: "Weekly plan", body: "# Weekly plan\nResearch evidence" }],
  facts: [{ id: "novel", statement: "Novels become comics", quote: "Source quotation", sources: ["PRODUCT.md:1"], marketable: true }],
  issues: [], canarySha: "abcdef1234",
};
function desk() { return render(<MemoryRouter><I18nProvider><MarketingDesk connection={connection} /></I18nProvider></MemoryRouter>); }
beforeEach(() => {
  vi.mocked(fetchMarketingSnapshot).mockReset().mockResolvedValue(structuredClone(fixture));
  vi.mocked(transitionMarketingDraft).mockReset();
});

it("shows local drafts, quotes and reports without triggering generation", async () => {
  const user = userEvent.setup();
  desk();
  expect(await screen.findByText("Public copy only")).toBeTruthy();
  expect(screen.getByText("Source quotation")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: /Plans & reports/ }));
  expect(screen.getByText(/Research evidence/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  expect(transitionMarketingDraft).not.toHaveBeenCalled();
});

it("sends the reviewed revision with approval and records publication only after confirmation", async () => {
  const user = userEvent.setup();
  const approved: MarketingSnapshot = { ...fixture, drafts: [{ ...fixture.drafts[0], revision: "b".repeat(64), meta: { ...fixture.drafts[0].meta, status: "approved" } }] };
  vi.mocked(transitionMarketingDraft).mockResolvedValueOnce(approved);
  desk();
  await user.click(await screen.findByRole("button", { name: "Approve" }));
  expect(transitionMarketingDraft).toHaveBeenCalledWith(connection, { path: fixture.drafts[0].path, revision: "a".repeat(64), transition: { to: "approved" } }, expect.any(AbortSignal));
  await user.click(await screen.findByRole("button", { name: "I posted it" }));
  expect(transitionMarketingDraft).toHaveBeenCalledTimes(1);
  await user.type(screen.getByLabelText(/Where did you post/), "https://example.com/post");
  vi.mocked(transitionMarketingDraft).mockResolvedValueOnce({ ...approved, drafts: [{ ...approved.drafts[0], meta: { ...approved.drafts[0].meta, status: "published", published: { at: "2026-10-28", url: "https://example.com/post" } } }] });
  await user.click(screen.getByRole("button", { name: "Record publication" }));
  await waitFor(() => expect(transitionMarketingDraft).toHaveBeenCalledTimes(2));
  expect(vi.mocked(transitionMarketingDraft).mock.calls[1][1]).toEqual({ path: fixture.drafts[0].path, revision: "b".repeat(64), transition: { to: "published", url: "https://example.com/post" } });
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
});

it("keeps stale copy visible and disables actions after a conflict until refreshed", async () => {
  const user = userEvent.setup();
  vi.mocked(transitionMarketingDraft).mockRejectedValueOnce(new Error("Workspace changed; refresh before continuing"));
  desk();
  await user.click(await screen.findByRole("button", { name: "Approve" }));
  await screen.findByRole("alert");
  expect(screen.getByText("Public copy only")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Approve" }).matches(":disabled")).toBe(true);
  await user.click(screen.getAllByRole("button", { name: "Refresh desk" })[0]);
  await waitFor(() => expect(screen.getByRole("button", { name: "Approve" }).matches(":disabled")).toBe(false));
});

it("blocks approval for audit errors and requires a reason to reject", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchMarketingSnapshot).mockResolvedValue({ ...fixture, issues: [{ level: "error", path: "knowledge/facts.yaml", message: "Missing source" }] });
  desk();
  expect((await screen.findByRole("button", { name: "Approve" })).matches(":disabled")).toBe(true);
  await user.click(screen.getByRole("button", { name: "Reject" }));
  expect(screen.getByRole("button", { name: "Confirm rejection" }).matches(":disabled")).toBe(true);
  await user.type(screen.getByLabelText("Why reject this draft?"), "Needs different copy");
  vi.mocked(transitionMarketingDraft).mockResolvedValue(fixture);
  await user.click(screen.getByRole("button", { name: "Confirm rejection" }));
  expect(vi.mocked(transitionMarketingDraft).mock.calls[0][1].transition).toEqual({ to: "rejected", reason: "Needs different copy" });
});

it("offers reapproval instead of publication when supporting evidence is stale", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchMarketingSnapshot).mockResolvedValue({ ...fixture, drafts: [{ ...fixture.drafts[0], approvalCurrent: false, issues: [{ path: fixture.drafts[0].path, level: "error", message: "edited after approval; re-approve before posting" }], meta: { ...fixture.drafts[0].meta, status: "approved" } }] });
  desk();
  await screen.findByRole("button", { name: /Approved 1/ });
  await user.click(screen.getByRole("button", { name: /Approved 1/ }));
  expect(screen.queryByRole("button", { name: "I posted it" })).toBeNull();
  expect(screen.getByRole("button", { name: "Approve" }).matches(":disabled")).toBe(false);
});

it("shows changed published evidence as history without offering or requesting reapproval", async () => {
  const user = userEvent.setup();
  vi.mocked(fetchMarketingSnapshot).mockResolvedValue({ ...fixture, drafts: [{ ...fixture.drafts[0], approvalCurrent: false, issues: [{ path: fixture.drafts[0].path, level: "warn", message: "Published history: supporting evidence changed" }], meta: { ...fixture.drafts[0].meta, status: "published", published: { at: "2026-10-28" } } }] });
  desk();
  await user.click(await screen.findByRole("button", { name: /Published 1/ }));
  expect(screen.getByText("Published history: supporting evidence changed")).toBeTruthy();
  expect(screen.queryByText(/approve again before posting/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  expect(screen.queryByRole("button", { name: "I posted it" })).toBeNull();
});

it("restricts marketing navigation to local development connections", () => {
  expect(localMarketingAvailable("http://127.0.0.1:8000", "localhost")).toBe(true);
  expect(localMarketingAvailable("https://scenewright.ink", "localhost")).toBe(false);
  expect(localMarketingAvailable("http://127.0.0.1:8000", "scenewright.ink")).toBe(false);
  expect(localMarketingAvailable("http://localhost.evil.example", "localhost")).toBe(false);
});
