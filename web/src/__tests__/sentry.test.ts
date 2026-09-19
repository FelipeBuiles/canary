import * as Sentry from "@sentry/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initSentry, setSentryUser } from "../sentry";

vi.mock("@sentry/react", () => ({
  init: vi.fn(),
  replayIntegration: vi.fn(() => ({ name: "Replay" })),
  setUser: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("VITE_SENTRY_DSN", "https://public@example.invalid/1");
  vi.stubEnv("VITE_SENTRY_TRACES_SAMPLE_RATE", "0");
  vi.stubEnv("VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE", "0");
});

afterEach(() => vi.unstubAllEnvs());

describe("Sentry SDK upgrade contract", () => {
  it("does not start telemetry without a DSN", () => {
    vi.stubEnv("VITE_SENTRY_DSN", "");
    initSentry();
    expect(Sentry.init).not.toHaveBeenCalled();
    expect(Sentry.replayIntegration).not.toHaveBeenCalled();
  });

  it("keeps PII, tracing, and replay disabled by default", () => {
    initSentry();
    expect(Sentry.init).toHaveBeenCalledWith(expect.objectContaining({
      sendDefaultPii: false,
      tracesSampleRate: 0,
      replaysSessionSampleRate: 0,
      replaysOnErrorSampleRate: 0,
      integrations: [],
    }));
    expect(Sentry.replayIntegration).not.toHaveBeenCalled();
  });

  it.each([
    ["NaN", "Infinity", 0, 0],
    ["-1", "-0.5", 0, 0],
    ["2", "3", 1, 1],
    ["0.25", "0.1", 0.25, 0.1],
  ])("bounds configured sample rates (%s, %s)", (trace, replay, expectedTrace, expectedReplay) => {
    vi.stubEnv("VITE_SENTRY_TRACES_SAMPLE_RATE", trace);
    vi.stubEnv("VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE", replay);
    initSentry();
    expect(Sentry.init).toHaveBeenCalledWith(expect.objectContaining({
      tracesSampleRate: expectedTrace,
      replaysOnErrorSampleRate: expectedReplay,
      replaysSessionSampleRate: 0,
    }));
    if (expectedReplay > 0) {
      expect(Sentry.replayIntegration).toHaveBeenCalledWith({ maskAllText: true, blockAllMedia: true });
    } else {
      expect(Sentry.replayIntegration).not.toHaveBeenCalled();
    }
  });

  it("redacts sensitive headers without dropping unrelated request context", async () => {
    initSentry();
    const beforeSend = vi.mocked(Sentry.init).mock.calls[0]?.[0]?.beforeSend;
    expect(beforeSend).toBeTypeOf("function");
    if (!beforeSend) throw new Error("Sentry header redaction is not configured");
    const event = { type: undefined, request: { headers: {
      Authorization: "Bearer private", Cookie: "session=private",
      "X-API-Key": "private", "x-canary-OPS-token": "private",
      "Content-Type": "application/json",
    } } };
    expect(await beforeSend(event, {})).toEqual({ type: undefined, request: { headers: {
      Authorization: "[Filtered]", Cookie: "[Filtered]",
      "X-API-Key": "[Filtered]", "x-canary-OPS-token": "[Filtered]",
      "Content-Type": "application/json",
    } } });
    expect(await beforeSend({ type: undefined }, {})).toEqual({ type: undefined });
  });

  it("clears the telemetry identity on sign-out", () => {
    setSentryUser("user-id");
    setSentryUser(null);
    expect(Sentry.setUser).toHaveBeenNthCalledWith(1, { id: "user-id" });
    expect(Sentry.setUser).toHaveBeenNthCalledWith(2, null);
  });
});
