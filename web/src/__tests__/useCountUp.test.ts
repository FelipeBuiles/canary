import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { easeOutCount, useCountUp } from "../hooks/useCountUp";

describe("easeOutCount", () => {
  it("starts at from and ends at to", () => {
    expect(easeOutCount(100, 200, 0)).toBe(100);
    expect(easeOutCount(100, 200, 1)).toBe(200);
  });

  it("moves monotonically toward the target", () => {
    let previous = 0;
    for (const t of [0.1, 0.25, 0.5, 0.75, 0.9]) {
      const value = easeOutCount(0, 1000, t);
      expect(value).toBeGreaterThan(previous);
      expect(value).toBeLessThanOrEqual(1000);
      previous = value;
    }
  });
});

describe("useCountUp", () => {
  let rafCallbacks: FrameRequestCallback[];
  let now: number;
  let reducedMotion: boolean;

  function flushFrame(advanceMs: number) {
    now += advanceMs;
    const callbacks = rafCallbacks;
    rafCallbacks = [];
    act(() => {
      for (const cb of callbacks) cb(now);
    });
  }

  beforeEach(() => {
    rafCallbacks = [];
    now = 0;
    reducedMotion = false;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      rafCallbacks.push(cb);
      return rafCallbacks.length;
    });
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    vi.stubGlobal("matchMedia", (query: string) => ({ media: query, matches: reducedMotion }));
    vi.spyOn(performance, "now").mockImplementation(() => now);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("tweens upward over ~600ms on an increase", () => {
    const { result, rerender } = renderHook(({ value }) => useCountUp(value), {
      initialProps: { value: 100 },
    });
    expect(result.current).toBe(100);

    rerender({ value: 700 });
    expect(rafCallbacks.length).toBe(1);

    flushFrame(150);
    expect(result.current).toBeGreaterThan(100);
    expect(result.current).toBeLessThan(700);

    flushFrame(600);
    expect(result.current).toBe(700);
    expect(rafCallbacks.length).toBe(0);
  });

  it("snaps to a decrease on the next frame, without tweening", () => {
    const { result, rerender } = renderHook(({ value }) => useCountUp(value), {
      initialProps: { value: 500 },
    });

    rerender({ value: 200 });
    flushFrame(0);
    expect(result.current).toBe(200);
    expect(rafCallbacks.length).toBe(0);
  });

  it("snaps to an increase on the next frame under reduced motion", () => {
    reducedMotion = true;
    const { result, rerender } = renderHook(({ value }) => useCountUp(value), {
      initialProps: { value: 100 },
    });

    rerender({ value: 900 });
    flushFrame(0);
    expect(result.current).toBe(900);
    expect(rafCallbacks.length).toBe(0);
  });
});
