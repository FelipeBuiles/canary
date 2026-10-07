import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { FloatingIndicator } from "../components/ui/FloatingIndicator";
import { I18nProvider } from "../i18n";

const data = vi.hoisted(() => ({ status: {} as Record<string, unknown> }));
vi.mock("../api/queries", () => ({ useProjectStatus: () => ({ data: data.status }) }));

function show(path: string) {
  return render(<QueryClientProvider client={new QueryClient()}><I18nProvider><MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/project/:id/:room" element={<FloatingIndicator />} /></Routes>
  </MemoryRouter></I18nProvider></QueryClientProvider>);
}

describe("floating job activity", () => {
  const runningCast = {
    is_running: true, part_busy: true, series_busy: false,
    stages: { cast: { status: "running", items_done: 2, items_total: 5 } },
    active_jobs: [{ stage: "cast", status: "running" }],
  };

  it.each(["story", "styles", "pages", "book", "settings"])("shows Cast progress on the %s page", (room) => {
    data.status = runningCast;
    show(`/project/book/${room}`);
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText("2 / 5")).toBeTruthy();
  });

  it("hides Cast progress on the Cast page", () => {
    data.status = runningCast;
    show("/project/book/cast");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("jumps from Art Style to the Cast page and hides the indicator", () => {
    data.status = runningCast;
    show("/project/book/styles");
    fireEvent.click(screen.getByRole("button", { name: "JUMP TO LOOK" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("follows the actual Style job despite an unfinished Draw checkpoint", () => {
    data.status = { is_running: true, part_busy: true, series_busy: false, stages: {
      draw: { status: "running", items_done: 1, items_total: 60 },
      style: { status: "awaiting_review", items_done: 0, items_total: 0 },
    }, active_jobs: [{ stage: "style", status: "running" }] };
    const view = show("/project/book/pages");
    expect(screen.getByRole("button", { name: "JUMP TO LOOK" })).toBeTruthy();
    expect(screen.queryByText("JUMP TO PAGES")).toBeNull();
    view.unmount();
    show("/project/book/styles");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("reports a Style batch by step, and counts only the proofs being painted", () => {
    const style = (payload: Record<string, unknown>) => ({ is_running: true, part_busy: true, series_busy: false, stages: {
      style: { status: "running", items_done: 0, items_total: 6 },
    }, active_jobs: [{ stage: "style", status: "running", payload }] });
    data.status = style({ style_phase: "directions" });
    const view = show("/project/book/story");
    expect(screen.getByText(/Step 1 of 3/)).toBeTruthy();
    expect(screen.queryByText(/0 \/ 6/)).toBeNull();
    view.unmount();
    data.status = style({ style_phase: "proofs", proofs: {
      0: { status: "complete" }, 1: { status: "complete" }, 2: { status: "running" },
      3: { status: "queued" }, 4: { status: "queued" }, 5: { status: "queued" },
    } });
    show("/project/book/story");
    expect(screen.getByText(/Step 3 of 3/)).toBeTruthy();
    expect(screen.getByText("2 / 6 proofs")).toBeTruthy();
  });

  it("does not invent a running job from a checkpoint", () => {
    data.status = { is_running: true, part_busy: true, series_busy: false, stages: { draw: { status: "running" } }, active_jobs: [] };
    show("/project/book/styles");
    expect(screen.queryByRole("status")).toBeNull();
  });
});
