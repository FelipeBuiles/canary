import type { PageSummary } from "../../types/api";

interface PageNavigatorProps {
  project: string;
  pages: PageSummary[];
  currentPage: number;
  onSelect: (pageNum: number) => void;
}

/**
 * Thumbnails use the rendered page PNGs (written by the compose stage /
 * export), not live preview iframes — a full 2480x3508 document with
 * full-resolution panel images per thumbnail is far too heavy for a rail.
 * They can lag behind unexported edits; the canvas is the live view.
 */
function pageThumbUrl(project: string, pageNumber: number): string {
  const name = `page_${String(pageNumber).padStart(3, "0")}.png`;
  return `/api/projects/${encodeURIComponent(project)}/files/compose/pages/${name}`;
}

export function PageNavigator({
  project,
  pages,
  currentPage,
  onSelect,
}: PageNavigatorProps) {
  return (
    <div className="min-h-0 border-[3px] border-ink-black bg-pulp-paper shadow-[3px_3px_0_0_var(--color-ink-black)] md:flex md:max-h-full md:flex-col">
      <div className="border-b border-ink-black/20 px-2.5 py-2">
        <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
          PAGES
        </div>
      </div>
      <div className="flex gap-2 overflow-x-auto p-2 md:min-h-0 md:flex-1 md:flex-col md:overflow-x-hidden md:overflow-y-auto">
        {pages.map((p) => {
          const isActive = p.page_number === currentPage;

          return (
            <button
              key={p.page_number}
              onClick={() => onSelect(p.page_number)}
              aria-current={isActive ? "page" : undefined}
              className={`group block w-[124px] shrink-0 border-[2px] text-left transition-[background-color,border-color,box-shadow,transform] duration-150 md:w-full ${
                isActive
                  ? "border-hero-red bg-bristol shadow-[2px_2px_0_0_var(--color-outline-ghost)]"
                  : "border-ink-black/25 bg-bristol hover:border-ink-black/55 hover:shadow-[2px_2px_0_0_var(--color-ghost-shadow)]"
              }`}
            >
              <div className="relative aspect-[2480/3508] w-full overflow-hidden bg-[#f3eedf] p-1">
                <span className="absolute inset-0 flex items-center justify-center font-display text-[1.4rem] font-black text-ink-black/15">
                  {p.page_number}
                </span>
                <img
                  src={pageThumbUrl(project, p.page_number)}
                  alt={`Page ${p.page_number} thumbnail`}
                  className="relative h-full w-full object-contain"
                  loading="lazy"
                  onError={(e) => {
                    // No PNG rendered yet — leave the page-number placeholder
                    e.currentTarget.style.display = "none";
                  }}
                />
              </div>
              <div className="flex items-center justify-between border-t border-ink-black/15 px-1.5 py-1.5">
                <span className="font-meta text-[0.54rem] tracking-[0.14em] text-ink-black/62">
                  PAGE {String(p.page_number).padStart(2, "0")}
                </span>
                <span className="font-meta text-[0.5rem] tracking-[0.1em] text-ink-black/38">
                  {p.panel_count}p
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
