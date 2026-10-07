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
  it("keeps only the latest preview outside event history and ignores stale clears", () => {
    usePipelineStore.getState().connect("book~one");
    const source = FakeEventSource.instances.at(-1)!;
    const emit = (event: object) => source.onmessage!({ data: JSON.stringify(event) });
    for (let index = 0; index < 3; index += 1) emit({ type: "image_preview", target: "page:1", request_id: "current",
      preview_index: index, image_url: `data:image/webp;base64,${index}` });
    emit({ type: "image_preview", target: "page:1", request_id: "current", preview_index: 0, image_url: "data:image/webp;base64,old" });
    expect(usePipelineStore.getState().imagePreviews["page:1"].preview_index).toBe(2);
    expect(usePipelineStore.getState().events).toEqual([]);
    emit({ type: "image_preview_clear", target: "page:1", request_id: "earlier" });
    expect(usePipelineStore.getState().imagePreviews["page:1"]).toBeTruthy();
    emit({ type: "image_preview_clear", target: "page:1", request_id: "current" });
    expect(usePipelineStore.getState().imagePreviews).toEqual({});
    emit({ type: "image_preview", target: "page:1", request_id: "current", preview_index: 0, image_url: "data:image/webp;base64,new" });
    usePipelineStore.getState().connect("other-book~one");
    expect(usePipelineStore.getState().imagePreviews).toEqual({});
  });

  it("holds only completed pixels from a finished job until the card releases them", () => {
    usePipelineStore.getState().connect("book~one");
    const source = FakeEventSource.instances.at(-1)!;
    const emit = (event: object) => source.onmessage!({ data: JSON.stringify(event) });
    emit({ type: "image_preview", target: "a", request_id: "done", preview_index: 3, image_url: "data:image/webp;base64,a" });
    emit({ type: "image_preview", target: "b", request_id: "draft", preview_index: 1, image_url: "data:image/webp;base64,b" });
    emit({ type: "image_preview_clear", target: "a", request_id: "done", settled: true });
    emit({ type: "image_preview_clear", target: "b", request_id: "draft", settled: true });
    expect(usePipelineStore.getState().imagePreviews.a.settled).toBe(true);
    expect(usePipelineStore.getState().imagePreviews.b).toBeUndefined();
    usePipelineStore.getState().releaseImagePreview("a", "other");
    expect(usePipelineStore.getState().imagePreviews.a).toBeTruthy();
    usePipelineStore.getState().releaseImagePreview("a", "done");
    expect(usePipelineStore.getState().imagePreviews.a).toBeUndefined();
  });

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
