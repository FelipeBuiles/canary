import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { StyleRoom } from "../pages/rooms/StyleRoom";
import { I18nProvider } from "../i18n";

const state = vi.hoisted(() => {
  const mutation = { mutate: vi.fn(), isPending: false };
  const emptyQuery = () => ({ data: undefined });
  return { mutation, emptyQuery, estimateError: null as Error | null, retryEstimate: vi.fn(), labels: ["Ink", "Watercolor", "Noir", "Graphic"],
    castStatus: undefined as string | undefined, handleRun: vi.fn(), generateCover: vi.fn() };
});
vi.mock("../api/queries", () => ({
  useStyles: () => ({ data: { suggestions: state.labels.map((label, index) => ({
    id: label, index, label, template: `Full ${label} direction`, has_sample: true, is_active: false,
  })) }, refetch: vi.fn(), isLoading: false, isError: false }),
  useProjectConfig: state.emptyQuery, useStoryBible: state.emptyQuery,
  useProjectStatus: () => ({ data: state.castStatus ? { style_selected: true, has_cover: false,
    stages: { style: { status: "complete" }, cast: { status: state.castStatus } } } : undefined }), useGenerationJobs: state.emptyQuery,
  useSuggestStylesEstimate: () => ({ error: state.estimateError, refetch: state.retryEstimate }), useStyleDirectionEstimate: () => ({ refetch: vi.fn() }),
  useStyleSampleEstimate: state.emptyQuery, useStageEstimate: () => ({ data: { estimate_credits: 25 } }),
  useProjectCoverEstimate: state.emptyQuery, useProjects: state.emptyQuery,
  useImageGenerationMeta: state.emptyQuery,
  useSuggestStyles: () => state.mutation, useCreateStyleDirection: () => state.mutation,
  useGenerateStyleSamples: () => state.mutation, useGenerateStyleValidation: () => state.mutation,
  useApproveStage: () => state.mutation, useGenerateProjectCover: () => ({ mutate: state.generateCover }),
  useSetActiveStyle: () => state.mutation,
}));
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: state.handleRun, isPending: false }) }));
vi.mock("../components/composites", async (importOriginal) => ({
  ...await importOriginal<object>(),
  RoomShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
  RoomHeader: () => null,
  ApprovalBar: ({ onPrimary, primaryDisabled, estimateCredits }: { onPrimary: () => void; primaryDisabled: boolean; estimateCredits: number }) =>
    <button disabled={primaryDisabled} onClick={onPrimary}>Continue for {estimateCredits}</button>,
  ConfirmDrawer: () => null, RerunStageAction: () => null,
}));

function proof(label: string) {
  const heading = screen.getByRole("heading", { name: label, level: 3 });
  return within(heading.parentElement!);
}

describe("StyleRoom comparison", () => {
  it("guides the first addition, keeps three choices without eviction, and allows replacement after removal", async () => {
    const user = userEvent.setup();
    const room = () => <I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
      <Route path="/projects/:id/style" element={<StyleRoom />} />
    </Routes></MemoryRouter></I18nProvider>;
    const view = render(room());
    await user.click(proof("Ink").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByText("One proof added. Choose another to start comparing.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "COMPARE PROOFS" })).toBeNull();
    await user.click(proof("Watercolor").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByRole("region", { name: "COMPARE PROOFS" })).toBeTruthy();
    await user.click(proof("Noir").getByRole("button", { name: "COMPARE" }));
    const fourth = proof("Graphic").getByRole("button", { name: "COMPARE" });
    expect(fourth).toHaveProperty("disabled", true);
    await user.click(fourth);
    for (const label of ["Ink", "Watercolor", "Noir"]) {
      expect(screen.getByRole("button", { name: `Remove from comparison · ${label}` })).toBeTruthy();
    }
    expect(screen.getByText("Three proofs added. Remove one to compare another.")).toBeTruthy();
    await user.click(proof("Watercolor").getByRole("button", { name: "COMPARING" }));
    expect(screen.queryByRole("button", { name: "Remove from comparison · Watercolor" })).toBeNull();
    await user.click(proof("Graphic").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByRole("button", { name: "Remove from comparison · Graphic" })).toBeTruthy();
    state.labels = ["Etching", "Pastel", "Woodcut"];
    view.rerender(room());
    await user.click(proof("Etching").getByRole("button", { name: "COMPARE" }));
    expect(screen.getByText("One proof added. Choose another to start comparing.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove from comparison · Etching" })).toBeTruthy();
    expect(state.mutation.mutate).not.toHaveBeenCalled();
  });
});

it("shows estimate failures with a retry instead of claiming generation is running", async () => {
    state.labels = [];
    state.estimateError = new Error("A job cannot mix API-funded and Codex-subscription operations");
    render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
      <Route path="/projects/:id/style" element={<StyleRoom />} />
    </Routes></MemoryRouter></I18nProvider>);
    expect(screen.getByRole("alert").textContent).toContain(state.estimateError.message);
    expect(screen.queryByText("PREPARING DIRECTIONS…")).toBeNull();
    expect(screen.getByRole("button", { name: "CREATE FIVE DIRECTIONS" })).toHaveProperty("disabled", true);
    await userEvent.setup().click(screen.getByRole("button", { name: "TRY AGAIN" }));
    expect(state.retryEstimate).toHaveBeenCalledOnce();
    expect(state.mutation.mutate).not.toHaveBeenCalled();
 });

it("starts Cast with its bundled cover estimate without requesting a cover before references exist", async () => {
  state.castStatus = "pending";
  state.estimateError = null;
  render(<I18nProvider><MemoryRouter initialEntries={["/projects/book/style"]}><Routes>
    <Route path="/projects/:id/style" element={<StyleRoom />} />
    <Route path="/project/:id/cast" element={<p>Cast room</p>} />
  </Routes></MemoryRouter></I18nProvider>);
  await userEvent.setup().click(screen.getByRole("button", { name: "Continue for 25" }));
  expect(state.handleRun).toHaveBeenCalledWith("book", "cast", { actionLabel: "Cast characters & places" });
  expect(state.generateCover).not.toHaveBeenCalled();
  expect(screen.getByText("Cast room")).toBeTruthy();
  state.castStatus = undefined;
});
