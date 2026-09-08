import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PIPELINE_EVENT_LIMIT, usePipelineStore } from "../store/pipeline";

vi.mock("../api/queryClient", () => ({ queryClient: { invalidateQueries: vi.fn() } }));
vi.mock("../lib/stageProgress", () => ({ applyPipelineEvent: vi.fn() }));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn();
  constructor() { FakeEventSource.instances.push(this); }
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  usePipelineStore.getState().disconnect();
  usePipelineStore.getState().clearEvents();
});
afterEach(() => {
  usePipelineStore.getState().disconnect();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("pipeline recovery", () => {
  it("backs off 1s, 2s, 4s until an actual connection succeeds", () => {
    usePipelineStore.getState().connect("demo");
    for (const delay of [1000, 2000, 4000]) {
      const count = FakeEventSource.instances.length;
      FakeEventSource.instances.at(-1)!.onerror!();
      vi.advanceTimersByTime(delay - 1);
      expect(FakeEventSource.instances).toHaveLength(count);
      vi.advanceTimersByTime(1);
      expect(FakeEventSource.instances).toHaveLength(count + 1);
    }
    FakeEventSource.instances.at(-1)!.onopen!();
    FakeEventSource.instances.at(-1)!.onerror!();
    vi.advanceTimersByTime(1000);
    expect(FakeEventSource.instances).toHaveLength(5);
  });

  it("bounds event history and discards old-source events after navigation", () => {
    usePipelineStore.getState().connect("first");
    const old = FakeEventSource.instances[0];
    for (let index = 0; index < PIPELINE_EVENT_LIMIT + 25; index += 1) {
      old.onmessage!({ data: JSON.stringify({ type: "progress", message: String(index) }) });
    }
    expect(usePipelineStore.getState().events).toHaveLength(PIPELINE_EVENT_LIMIT);
    expect(usePipelineStore.getState().events[0].message).toBe("25");
    old.onerror!();
    usePipelineStore.getState().connect("second");
    old.onmessage!({ data: JSON.stringify({ type: "progress", message: "private old data" }) });
    expect(usePipelineStore.getState().events).toEqual([]);
    vi.advanceTimersByTime(30_000);
    expect(FakeEventSource.instances).toHaveLength(2);
  });
});
