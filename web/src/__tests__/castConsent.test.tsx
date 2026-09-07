import type { ReactNode } from "react";
import type * as Composites from "../components/composites";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const run = vi.fn();
let stageStatus = "pending";
let selectedStyle = true;
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: run, isPending: false }) }));
vi.mock("../api/queries", () => ({
  useStoryBible: () => ({ data: { characters: [], locations: [], props: [] }, isLoading: false }),
  useProjectStatus: () => ({ data: { style_selected: selectedStyle, stages: { cast: { status: stageStatus } } } }),
  useApproveStage: () => ({ mutate: vi.fn(), isPending: false }),
  useResetStale: () => ({ mutate: vi.fn(), isPending: false }),
  useStageEstimate: () => ({ data: { estimate_credits: 20, reserved_credits: 30, reservation_multiplier: 1.5, confidence: "variable" } }),
  useCreditBalance: () => ({ data: undefined }),
}));
vi.mock("../components/composites", async (importOriginal) => {
  const original = await importOriginal<typeof Composites>();
  return { ...original, RoomShell: ({ children }: { children: ReactNode }) => children, RerunStageAction: () => null };
});
import { CastRoom } from "../pages/rooms/CastRoom";

function renderCast() {
  return render(<MemoryRouter initialEntries={["/project/demo/cast"]}><I18nProvider><Routes><Route path="/project/:id/cast" element={<CastRoom />} /></Routes></I18nProvider></MemoryRouter>);
}

beforeEach(() => { run.mockReset(); stageStatus = "pending"; selectedStyle = true; });

describe("cast consent", () => {
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
