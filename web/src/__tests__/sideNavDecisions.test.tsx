import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
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
  useAdaptation: () => ({ data: undefined }),
  useBookPlan: () => ({ data: undefined }),
  useCompletePages: () => ({ data: undefined }),
}));

import { SideNav } from "../layout/SideNav";

function LocationProbe() {
  const location = useLocation();
  return <p data-testid="location">{location.pathname}{location.search}</p>;
}

function renderNav(initialPath: string) {
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <I18nProvider>
        <Routes>
          <Route path="/project/:id/story" element={<SideNav />} />
          <Route path="/project/:id/styles" element={<SideNav />} />
          <Route path="/project/:id/cast" element={<SideNav />} />
          <Route path="/project/:id/pages" element={<SideNav />} />
        </Routes>
        <LocationProbe />
      </I18nProvider>
    </MemoryRouter>,
  );
}

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

describe("SideNav reading actions", () => {
  it("opens the adaptation drawer without leaving the Pages room", () => {
    renderNav("/project/demo/pages");

    fireEvent.click(screen.getByRole("button", { name: "Book adaptation" }));

    expect(screen.getByTestId("location").textContent).toBe(
      "/project/demo/pages?reading=adaptation",
    );
    expect(screen.getByRole("button", { name: "Book adaptation" }).getAttribute("aria-current"))
      .toBe("page");
  });

  it("reaches the page plan drawer from another room", () => {
    renderNav("/project/demo/story");

    fireEvent.click(screen.getByRole("button", { name: "Page plan" }));

    expect(screen.getByTestId("location").textContent).toBe(
      "/project/demo/pages?reading=page-plan",
    );
  });
});
