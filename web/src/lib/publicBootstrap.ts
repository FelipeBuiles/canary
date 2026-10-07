import type { ShortStory } from "../types/api";
import type { Publication } from "../api/publications";
import type { LanguageCode } from "../locales/languages";

export interface PublicBootstrap {
  prerendered?: boolean;
  language?: LanguageCode;
  stories?: ShortStory[];
  story?: { code: string; text: string };
  book?: Publication;
}
let initial: PublicBootstrap | undefined;
export function setPublicBootstrap(data: PublicBootstrap) { initial = data; }
export function getPublicBootstrap(): PublicBootstrap | undefined {
  if (initial) return initial;
  if (typeof document === "undefined") return undefined;
  const node = document.getElementById("public-bootstrap");
  if (node?.textContent) initial = JSON.parse(node.textContent) as PublicBootstrap;
  return initial;
}
