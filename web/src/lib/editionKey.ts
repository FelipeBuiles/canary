/** A compact stable key for the planned pages an edition was drawn from. */
export function editionKeyFor(project: string, pages: Array<{ page_number: number; revision: number }>): string {
  let hash = 5381;
  for (const { page_number, revision } of pages) {
    for (const char of `${page_number}:${revision};`) hash = ((hash << 5) + hash + char.charCodeAt(0)) | 0;
  }
  return `${project}.${pages.length}.${(hash >>> 0).toString(36)}`;
}
