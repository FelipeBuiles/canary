import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      is_running: false,
      stages: {
        style: { status: "complete" },
        cast: { status: "complete" },
      },
    },
  }),
  useProjects: () => ({
    data: [{ id: "demo", project_name: "The Last Incantation" }],
  }),
}));

import { SideNav } from "../layout/SideNav";

describe("SideNav Look decisions", () => {
  it("keeps both art style and cast reachable after they are complete", () => {
    render(
      <MemoryRouter initialEntries={["/project/demo/styles"]}>
        <I18nProvider>
          <Routes>
            <Route path="/project/:id/:room" element={<SideNav />} />
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(screen.getAllByRole("button", { name: /Art style/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /Characters & places/i }).length).toBeGreaterThan(0);
  });
});
