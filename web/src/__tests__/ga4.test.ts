import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Exercise the real route sanitizer and Google command queue without fetching Google.
let append: ReturnType<typeof vi.spyOn>;
let tag: HTMLScriptElement | undefined;
let module: typeof import("../lib/ga4");
function commands(): unknown[][] {
  return ((window as Window & { dataLayer?: unknown[] }).dataLayer ?? []).map(row => Array.from(row as ArrayLike<unknown>));
}
function events(name: string) { return commands().filter(row => row[0] === "event" && row[1] === name); }
function loadTag() { tag?.dispatchEvent(new Event("load")); }

beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv("VITE_CANARY_ENV", "production");
  vi.stubEnv("VITE_GA4_MEASUREMENT_ID", "G-R9Q5LX1E00");
  localStorage.clear();
  window.history.replaceState({}, "", "/");
  Object.assign(window, { dataLayer: [], gtag: undefined });
  tag = undefined;
  append = vi.spyOn(document.head, "append").mockImplementation((...nodes) => { tag = nodes[0] as HTMLScriptElement; });
  // Module reloads should not leave old listeners in this simulated browser.
  const add = window.addEventListener.bind(window);
  vi.spyOn(window, "addEventListener").mockImplementation((type, listener, options) => {
    if (type !== "storage") add(type, listener, options);
  });
  module = await import("../lib/ga4");
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

describe("optional GA4", () => {
  it("never loads Google, queues events, or claims readiness without consent", () => {
    module.trackGa4Pageview("/", false);
    module.trackGa4Signup();
    module.setGa4Consent("declined");
    module.trackGa4Pageview("/pricing", false);
    expect(append).not.toHaveBeenCalled();
    expect(commands()).toEqual([]);
    expect(module.ga4Ready()).toBe(false);
  });

  it.each(["development", "test"])("does not load in %s builds", env => {
    vi.stubEnv("VITE_CANARY_ENV", env);
    module.trackGa4Pageview("/", false);
    module.setGa4Consent("accepted");
    expect(append).not.toHaveBeenCalled();
  });

  it("requires a valid public measurement ID", () => {
    vi.stubEnv("VITE_GA4_MEASUREMENT_ID", "G-evil?url=secret");
    module.trackGa4Pageview("/", false);
    module.setGa4Consent("accepted");
    expect(append).not.toHaveBeenCalled();
  });

  it("retains the first consented landing page while the tag loads and deduplicates route effects", () => {
    module.trackGa4Pageview("/", false);
    module.setGa4Consent("accepted");
    module.trackGa4Pageview("/", false);
    module.trackGa4Pageview("/pricing", false);
    module.trackGa4Pageview("/pricing", false);
    expect(append).toHaveBeenCalledOnce();
    expect(tag?.src).toBe("https://www.googletagmanager.com/gtag/js?id=G-R9Q5LX1E00");
    expect(events("page_view")).toHaveLength(0);
    loadTag();
    expect(events("page_view")).toHaveLength(2);
    module.trackGa4Pageview("/pricing", false);
    expect(events("page_view")).toHaveLength(2);
    module.trackGa4Pageview("/", false);
    expect(events("page_view")).toHaveLength(3);
    expect(commands().find(row => row[0] === "config")?.[2]).toMatchObject({
      send_page_view: false, cookie_domain: "none", allow_google_signals: false, allow_ad_personalization_signals: false,
    });
  });

  it("scrubs private paths, titles, query strings, fragments, and invalid campaign tokens", () => {
    vi.spyOn(document, "referrer", "get").mockReturnValue("https://www.google.com/search?q=private-manuscript");
    document.title = "Private manuscript name";
    window.history.replaceState({}, "", "/project/private-id/pages?utm_source=Google&utm_medium=organic&utm_campaign=private%20manuscript&token=secret#password");
    module.trackGa4Pageview(window.location.pathname, true);
    module.setGa4Consent("accepted");
    loadTag();
    expect(events("page_view")[0][2]).toMatchObject({
      page_location: window.location.origin + "/project/:id/pages", page_title: "Scenewright comic studio",
      page_referrer: "https://www.google.com/", campaign_source: "google", campaign_medium: "organic", campaign_name: "",
    });
    expect(JSON.stringify(commands())).not.toMatch(/private-id|manuscript|password|token=secret/);
    module.trackGa4Signup();
    expect(events("sign_up")).toHaveLength(1);
    expect(events("sign_up")[0][2]).toEqual({ send_to: "G-R9Q5LX1E00" });
  });

  it("drops buffered visits if consent is revoked while Google loads", () => {
    module.trackGa4Pageview("/", false);
    module.setGa4Consent("accepted");
    module.setGa4Consent("declined");
    loadTag();
    module.trackGa4Signup();
    expect(events("page_view")).toHaveLength(0);
    expect(events("sign_up")).toHaveLength(0);
    expect(module.ga4Ready()).toBe(false);
  });

  it("stops collection, removes host analytics cookies, and can be re-enabled", () => {
    module.trackGa4Pageview("/", false);
    module.setGa4Consent("accepted");
    loadTag();
    document.cookie = "_ga=test; Path=/";
    document.cookie = "_ga_R9Q5LX1E00=session; Path=/";
    document.cookie = "session=keep; Path=/";
    module.setGa4Consent("declined");
    module.trackGa4Pageview("/pricing", false);
    module.trackGa4Signup();
    expect(events("page_view")).toHaveLength(1);
    expect(events("sign_up")).toHaveLength(0);
    expect(document.cookie).not.toContain("_ga");
    expect(document.cookie).toContain("session=keep");
    expect((window as unknown as Record<string, unknown>)["ga-disable-G-R9Q5LX1E00"]).toBe(true);
    module.setGa4Consent("accepted");
    expect(events("page_view")).toHaveLength(2);
    expect(module.ga4Ready()).toBe(true);
    expect(localStorage.getItem("scenewright:ga4-consent:v1")).toBe("accepted");
  });

  it("tolerates unavailable preference storage", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => { throw new Error("denied"); });
    module.trackGa4Pageview("/", false);
    expect(() => module.setGa4Consent("accepted")).not.toThrow();
    loadTag();
    expect(events("page_view")).toHaveLength(1);
  });
});
