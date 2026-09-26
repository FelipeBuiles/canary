export interface PublicationPage { number: number; width: number; height: number; url: string; spread_role?: "single" | "left" | "right" | "spread" }

/** Reader languages; "source" is the book's original copy. */
export type { LetteringLocale as PublicationLocale } from "../locales/languages";
import type { LetteringLocale as PublicationLocale } from "../locales/languages";

export interface Publication {
  id: string;
  version: string;
  title: string;
  author: string;
  description: string;
  allow_feature: boolean;
  featured: boolean;
  published_at: string;
  source_credit?: { title: string; author: string; source_url: string; license: string; license_url: string } | null;
  pages: PublicationPage[];
  /** Editable-lettering books only: the language of `pages`. Baked books have none. */
  locale?: PublicationLocale;
  /** Other complete languages frozen with this version, same page numbers. */
  translations?: { locale: Exclude<PublicationLocale, "source">; pages: PublicationPage[] }[];
  /** Publish response only: languages left out, with the reason. */
  unpublished_locales?: Partial<Record<Exclude<PublicationLocale, "source">, string>>;
}

export interface PublicationLanguage { locale: PublicationLocale; pages: PublicationPage[] }

/** Every published language, primary first; empty when the book has no language choice. */
export function publicationLanguages(book: Publication): PublicationLanguage[] {
  if (!book.locale) return [];
  return [{ locale: book.locale, pages: book.pages }, ...(book.translations ?? [])];
}

export async function publicBook(id: string, signal?: AbortSignal): Promise<Publication> {
  const response = await fetch(`/api/public/books/${encodeURIComponent(id)}`, { signal });
  if (!response.ok) throw new Error(response.status === 404 ? "This book is no longer public." : "The book could not be loaded. Try again.");
  return response.json();
}
