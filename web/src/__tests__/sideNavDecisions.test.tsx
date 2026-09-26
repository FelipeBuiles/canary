import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const readiness = vi.hoisted(() => ({ documents: true }));
beforeEach(() => { readiness.documents = true; });

vi.mock("../api/queries", () => ({
  useProjectStatus: () => ({
    data: {
      is_running: false,
      style_selected: true,
      stages: {
        extract: { status: "complete" },
        brief: { status: "complete", approved: true },
        style: { status: "complete" },
        cast: { status: "complete", approved: true },
        adapt: { status: readiness.documents ? "complete" : "pending" },
        plan: { status: readiness.documents ? "complete" : "pending" },
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


describe("SideNav locked stations", () => {
  it("disables Book on desktop and in the mobile station picker", () => {
    renderNav("/project/demo/story");
    expect(screen.getByRole("button", { name: /Station 04 Book: Locked/ }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "STATION" }));
    expect(screen.getByRole("option", { name: /04 Book.*Locked/ }).hasAttribute("disabled")).toBe(true);
  });
});


it("locks both reading subpages until their documents exist", () => {
  readiness.documents = false;
  renderNav("/project/demo/pages");
  for (const name of ["Book adaptation", "Page plan"]) {
    const button = screen.getByRole("button", { name });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.click(button);
  }
  expect(screen.getByTestId("location").textContent).toBe("/project/demo/pages");
});
