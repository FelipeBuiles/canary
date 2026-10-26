import type { LanguageCode } from "../locales/languages";
import { SHOWCASE_SHELF } from "./showcaseShelf";

/** Build-time public origin; mirrors the server's SCENEWRIGHT_PUBLIC_URL. */
export const PUBLIC_ORIGIN = (import.meta.env.VITE_PUBLIC_URL as string | undefined)?.replace(/\/$/, "") || "https://scenewright.ink";
/** The curated Kaitlin Out of Space showcase book used by the example page. */
export const KAITLIN_EXAMPLE_BOOK_ID = "df3a1b400a444815bddeca430360f0d9";
export const PUBLIC_IMAGE = "/marketing/scenewright-social.png";
export interface PublicPageMetadata {
  title: string;
  description: string;
  language: LanguageCode;
}
export const publicPages: Record<string, PublicPageMetadata> = {
  "/": { title: "Turn Your Novel into a Comic with AI | Scenewright", description: "Turn a chapter or a whole novel into a finished comic. Choose the look and cast, review every page, and export PDF or CBZ. EPUB, PDF or TXT in.", language: "en" },
  "/es": { title: "Convierte tu novela en cómic con IA | Scenewright", description: "Convierte un capítulo o una novela entera en un cómic terminado. Elige el estilo y los personajes, revisa cada página y exporta PDF o CBZ.", language: "es" },
  "/fr": { title: "Transformez votre roman en BD avec l’IA | Scenewright", description: "Transformez un chapitre ou un roman entier en BD terminée. Choisissez le style et les personnages, révisez chaque page et exportez en PDF ou CBZ.", language: "fr" },
  "/how-it-works": { title: "How to Turn Your Story into Comic Pages | Scenewright", description: "Learn the Scenewright workflow: choose a scene, direct its style and cast, review comic pages, and export a PDF or CBZ book.", language: "en" },
  "/pricing": { title: "Pricing and Generation Credits | Scenewright", description: "Scenewright uses prepaid generation credits, with packs from US$12 and no subscription. Review credit estimates before generating or redrawing pages.", language: "en" },
  "/guides/turn-a-novel-into-a-comic": { title: "How to Turn a Novel into a Comic: A Practical Guide | Scenewright", description: "Choose a manageable scene, turn prose into visual beats, establish character references, review continuity and lettering, and export your comic.", language: "en" },
  "/examples/kaitlin-out-of-space": { title: "Kaitlin Out of Space: Comic Adaptation Example | Scenewright", description: "Compare three pages from a Scenewright adaptation of Krishan Coupland’s Kaitlin Out of Space. Read the original story and the finished comic.", language: "en" },
  "/about": { title: "About Scenewright — A Comic Studio for Authors", description: "Scenewright is an AI-assisted comic adaptation studio for authors. Learn what it does, what needs human review, and how to contact us.", language: "en" },
  "/legal/terms": { title: "Terms of Service | Scenewright", description: "Read Scenewright’s terms of service, including accounts, uploaded material, generated content, payments, and use of the service.", language: "en" },
  "/legal/privacy": { title: "Privacy Policy | Scenewright", description: "Read how Scenewright handles account information, uploaded manuscripts, generated content, payments, and privacy requests.", language: "en" },
  "/legal/acceptable-use": { title: "Acceptable Use and Reporting | Scenewright", description: "Read Scenewright’s acceptable use policy and learn how to report prohibited content or rights concerns.", language: "en" },
};
export const homePaths = { en: "/", es: "/es", fr: "/fr" } as const;
/** Shared by prerendering and navigation; applies only to our public site copy. */
export function publicSearchMetadata(path: string): Record<string, string> {
  const page = publicPages[path];
  if (!page) return {};
  const locales = { en: "en_US", es: "es_ES", fr: "fr_FR" } as const;
  return {
    robots: "index, follow, max-snippet:-1, max-image-preview:large",
    "og:locale": locales[page.language],
  };
}
export const isPublicHome = (path: string) => Object.values(homePaths).includes(path as typeof homePaths[LanguageCode]);
export function publicSchema(path: string) {
  const page = publicPages[path];
  if (!page) return undefined;
  const organization = { "@type": "Organization", "@id": `${PUBLIC_ORIGIN}/#organization`, name: "Scenewright", url: PUBLIC_ORIGIN, email: "hello@scenewright.ink" };
  const graph: Record<string, unknown>[] = [organization, {
    "@type": "WebSite", "@id": `${PUBLIC_ORIGIN}/#website`, name: "Scenewright", url: PUBLIC_ORIGIN,
    publisher: { "@id": organization["@id"] }, inLanguage: ["en", "es", "fr"],
  }];
  if (isPublicHome(path)) graph.push({ "@type": "WebApplication", "@id": `${PUBLIC_ORIGIN}/#application`, name: "Scenewright", url: PUBLIC_ORIGIN,
    applicationCategory: "DesignApplication", operatingSystem: "Web browser", description: page.description,
    creator: { "@id": organization["@id"] }, featureList: ["EPUB, PDF and TXT input", "Style and cast direction", "Comic page review", "PDF and CBZ export"] });
  if (isPublicHome(path)) graph.push({ "@type": "ItemList", "@id": `${PUBLIC_ORIGIN}${path}#books`, name: "Books made with Scenewright",
    itemListElement: SHOWCASE_SHELF.map((book, index) => ({ "@type": "ListItem", position: index + 1, item: {
      "@type": "Book", name: book.title, url: `${PUBLIC_ORIGIN}/read/${book.id}`, image: PUBLIC_ORIGIN + book.cover,
      numberOfPages: book.pages, author: { "@type": "Person", name: book.author }, bookFormat: "https://schema.org/GraphicNovel" } })) });
  graph.push({ "@type": path.startsWith("/guides/") ? "Article" : "WebPage", "@id": `${PUBLIC_ORIGIN}${path}#page`, url: PUBLIC_ORIGIN + path,
    name: page.title, ...(path.startsWith("/guides/") ? { headline: page.title, author: { "@id": organization["@id"] } } : {}),
    description: page.description, inLanguage: page.language, isPartOf: { "@id": `${PUBLIC_ORIGIN}/#website` } });
  if (path === "/examples/kaitlin-out-of-space") graph.push({ "@type": "CreativeWork", name: "Kaitlin Out of Space comic adaptation",
    url: `${PUBLIC_ORIGIN}/read/${KAITLIN_EXAMPLE_BOOK_ID}`, isBasedOn: { "@type": "CreativeWork", name: "Kaitlin Out of Space",
      author: { "@type": "Person", name: "Krishan Coupland" }, url: "https://krishancoupland.co.uk/portfolio/kaitlin-out-of-space/", license: "https://creativecommons.org/publicdomain/zero/1.0/" } });
  return { "@context": "https://schema.org", "@graph": graph };
}
