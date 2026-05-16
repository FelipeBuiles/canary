// @vitest-environment jsdom

import { renderHook } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import {
  useDrawProgressStore,
  useInFlight,
  useInFlightSet,
} from "../store/drawProgress";

const PROJECT = "proj-hooks";

beforeEach(() => {
  useDrawProgressStore.setState({ byProject: {} });
});

describe("drawProgress hooks", () => {
  it("keeps derived in-flight snapshots stable across unchanged renders", () => {
    useDrawProgressStore
      .getState()
      .applyPanelStart(PROJECT, "s_1", 1, "2026-05-15T18:00:00Z");

    const { result, rerender } = renderHook(() => ({
      inFlight: useInFlight(PROJECT),
      inFlightSet: useInFlightSet(PROJECT),
    }));

    const firstInFlight = result.current.inFlight;
    const firstInFlightSet = result.current.inFlightSet;

    rerender();

    expect(result.current.inFlight).toBe(firstInFlight);
    expect(result.current.inFlightSet).toBe(firstInFlightSet);
  });
});
