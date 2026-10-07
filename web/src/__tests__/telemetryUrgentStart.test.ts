import { afterEach, expect, it, vi } from "vitest";

vi.mock("posthog-js/dist/exception-autocapture", () => ({}));
vi.mock("posthog-js/dist/posthog-recorder", () => ({}));
vi.mock("posthog-js/dist/web-vitals", () => ({}));
// The idle slot never arrives, as when a visitor leaves right after an error.
vi.mock("../lib/afterPageLoad", () => ({ afterPageLoad: () => () => {} }));

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

it("loads telemetry immediately when an error is reported before idle", async () => {
  vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_offline_test");
  vi.stubEnv("VITE_POSTHOG_HOST", "https://us.i.posthog.com");
  const { default: sdk } = await import("posthog-js/dist/module.no-external");
  const init = vi.spyOn(sdk, "init").mockImplementation(() => sdk);
  const captured = vi.spyOn(sdk, "captureException").mockImplementation(() => undefined);
  const telemetry = await import("../telemetry");
  const started = telemetry.initTelemetry();
  const pending = await Promise.race([started.then(() => false), new Promise(resolve => setTimeout(() => resolve(true), 50))]);
  expect(pending).toBe(true);
  telemetry.captureUiError(new Error("startup failure"));
  await started;
  expect(init).toHaveBeenCalled();
  await vi.waitFor(() => expect(captured).toHaveBeenCalled());
});
