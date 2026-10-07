import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { usePublicMetadata } from "../lib/publicMetadata";
import { publicPages, publicSchema } from "../lib/publicPages";
function Page({ path = "/read/abc" }: { path?: string }) {
  usePublicMetadata("Story — Scenewright", "Public description", path, "/cover.jpg");
  return null;
}
it("updates server head nodes once and clears book metadata on navigation", () => {
  document.head.innerHTML = '<title>Server book</title><link rel="canonical" href="https://scenewright.ink/read/abc"><meta name="description" content="Server description"><meta property="og:type" content="book">';
  const view = render(<Page />);
  expect(document.querySelectorAll("title")).toHaveLength(1);
  expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
  expect(document.title).toBe("Story — Scenewright");
  view.rerender(<Page path="/read/def" />);
  expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe("https://scenewright.ink/read/def");
  view.unmount();
  expect(document.title).toBe("AI Comic Studio for Authors | Scenewright");
  expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe("https://scenewright.ink/");
  expect(document.querySelector('meta[property="og:type"]')?.getAttribute("content")).toBe("website");
  document.head.innerHTML = "";
});
function StaticPage({ path }: { path: string }) {
  const page = publicPages[path];
  usePublicMetadata(page?.title ?? "Scenewright", page?.description ?? "Sign in", path, undefined,
    { noindex: !page, schema: page ? publicSchema(path) : undefined, alternates: path === "/fr" });
  return null;
}
it("replaces localized metadata and schema when navigating to a utility page", () => {
  const view = render(<StaticPage path="/fr" />);
  expect(document.querySelectorAll('link[hreflang]')).toHaveLength(4);
  expect(document.querySelectorAll('#public-schema')).toHaveLength(1);
  expect(document.querySelector('meta[property="og:locale"]')?.getAttribute("content")).toBe("fr_FR");
  expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("index, follow, max-snippet:-1, max-image-preview:large");
  expect(JSON.parse(document.getElementById("public-schema")!.textContent!)["@graph"].some((item: { "@type": string }) => item["@type"] === "WebApplication")).toBe(true);
  view.rerender(<StaticPage path="/legal/terms" />);
  expect(document.title).toBe(publicPages["/legal/terms"].title);
  expect(document.querySelectorAll('meta[property="og:locale"]')).toHaveLength(1);
  expect(document.querySelector('meta[property="og:locale"]')?.getAttribute("content")).toBe("en_US");
  expect(document.querySelectorAll('link[hreflang]')).toHaveLength(0);
  view.rerender(<StaticPage path="/signup" />);
  expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("noindex, follow");
  expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe("https://scenewright.ink/signup");
  expect(document.getElementById("public-schema")).toBeNull();
  expect(document.querySelector('meta[property="og:locale"]')).toBeNull();
  view.rerender(<Page />);
  expect(document.querySelector('meta[name="robots"]')?.getAttribute("content")).toBe("index, follow");
  expect(document.querySelector('meta[property="og:locale"]')).toBeNull();
  view.unmount();
  document.head.innerHTML = "";
});
