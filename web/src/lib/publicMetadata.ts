import { useEffect } from "react";
import { homePaths, PUBLIC_IMAGE, PUBLIC_ORIGIN, publicPages, publicSearchMetadata } from "./publicPages";

interface MetadataOptions { noindex?: boolean; schema?: unknown; alternates?: boolean }
function setNode(tag: string, key: string, value: string, attribute: string, content: string) {
  const node = document.head.querySelector(`${tag}[${key}="${value}"]`) ?? document.createElement(tag);
  node.setAttribute(key, value);
  node.setAttribute(attribute, content);
  if (!node.parentNode) document.head.append(node);
}
function apply(title: string, description: string, path: string, image: string | undefined, options: MetadataOptions, schemaJson?: string) {
  document.title = title;
  const url = PUBLIC_ORIGIN + path;
  const cover = new URL(image ?? PUBLIC_IMAGE, PUBLIC_ORIGIN).href;
  setNode("link", "rel", "canonical", "href", url);
  document.head.querySelectorAll('meta[property^="og:image:"], meta[name="twitter:image:alt"], meta[property="og:locale"]').forEach(node => node.remove());
  for (const [key, content] of Object.entries({ description, robots: "index, follow",
    ...publicSearchMetadata(path), ...(options.noindex ? { robots: "noindex, follow" } : {}),
    "og:type": path.startsWith("/read/") ? "book" : "website", "og:site_name": "Scenewright", "og:title": title,
    "og:description": description, "og:url": url, "og:image": cover,
    "twitter:title": title, "twitter:description": description, "twitter:image": cover, "twitter:card": "summary_large_image",
    "og:image:alt": title, "twitter:image:alt": title, ...(!image ? { "og:image:width": "1200", "og:image:height": "630" } : {}) })) {
    setNode("meta", key.startsWith("og:") ? "property" : "name", key, "content", content);
  }
  document.head.querySelectorAll('link[rel="alternate"][hreflang]').forEach(node => node.remove());
  if (options.alternates) for (const [language, target] of [...Object.entries(homePaths), ["x-default", "/"]]) {
    const link = document.createElement("link");
    link.rel = "alternate"; link.hreflang = language; link.href = PUBLIC_ORIGIN + target;
    document.head.append(link);
  }
  let schema = document.getElementById("public-schema");
  if (schemaJson) {
    if (!schema) { schema = document.createElement("script"); schema.id = "public-schema"; schema.setAttribute("type", "application/ld+json"); document.head.append(schema); }
    schema.textContent = schemaJson;
  } else schema?.remove();
}
/** Own head nodes across server responses, hydration, and client navigation. */
export function usePublicMetadata(title: string | undefined, description: string, path: string, image?: string, options: MetadataOptions = {}) {
  const { noindex, alternates } = options;
  const schemaJson = options.schema === undefined ? undefined : JSON.stringify(options.schema);
  useEffect(() => {
    if (!title) return;
    apply(title, description, path, image, { noindex, alternates }, schemaJson);
    return () => apply(publicPages["/"].title, publicPages["/"].description, "/", undefined, {});
  }, [title, description, path, image, noindex, alternates, schemaJson]);
}
