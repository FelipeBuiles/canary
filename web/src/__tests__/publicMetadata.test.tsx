import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { usePublicMetadata } from "../lib/publicMetadata";
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
  expect(document.title).toBe("Scenewright — Your story. Its first comic scene.");
  expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe("https://scenewright.ink/");
  expect(document.querySelector('meta[property="og:type"]')?.getAttribute("content")).toBe("website");
  document.head.innerHTML = "";
});
