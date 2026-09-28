import { afterEach, describe, expect, it, vi } from "vitest";
import { canonicalPath, maskReplayAttribute, maskReplayText, readAcquisition, scrubEvent } from "../telemetry";

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
      $elements_chain: 'button.primary:nth-child="1"',
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
  it("masks replay prose outside interface chrome and rewrites links", () => {
    document.body.innerHTML = '<button><span id="chrome">Export</span></button><p id="prose">Private manuscript</p>';
    expect(maskReplayText("Export", document.getElementById("chrome")!)).toBe("Export");
    expect(maskReplayText("Private manuscript", document.getElementById("prose")!)).toBe("******* **********");
    expect(maskReplayAttribute("href", "/project/private-id/cast")).toBe(`${window.location.origin}/project/:id/cast`);
    expect(maskReplayAttribute("href", "/assets/index-abc.css")).toBe(`${window.location.origin}/assets/index-abc.css`);
    expect(maskReplayAttribute("src", "https://cdn.example/private.png?token=private")).toBe("https://cdn.example");
    expect(maskReplayAttribute("class", "primary")).toBe("primary");
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
