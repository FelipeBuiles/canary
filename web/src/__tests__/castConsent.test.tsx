import type { ReactNode } from "react";
import type * as Composites from "../components/composites";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const run = vi.fn();
const approve = vi.fn();
let stageStatus = "pending";
let approvalBlocker: string | null = null;
let selectedStyle = true;
let failures: unknown[] = [];
let isRunning = false;
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: run, isPending: false }) }));
vi.mock("../api/seriesQueries", () => ({
  useCastFreshness: () => ({ data: undefined }),
  useKeepReference: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useReopenCast: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));
let castReview: unknown = undefined;
let redrawing = new Set<string>();
vi.mock("../api/castReview", () => ({ useCastReview: () => ({ data: castReview }), useRedrawingCharacters: () => redrawing }));
vi.mock("../api/queries", () => ({
  useStoryBible: () => ({ data: { characters: [], locations: [], props: [] }, isLoading: false }),
  useProjectStatus: () => ({ data: { style_selected: selectedStyle, is_running: isRunning, stages: { cast: { status: stageStatus, approval_blocker: approvalBlocker, failures } } } }),
  useApproveStage: () => ({ mutate: approve, isPending: false }),
  useResetStale: () => ({ mutate: vi.fn(), isPending: false }),
  useStageEstimate: () => ({ data: { estimate_credits: 20, reserved_credits: 30, reservation_multiplier: 1.5, confidence: "variable" } }),
  useCreditBalance: () => ({ data: undefined }),
}));
vi.mock("../components/composites", async (importOriginal) => {
  const original = await importOriginal<typeof Composites>();
  return { ...original, RoomShell: ({ children }: { children: ReactNode }) => children, RerunStageAction: () => null };
});
import { CastFailureNotice, CastRoom } from "../pages/rooms/CastRoom";
import { CAST_REVIEW_BLOCKER } from "../lib/castCheckpoint";

function renderCast() {
  return render(<MemoryRouter initialEntries={["/project/demo/cast"]}><I18nProvider><Routes><Route path="/project/:id/cast" element={<CastRoom />} /></Routes></I18nProvider></MemoryRouter>);
}

beforeEach(() => { run.mockReset(); approve.mockReset(); stageStatus = "pending"; approvalBlocker = null; selectedStyle = true; failures = []; isRunning = false; castReview = undefined; redrawing = new Set(); });

describe("cast consent", () => {
  it("names the reference that stopped Cast and why instead of a bare resume prompt", () => {
    stageStatus = "failed";
    const message = "The image provider declined this scene but did not say which detail caused it. Your work is unchanged. Change its direction, or regenerate it from its card.";
    approvalBlocker = `Kaitlin — Naked, suit gone: ${message}`;
    failures = [{
      item_id: "kaitlin:naked", asset_type: "character", entity_id: "kaitlin", state_id: "naked",
      label: "Kaitlin — Naked, suit gone", classification: "provider_blocked", attempts: 1, message,
    }];
    renderCast();
    const notice = screen.getByRole("alert", { name: "CAST STOPPED" });
    expect(within(notice).getByRole("link", { name: "Kaitlin — Naked, suit gone" }).getAttribute("href")).toBe("#cast-character-kaitlin");
    expect(within(notice).getByText(message)).toBeTruthy();
    expect(screen.getByText(approvalBlocker)).toBeTruthy();
  });

  it("names the likely wording behind a decline and offers ways to unblock it", async () => {
    const user = userEvent.setup();
    const onLessGraphic = vi.fn();
    const failure = {
      item_id: "sphinx", asset_type: "prop" as const, entity_id: "sphinx", state_id: null,
      label: "Wooden sphinx", classification: "provider_blocked", attempts: 1, message: "Declined.",
      likely_triggers: [{ phrase: "bare womanly torso", category: "nudity" as const, source: "description" as const, context: "…" }],
    };
    render(<MemoryRouter initialEntries={["/project/demo/cast"]}><I18nProvider><Routes><Route path="/project/:id/cast"
      element={<CastFailureNotice failures={[failure]} onLessGraphic={onLessGraphic} />} /></Routes></I18nProvider></MemoryRouter>);
    const notice = screen.getByRole("alert", { name: "CAST STOPPED" });
    expect(within(notice).getByText("bare womanly torso").parentElement!.textContent).toContain("nudity in its description");
    expect(within(notice).getByRole("link", { name: "Reword its description" }).getAttribute("href"))
      .toBe("/project/demo/story?edit=props:sphinx");
    await user.click(within(notice).getByRole("button", { name: "Make a less graphic version" }));
    expect(onLessGraphic).toHaveBeenCalledWith(failure);
  });

  it("hides a stopped Cast's failure while a new run is queued", () => {
    stageStatus = "failed";
    isRunning = true;
    failures = [{
      item_id: "kaitlin:naked", asset_type: "character", entity_id: "kaitlin", state_id: "naked",
      label: "Kaitlin — Naked, suit gone", classification: "provider_blocked", attempts: 1, message: "Declined.",
    }];
    renderCast();
    expect(screen.queryByRole("alert", { name: "CAST STOPPED" })).toBeNull();
  });

  it("says open Character Check notes are advice and keeps Continue enabled", () => {
    stageStatus = "awaiting_review";
    castReview = { status: "current", reviewing: false, dismissed: 0, issues: [
      { character_ids: ["a"], concern: "presentation", evidence: "Too tall", suggestion: "Shrink" }] };
    renderCast();
    expect(screen.getByText("1 character note is open. You can still continue; notes are advice.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "LOOKS RIGHT — CONTINUE →" }).hasAttribute("disabled")).toBe(false);
  });

  it("keeps Continue disabled while a character sheet is being redrawn", () => {
    stageStatus = "awaiting_review";
    redrawing = new Set(["a"]);
    renderCast();
    expect(screen.getByText("A reference is still being drawn. Continue unlocks when it finishes.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "LOOKS RIGHT — CONTINUE →" }).hasAttribute("disabled")).toBe(true);
  });

  it("offers review instead of another generation once individually generated references are ready", () => {
    stageStatus = "awaiting_review";
    renderCast();
    expect(screen.queryByRole("button", { name: "START CAST" })).toBeNull();
    expect(screen.getByRole("button", { name: "LOOKS RIGHT — CONTINUE →" }).hasAttribute("disabled")).toBe(false);
    expect(run).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("explains a refused approval beside the button that was pressed", async () => {
    const user = userEvent.setup();
    stageStatus = "awaiting_review";
    approve.mockImplementation((_vars, options) => options.onError(new Error("Wait for all project jobs to finish before changing this project.")));
    renderCast();
    const continueButton = screen.getByRole("button", { name: "LOOKS RIGHT — CONTINUE →" });
    await user.click(continueButton);
    expect(approve).toHaveBeenCalledWith({ project: "demo", stage: "cast" }, expect.anything());
    const alert = within(continueButton.closest("footer")!).getByRole("alert");
    expect(alert.textContent).toBe("Wait for all project jobs to finish before changing this project.");
  });

  it("does not spend on entry and requires confirmation after showing the estimate and hold", async () => {
    const user = userEvent.setup();
    renderCast();
    expect(run).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "START CAST" }));
    expect(run).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText(/Temporary hold/)).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "START CAST" }));
    expect(run).toHaveBeenCalledWith("demo", "cast", expect.objectContaining({ actionLabel: "Start cast characters & places" }));
  });

  it("keeps pending cast unavailable until a style is selected", async () => {
    const user = userEvent.setup();
    selectedStyle = false;
    renderCast();
    await user.click(screen.getByRole("button", { name: "START CAST" }));
    expect(run).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("requires deliberate resume and displays failed user action feedback", async () => {
    const user = userEvent.setup();
    stageStatus = "failed";
    renderCast();
    await user.click(screen.getByRole("button", { name: /RESUME CAST/ }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "RESUME CAST" }));
    act(() => run.mock.calls[0][2].onError(new Error("Provider unavailable")));
    expect(screen.getByRole("alert").textContent).toContain("Provider unavailable");
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});


it("replaces premature Continue with a confirmed resume for an incomplete checkpoint", async () => {
  stageStatus = "awaiting_review";
  approvalBlocker = "Resume Cast to finish the missing work";
  renderCast();
  expect(screen.queryByRole("button", { name: "LOOKS RIGHT — CONTINUE →" })).toBeNull();
  expect(screen.getByText(approvalBlocker)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: /RESUME CAST/ }));
  expect(run).not.toHaveBeenCalled();
  expect(screen.getByRole("alertdialog")).toBeTruthy();
});

it("links each failed reference to its own card and offers one confirmed resume beside the list", async () => {
  stageStatus = "failed";
  failures = [
    { item_id: "hall", asset_type: "location", entity_id: "hall", state_id: null, label: "Great Hall", classification: "provider_error", attempts: 1, message: "Timed out." },
    { item_id: "key", asset_type: "prop", entity_id: "key", state_id: null, label: "Brass Key", classification: "provider_error", attempts: 1, message: "Timed out." },
  ];
  renderCast();
  const notice = screen.getByRole("alert", { name: "CAST STOPPED" });
  expect(within(notice).getByRole("link", { name: "Great Hall" }).getAttribute("href")).toBe("#cast-location-hall");
  expect(within(notice).getByRole("link", { name: "Brass Key" }).getAttribute("href")).toBe("#cast-prop-key");
  await userEvent.click(within(notice).getByRole("button", { name: "RESUME CAST" }));
  expect(run).not.toHaveBeenCalled();
  expect(screen.getByRole("alertdialog")).toBeTruthy();
});

it("continues after corrections in one step: the server re-checks the cast, then approves it", async () => {
  stageStatus = "awaiting_review";
  approvalBlocker = CAST_REVIEW_BLOCKER;
  renderCast();
  expect(screen.queryByRole("button", { name: /RESUME CAST|RE-CHECK/ })).toBeNull();
  expect(screen.getByText("Scenewright checks your corrected cast, then adapts the book and plans complete pages — automatically")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "LOOKS RIGHT — CONTINUE →" }));
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(run).toHaveBeenCalledOnce();
  expect(run.mock.calls[0][1]).toBe("cast");
  expect(run.mock.calls[0][2]).toMatchObject({ thenApprove: true });
  expect(approve).not.toHaveBeenCalled();
});
