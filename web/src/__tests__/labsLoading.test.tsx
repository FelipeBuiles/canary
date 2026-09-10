import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queries = vi.hoisted(() => ({
  models: { data: undefined, error: null as Error | null, isLoading: false, isFetching: false, refetch: vi.fn() },
  fixture: { data: undefined, error: null as Error | null, isLoading: false, isFetching: false, refetch: vi.fn() },
}));

vi.mock("../api/queries", () => ({
  useLabsModels: () => queries.models,
  useLabsFixture: () => queries.fixture,
}));

import { LabsRoom } from "../pages/LabsRoom";

describe("Labs initial loading recovery", () => {
  beforeEach(() => {
    for (const query of Object.values(queries)) {
      query.error = null;
      query.isLoading = false;
      query.isFetching = false;
      query.refetch.mockClear();
    }
  });

  it.each(["models", "fixture"] as const)("shows recovery when the %s query fails", (source) => {
    queries[source].error = new Error("Service unavailable");
    render(<LabsRoom />);

    expect(screen.getByRole("alert").textContent).toContain("Labs could not be loaded");
    expect(screen.queryByText("Loading models and sample scene…")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry Labs" }));
    expect(queries.models.refetch).toHaveBeenCalledTimes(1);
    expect(queries.fixture.refetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the error visible and prevents duplicate retries while a retry is fetching", () => {
    queries.fixture.error = new Error("Service unavailable");
    queries.models.isFetching = true;
    render(<LabsRoom />);

    expect(screen.getByRole("alert")).toBeTruthy();
    const retry = screen.getByRole("button", { name: "Retrying…" });
    expect((retry as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(retry);
    expect(queries.models.refetch).not.toHaveBeenCalled();
    expect(queries.fixture.refetch).not.toHaveBeenCalled();
  });
});
