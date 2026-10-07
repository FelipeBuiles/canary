import { afterEach, describe, expect, it, vi } from "vitest";
import { afterPageLoad } from "../lib/afterPageLoad";
import { scrubEvent } from "../telemetry";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("optional startup work", () => {
  it("waits for load and an idle slot, and cancels work when unmounted", () => {
    vi.spyOn(document, "readyState", "get").mockReturnValue("loading");
    let run: IdleRequestCallback | undefined;
    const idle = vi.fn((callback: IdleRequestCallback) => { run = callback; return 7; });
    const cancel = vi.fn();
    vi.stubGlobal("requestIdleCallback", idle);
    vi.stubGlobal("cancelIdleCallback", cancel);
    const task = vi.fn();
    const cleanup = afterPageLoad(task);
    expect(idle).not.toHaveBeenCalled();
    window.dispatchEvent(new Event("load"));
    expect(idle).toHaveBeenCalledOnce();
    expect(task).not.toHaveBeenCalled();
    run!({ didTimeout: false, timeRemaining: () => 50 });
    expect(task).toHaveBeenCalledOnce();
    cleanup();
    expect(cancel).toHaveBeenCalledWith(7);
  });

  it("has a cancellable fallback when idle callbacks are unavailable", () => {
    vi.useFakeTimers();
    vi.spyOn(document, "readyState", "get").mockReturnValue("complete");
    vi.stubGlobal("requestIdleCallback", undefined);
    const task = vi.fn();
    const cleanup = afterPageLoad(task);
    cleanup();
    vi.runAllTimers();
    expect(task).not.toHaveBeenCalled();
    afterPageLoad(task);
    expect(task).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(task).toHaveBeenCalledOnce();
  });
});

describe("Web Vitals privacy", () => {
  it("retains numbers and the measurement's route without private attribution", () => {
    const result = scrubEvent({ event: "$web_vitals", uuid: "test", properties: {
      $current_url: "http://localhost/project/private-book~private-part/pages?text=private",
      $web_vitals_LCP_value: 2100,
      $web_vitals_INP_value: 120,
      $web_vitals_CLS_value: 0,
      $web_vitals_FCP_value: 700,
      $web_vitals_LCP_event: { entries: [{ url: "/api/private-art" }], attribution: { element: "private manuscript" } },
      manuscript: "private",
    } });
    expect(result?.properties).toMatchObject({
      $pathname: "/project/:id/pages",
      $current_url: "http://localhost/project/:id/pages",
      $web_vitals_LCP_value: 2100, $web_vitals_INP_value: 120,
      $web_vitals_CLS_value: 0, $web_vitals_FCP_value: 700,
    });
    expect(JSON.stringify(result)).not.toContain("private");
    expect(result?.properties.$web_vitals_LCP_event).toBeUndefined();
  });

  it.each([NaN, Infinity, -1, "2100", null])("drops malformed metric values: %s", value => {
    expect(scrubEvent({ event: "$web_vitals", uuid: "test", properties: { $web_vitals_LCP_value: value } })).toBeNull();
  });
});
