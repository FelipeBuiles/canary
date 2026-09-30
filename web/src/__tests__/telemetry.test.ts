import { afterEach, describe, expect, it, vi } from "vitest";
import { canonicalPath, maskReplayAttribute, maskReplayText, readAcquisition, scrubEvent } from "../telemetry";

describe("PostHog privacy boundary", () => {
  afterEach(() => vi.unstubAllEnvs());
  it("keeps the configured ingestion token when scrubbing a real SDK pageview", async () => {
    vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_offline_test");
    const { PostHog } = await import("posthog-js/dist/module.no-external");
    const sdk = new PostHog();
    const captured = vi.fn(scrubEvent);
    sdk.init("phc_offline_test", {
      persistence: "memory", capture_pageview: false, capture_pageleave: false,
      autocapture: false, disable_session_recording: true, advanced_disable_decide: true,
      person_profiles: "identified_only",
      before_send: event => { captured(event); return null; }, // Never transmit test events.
    });
    sdk.capture("$pageview", { canonical_path: "/", token: "private", manuscript: "private" });
    const result = captured.mock.results.at(-1)?.value;
    expect(result?.properties).toMatchObject({
      token: "phc_offline_test", $pathname: "/", $lib: "web", $process_person_profile: false,
    });
    expect(result?.properties.distinct_id).toBeTruthy();
    expect(result?.properties.$session_id).toBeTruthy();
    expect(JSON.stringify(result)).not.toContain("private");
  });
  it.each(["$identify", "$exception", "$autocapture", "signup_submitted", "$snapshot"])(
    "keeps ingestion and diagnostic metadata on %s without admitting content", event => {
      vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_offline_test");
      const result = scrubEvent({ uuid: "test", event, properties: {
        token: "private", $session_id: "session-1", $window_id: "window-1", $snapshot_data: [],
        $lib: "web", $lib_version: "1.434.15", $insert_id: "insert-1", $pageview_id: "view-1",
        $browser: "Chrome", $browser_version: 140, $os: "Mac OS X", $os_version: "15.0",
        $browser_language: "en-CA", $device_type: "Desktop", $timezone: "America/Toronto",
        $screen_width: 1920, $viewport_height: 900, $timezone_offset: 240, $is_identified: true,
        $raw_user_agent: "private", $set: { email: "private" }, prompt: "private", title: "private",
        $session_entry_url: "http://localhost/project/private-id/pages?token=private#private",
        $session_entry_referring_domain: "www.reddit.com", $referrer: "https://reddit.com/private",
      } });
      expect(result?.properties).toMatchObject({
        token: "phc_offline_test", $lib: "web", $lib_version: "1.434.15", $pageview_id: "view-1",
        $browser_version: 140, $os_version: "15.0", $browser_language: "en-CA",
        $timezone: "America/Toronto", $screen_width: 1920, $viewport_height: 900, $is_identified: true,
      });
      if (event !== "$snapshot") expect(result?.properties).toMatchObject({
        $session_entry_url: "http://localhost/project/:id/pages",
        $session_entry_pathname: "/project/:id/pages", $session_entry_referring_domain: "reddit.com",
      });
      expect(JSON.stringify(result)).not.toContain("private");
    },
  );
  it("rejects malformed metadata and unknown event types", () => {
    const result = scrubEvent({ uuid: "test", event: "$exception", properties: {
      $screen_width: Infinity, $browser_version: "private", $os: { text: "private" },
      $timezone: "private value?", $is_identified: "private", unknown: "private",
    } });
    expect(result?.properties.$screen_width).toBeUndefined();
    expect(JSON.stringify(result)).not.toContain("private");
    expect(scrubEvent({ uuid: "test", event: "unknown", properties: {} })).toBeNull();
  });
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
  it("reduces page views to route templates without IDs, queries, or referrer URLs", () => {
    const result = scrubEvent({ uuid: "test", event: "$pageview", properties: {
      canonical_path: "/project/:id/pages", $current_url: "http://localhost/project/abc/pages?secret=private",
      $referrer: "https://news.example.com/private-thread", $referring_domain: "www.news.example.com",
      utm_source: "newsletter", utm_campaign: "private campaign", $browser: "Mobile Safari", $os: "iOS",
      $process_person_profile: false, $set_once: { $initial_current_url: "private" },
    } });
    expect(JSON.stringify(result)).not.toContain("private");
    expect(result?.properties).toMatchObject({
      $pathname: "/project/:id/pages", $current_url: `${window.location.origin}/project/:id/pages`,
      $referring_domain: "news.example.com", utm_source: "newsletter", $browser: "Mobile Safari",
      $process_person_profile: false,
    });
    expect(result?.properties.utm_campaign).toBeUndefined();
  });
  it("drops page views that were not reduced to a canonical route", () => {
    expect(scrubEvent({ uuid: "test", event: "$pageview", properties: { canonical_path: "/project/abc?x=1" } })).toBeNull();
  });
  it("keeps click structure without text, attributes, or page IDs", () => {
    window.history.pushState({}, "", "/project/private-id/book?secret=private");
    const result = scrubEvent({ uuid: "test", event: "$rageclick", properties: {
      distinct_id: "user-123", $session_id: "session-1", $window_id: "window-1", $event_type: "click",
      $current_url: "http://localhost/project/private-id/book?secret=private", $el_text: "private",
      $elements_chain: 'button.primary:attr__aria-label="private"href="/project/private-id"nth-child="1"text="private"',
    } });
    window.history.pushState({}, "", "/");
    expect(JSON.stringify(result)).not.toContain("private");
    expect(result?.properties).toMatchObject({
      $current_url: `${window.location.origin}/project/:id/book`, $session_id: "session-1", $event_type: "click",
      $elements_chain: 'button',
    });
  });
  it("keeps replay frames with route-template URLs and no plugin payloads", () => {
    const result = scrubEvent({ uuid: "test", event: "$snapshot", properties: {
      distinct_id: "user-123", $session_id: "session-1", $window_id: "window-1", $snapshot_bytes: 42,
      $current_url: "http://localhost/project/private-id/pages",
      $snapshot_data: [
        { type: 4, data: { href: "http://localhost/project/private-id/pages?secret=private", width: 1, height: 1 } },
        { type: 5, data: { tag: "$url_changed", payload: { href: "http://localhost/read/private-id" } } },
        { type: 6, data: { plugin: "rrweb/network@1", payload: { name: "https://api.example/private" } } },
        { type: 3, data: { source: 2 } },
      ],
    } });
    expect(JSON.stringify(result)).not.toContain("private");
    expect(result?.properties.$snapshot_data).toEqual([
      { type: 4, data: { href: `${window.location.origin}/project/:id/pages`, width: 1, height: 1 } },
      { type: 5, data: { tag: "$url_changed", payload: { href: `${window.location.origin}/read/:id` } } },
      { type: 3, data: { source: 2 } },
    ]);
    expect(scrubEvent({ uuid: "test", event: "$snapshot", properties: { $snapshot_data: [] } })).toBeNull();
  });
  it("masks replay prose including dynamic chrome and rewrites safe links", () => {
    document.body.innerHTML = '<button><span id="chrome">Export</span></button><p id="prose">Private manuscript</p>';
    expect(maskReplayText("Export", document.getElementById("chrome")!)).toBe("******");
    expect(maskReplayText("Private manuscript", document.getElementById("prose")!)).toBe("******* **********");
    expect(maskReplayAttribute("href", "/project/private-id/cast")).toBe(`${window.location.origin}/project/:id/cast`);
    expect(maskReplayAttribute("href", "/assets/index-abc.css")).toBe(`${window.location.origin}/other`);
    expect(maskReplayAttribute("src", "https://cdn.example/private.png?token=private")).toBe("[redacted]");
    expect(maskReplayAttribute("class", "primary")).toBe("[redacted]");
  });
  it("maps every route shape to a bounded template", () => {
    expect(canonicalPath("/", false)).toBe("/");
    expect(canonicalPath("/", true)).toBe("/library");
    expect(canonicalPath("/read/0123abcd", false)).toBe("/read/:id");
    expect(canonicalPath("/project/0123/cast/", true)).toBe("/project/:id/cast");
    expect(canonicalPath("/project/0123/Private-Title", true)).toBe("/project/:id/other");
    expect(canonicalPath("/some/private/path", true)).toBe("/other");
  });
  it("captures first-touch attribution as bounded tokens", () => {
    const location = { search: "?utm_source=Reddit&utm_medium=social&utm_campaign=bad campaign", hostname: "scenewright.ink" };
    expect(readAcquisition(location, "https://www.reddit.com/r/private")).toEqual({
      source: "reddit", medium: "social", referring_domain: "reddit.com",
    });
    expect(readAcquisition({ search: "", hostname: "scenewright.ink" }, "https://scenewright.ink/read/x")).toEqual({ source: "direct" });
    expect(readAcquisition({ search: `?ref=book-${"a".repeat(32)}`, hostname: "scenewright.ink" }, "")).toEqual({ source: "book_referral" });
  });
});


it("scrubs full and incremental serialized DOM content, attributes and unsupported frames", () => {
  const secret = "DISTINCTIVE_UNPUBLISHED_SECRET";
  const result = scrubEvent({ uuid: "test", event: "$snapshot", properties: {
    $session_id: "session-1", $window_id: "window-1", $snapshot_data: [
      { type: 2, timestamp: 1, data: { node: { type: 2, id: 1, tagName: "button", attributes: {
        title: secret, "aria-label": secret, class: secret, style: `background:url(https://${secret}.invalid)`,
        "data-ph-unmask": "true", role: "button", href: `/project/${secret}/pages?token=${secret}`,
      }, childNodes: [{ type: 3, id: 2, textContent: secret }] } } },
      { type: 3, data: { source: 0, texts: [{ id: 2, value: secret }], attributes: [{ id: 1, attributes: { title: secret, role: "button" } }] } },
      { type: 3, data: { source: 5, id: 3, text: secret, isChecked: false } },
      { type: 3, data: { source: 8, rules: [{ rule: secret }] } },
      { type: 5, data: { tag: secret, payload: { secret } } },
      { type: 6, data: { plugin: "console", payload: { secret } } },
    ],
  } });
  expect(JSON.stringify(result)).not.toContain(secret);
  expect(result?.properties.$snapshot_data).toHaveLength(3);
  expect(result?.properties.$snapshot_data[0].data.node.attributes).toEqual({ role: "button", href: `${window.location.origin}/project/:id/pages` });
  expect(maskReplayAttribute("aria-label", secret)).toBe("[redacted]");
  expect(maskReplayAttribute("style", secret)).toBe("[redacted]");
  expect(maskReplayAttribute("src", `https://${secret}.invalid/art`)).toBe("[redacted]");
});


it("drops automatic top-level person properties and opaque compressed replay frames", () => {
  const raw = { uuid: "test", event: "$snapshot", $set_once: { initial_url: "UNPUBLISHED_SECRET" }, properties: {
    $session_id: "session-1", $window_id: "window-1", $snapshot_data: [
      { type: 2, cv: "2024-10", data: "opaque-packed-private-content" },
      { type: 3, cv: "2024-10", data: { source: 0, texts: "packed" } },
    ],
  } };
  const result = scrubEvent(raw);
  expect(JSON.stringify(result)).not.toContain("UNPUBLISHED_SECRET");
  expect(result?.properties.$snapshot_data).toEqual([]);
});
