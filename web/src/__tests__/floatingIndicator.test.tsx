import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { FloatingIndicator } from "../components/ui/FloatingIndicator";

const data = vi.hoisted(() => ({ status: {} as Record<string, unknown> }));
vi.mock("../api/queries", () => ({ useProjectStatus: () => ({ data: data.status }) }));

function show(path: string) {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/project/:id/:room" element={<FloatingIndicator />} /></Routes>
  </MemoryRouter></QueryClientProvider>);
}

describe("floating job activity", () => {
  it("follows the actual Style job despite an unfinished Draw checkpoint", () => {
    data.status = { is_running: true, stages: {
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

  it("does not invent a running job from a checkpoint", () => {
    data.status = { is_running: true, stages: { draw: { status: "running" } }, active_jobs: [] };
    show("/project/book/styles");
    expect(screen.queryByRole("status")).toBeNull();
  });
});
