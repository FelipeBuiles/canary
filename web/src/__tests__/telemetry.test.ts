import { afterEach, describe, expect, it, vi } from "vitest";
import { scrubEvent } from "../telemetry";

describe("PostHog privacy boundary", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("labels browser exceptions with the configured release and environment", () => {
    vi.stubEnv("VITE_CANARY_VERSION", "abc123-dirty");
    vi.stubEnv("VITE_CANARY_ENV", "development");
    const result = scrubEvent({ uuid: "test", event: "$exception", properties: {} });
    expect(result?.properties).toMatchObject({
      environment: "development", release: "abc123-dirty", $release_id: "abc123-dirty", schema_version: 1,
    });
  });
  it("drops automatic product collection", () => {
    expect(scrubEvent({ uuid: "test", event: "$pageview", properties: { $current_url: "private" } })).toBeNull();
  });
  it("retains safe code locations and IDs, drops private error text", () => {
    const result = scrubEvent({ uuid: "test", event: "$exception", properties: {
      distinct_id: "user-123", $current_url: "private", token: "private",
      $exception_list: [{ type: "Error", value: "private", stacktrace: { frames: [{
        filename: "http://localhost/assets/app-123.js?secret=private", lineno: 2, colno: 3, context_line: "private",
      }] } }],
    } });
    expect(JSON.stringify(result)).not.toContain("private");
    expect(result?.properties.distinct_id).toBe("user-123");
    expect(result?.properties.$exception_list[0].stacktrace.frames[0].filename).toBe("/assets/app-123.js");
  });
  it("fails closed on malformed exception payloads", () => {
    expect(scrubEvent({ uuid: "test", event: "$exception", properties: { $exception_list: [null] } })).toBeNull();
  });
});
