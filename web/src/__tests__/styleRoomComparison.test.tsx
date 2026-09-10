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
  return { mutation, emptyQuery, labels: ["Ink", "Watercolor", "Noir", "Graphic"] };
});
vi.mock("../api/queries", () => ({
  useStyles: () => ({ data: { suggestions: state.labels.map((label, index) => ({
    id: label, index, label, template: `Full ${label} direction`, has_sample: true, is_active: false,
  })) }, refetch: vi.fn(), isLoading: false, isError: false }),
  useProjectConfig: state.emptyQuery, useStoryBible: state.emptyQuery,
  useProjectStatus: state.emptyQuery, useGenerationJobs: state.emptyQuery,
  useSuggestStylesEstimate: state.emptyQuery, useStyleDirectionEstimate: state.emptyQuery,
  useStyleSampleEstimate: state.emptyQuery, useStageEstimate: state.emptyQuery,
  useProjectCoverEstimate: state.emptyQuery, useProjects: state.emptyQuery,
  useImageGenerationMeta: state.emptyQuery,
  useSuggestStyles: () => state.mutation, useCreateStyleDirection: () => state.mutation,
  useGenerateStyleSamples: () => state.mutation, useGenerateStyleValidation: () => state.mutation,
  useApproveStage: () => state.mutation, useGenerateProjectCover: () => state.mutation,
  useSetActiveStyle: () => state.mutation,
}));
vi.mock("../hooks/useRunAction", () => ({ useRunAction: () => ({ handleRun: vi.fn(), isPending: false }) }));
vi.mock("../components/composites", async (importOriginal) => ({
  ...await importOriginal<object>(),
  RoomShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
  RoomHeader: () => null, ApprovalBar: () => null, ConfirmDrawer: () => null, RerunStageAction: () => null,
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
