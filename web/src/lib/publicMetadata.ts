import { useEffect } from "react";

/** Own the existing head nodes so hydration and client navigation never duplicate them. */
export function usePublicMetadata(title: string | undefined, description: string, path: string, image?: string) {
  useEffect(() => {
    if (!title) return;
    document.title = title;
    const undo: (() => void)[] = [];
    const values = [
      ["meta", "name", "description", "content", description],
      ["link", "rel", "canonical", "href", `https://scenewright.ink${path}`],
      ["meta", "property", "og:type", "content", path.startsWith("/read/") ? "book" : "website"],
      ["meta", "property", "og:title", "content", title],
      ["meta", "property", "og:description", "content", description],
      ["meta", "property", "og:url", "content", `https://scenewright.ink${path}`],
      ["meta", "name", "twitter:title", "content", title],
      ["meta", "name", "twitter:description", "content", description],
      ["meta", "property", "og:image", "content", new URL(image ?? "/brand/scenewright-panel-frame/scenewright-app-icon-512.png", window.location.origin).href],
      ["meta", "name", "twitter:image", "content", new URL(image ?? "/brand/scenewright-panel-frame/scenewright-app-icon-512.png", window.location.origin).href],
    ];
    for (const [tag, key, value, attribute, content] of values) {
      const existing = document.head.querySelector(`${tag}[${key}="${value}"]`);
      const node = existing ?? document.createElement(tag);
      const previous = node.getAttribute(attribute);
      node.setAttribute(key, value);
      node.setAttribute(attribute, content);
      if (!existing) document.head.append(node);
      undo.push(() => {
        if (!existing) node.remove();
        else if (previous === null) node.removeAttribute(attribute);
        else node.setAttribute(attribute, previous);
      });
    }
    return () => {
      undo.forEach(restore => restore());
      // A direct reader request starts with server book metadata, so restoring
      // that snapshot would leak the book title onto the next private/home route.
      document.title = "Scenewright — Your story. Its first comic scene.";
      const canonical = document.head.querySelector('link[rel="canonical"]');
      canonical?.setAttribute("href", "https://scenewright.ink/");
      for (const key of ["description", "og:description", "twitter:description"]) {
        document.head.querySelector(`meta[name="${key}"], meta[property="${key}"]`)?.setAttribute("content", "Turn a short excerpt into a comic with Scenewright, an AI-assisted studio for indie authors. Direct the style and cast, review your pages, and export PDF or CBZ.");
      }
      for (const key of ["og:title", "twitter:title"]) {
        document.head.querySelector(`meta[name="${key}"], meta[property="${key}"]`)?.setAttribute("content", document.title);
      }
      document.head.querySelector('meta[property="og:url"]')?.setAttribute("content", "https://scenewright.ink/");
      document.head.querySelector('meta[property="og:type"]')?.setAttribute("content", "website");
      for (const key of ["og:image", "twitter:image"]) {
        document.head.querySelector(`meta[name="${key}"], meta[property="${key}"]`)?.setAttribute("content", "https://scenewright.ink/brand/scenewright-panel-frame/scenewright-app-icon-512.png");
      }
    };
  }, [title, description, path, image]);
}
