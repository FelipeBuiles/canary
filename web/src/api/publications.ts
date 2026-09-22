export interface Publication {
  id: string;
  version: string;
  title: string;
  author: string;
  description: string;
  allow_feature: boolean;
  featured: boolean;
  published_at: string;
  pages: { number: number; width: number; height: number; url: string; spread_role?: "single" | "left" | "right" | "spread" }[];
}

export async function publicBook(id: string, signal?: AbortSignal): Promise<Publication> {
  const response = await fetch(`/api/public/books/${encodeURIComponent(id)}`, { signal });
  if (!response.ok) throw new Error(response.status === 404 ? "This book is no longer public." : "The book could not be loaded. Try again.");
  return response.json();
}
