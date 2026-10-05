import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CaptureResult } from "posthog-js/dist/module.no-external";

vi.mock("posthog-js/dist/exception-autocapture", () => ({}));
vi.mock("posthog-js/dist/posthog-recorder", () => ({}));

/** Run Canary's initialization with the real SDK, intercepting all ingestion. */
async function loadPage() {
  vi.resetModules();
  const { default: sdk } = await import("posthog-js/dist/module.no-external");
  const events: CaptureResult[] = [];
  const init = sdk.init.bind(sdk);
  vi.spyOn(sdk, "init").mockImplementation((key, config) => init(key, {
    ...config,
    autocapture: false,
    capture_exceptions: false,
    disable_session_recording: true,
    advanced_disable_decide: true,
    before_send: event => {
      const clean = typeof config?.before_send === "function" ? config.before_send(event) : event;
      if (clean) events.push(clean);
      return null; // Never transmit test events.
    },
  }));
  const telemetry = await import("../telemetry");
  return { sdk, events, ...telemetry };
}

describe("persistent PostHog identity", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_offline_test");
    vi.stubEnv("VITE_POSTHOG_HOST", "https://us.i.posthog.com");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it.each([true, false])("keeps the same device across reloads when auth precedes initialization: %s", async earlyAuth => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const anonymousIds: string[] = [];
    for (let reload = 0; reload < 2; reload++) {
      const page = await loadPage();
      if (earlyAuth) page.setTelemetryUser("account-123");
      await page.initTelemetry();
      // Only the first sign-in merges the persisted anonymous visit.
      anonymousIds.push(page.sdk.get_property("$device_id") as string);
      if (!earlyAuth) page.setTelemetryUser("account-123");
      page.sdk.capture("$pageview", { canonical_path: "/library" });

      expect(page.sdk.get_distinct_id()).toBe("account-123");
      const identity = page.events.find(event => event.event === "$identify");
      if (reload === 0) expect(identity?.properties).toMatchObject({
        distinct_id: "account-123", $anon_distinct_id: anonymousIds[0],
      });
      else expect(identity).toBeUndefined();
      expect(page.events.at(-1)?.properties).toMatchObject({
        distinct_id: "account-123", $process_person_profile: true, $is_identified: true,
      });
    }
    expect(anonymousIds[0]).toBeTruthy();
    expect(anonymousIds[1]).toBe(anonymousIds[0]);
    expect(warn).not.toHaveBeenCalled();
  });

  it("merges the initial anonymous visit and isolates account changes", async () => {
    const page = await loadPage();
    await page.initTelemetry();
    const firstAnonymous = page.sdk.get_distinct_id();
    page.sdk.capture("$pageview", { canonical_path: "/" });
    expect(page.events.at(-1)?.properties).toMatchObject({
      distinct_id: firstAnonymous, $process_person_profile: false,
    });

    page.setTelemetryUser("account-123");
    page.setTelemetryUser("account-456");
    page.sdk.capture("$pageview", { canonical_path: "/library" });
    expect(page.events.at(-1)?.properties).toMatchObject({
      distinct_id: "account-456", $process_person_profile: true,
    });
    expect(page.events.filter(event => event.event === "$identify").map(event => event.properties.distinct_id))
      .toEqual(["account-123", "account-456"]);
    const identities = page.events.filter(event => event.event === "$identify");
    expect(identities[0].properties.$anon_distinct_id).toBe(firstAnonymous);
    expect(identities[1].properties.$anon_distinct_id).not.toBe(firstAnonymous);
    expect(identities[1].properties.$anon_distinct_id).not.toBe("account-123");

    page.setTelemetryUser(null);
    const signedOutAnonymous = page.sdk.get_distinct_id();
    expect(signedOutAnonymous).not.toBe(firstAnonymous);
    expect(signedOutAnonymous).not.toBe("account-456");
    page.sdk.capture("$pageview", { canonical_path: "/" });
    expect(page.events.at(-1)?.properties).toMatchObject({
      distinct_id: signedOutAnonymous, $process_person_profile: false,
    });
  });

  it("preserves anonymous identity across page loads and clears expired account identity", async () => {
    const first = await loadPage();
    await first.initTelemetry();
    const anonymous = first.sdk.get_distinct_id();
    const reload = await loadPage();
    await reload.initTelemetry();
    expect(reload.sdk.get_distinct_id()).toBe(anonymous);
    reload.setTelemetryUser("account-123");

    const expired = await loadPage();
    expired.setTelemetryUser(null);
    await expired.initTelemetry();
    expect(expired.sdk.get_distinct_id()).not.toBe("account-123");
    expect(expired.sdk.get_property("$user_state")).toBe("anonymous");
  });

  it("uses memory without anonymous merging when localStorage is denied", async () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => { throw new Error("denied"); });
    const page = await loadPage();
    await page.initTelemetry();
    page.setTelemetryUser("account-123");
    expect(page.sdk.config.persistence).toBe("memory");
    expect(page.events.find(event => event.event === "$identify")?.properties).not.toHaveProperty("$anon_distinct_id");
  });
});
