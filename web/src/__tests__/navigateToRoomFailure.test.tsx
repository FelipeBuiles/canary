import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { NavigateToRoom } from "../pages/NavigateToRoom";
import { I18nProvider } from "../i18n";

const refetch = vi.fn();
vi.mock("../api/queries", () => ({ useProjectStatus: () => ({
  data: undefined, isLoading: false, error: new Error("Status request failed"), refetch,
}) }));

it("replaces opening progress with recovery when no project status could be loaded", () => {
  render(<MemoryRouter initialEntries={["/project/demo"]}><I18nProvider><Routes>
    <Route path="/project/:id" element={<NavigateToRoom />} />
  </Routes></I18nProvider></MemoryRouter>);
  expect(screen.queryByText("OPENING PROJECT…")).toBeNull();
  expect(screen.getByText("The project could not be opened.")).toBeTruthy();
  expect(screen.getByText("Technical details").closest("details")?.open).toBe(false);
  expect(refetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(refetch).toHaveBeenCalledOnce();
});
