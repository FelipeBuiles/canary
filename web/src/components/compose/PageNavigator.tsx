import type { PageSummary } from "../../types/api";
import { pagePreviewUrl } from "../../api/pages";

interface PageNavigatorProps {
  project: string;
  pages: PageSummary[];
  currentPage: number;
  onSelect: (pageNum: number) => void;
}

export function PageNavigator({
  project,
  pages,
  currentPage,
  onSelect,
}: PageNavigatorProps) {
  return (
    <div className="min-h-0 border-[3px] border-ink-black bg-pulp-paper shadow-[4px_4px_0_0_var(--color-ink-black)] md:flex md:max-h-[calc(100vh-236px)] md:flex-col">
      <div className="border-b border-ink-black/20 px-3 py-2">
        <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
          CONTACT SHEET
        </div>
      </div>
      <div className="flex gap-2 overflow-x-auto p-2 md:min-h-0 md:flex-1 md:flex-col md:overflow-x-hidden md:overflow-y-auto">
        {pages.map((p) => {
          const isActive = p.page_number === currentPage;
          const src = pagePreviewUrl(project, p.page_number);

          return (
            <button
              key={p.page_number}
              onClick={() => onSelect(p.page_number)}
              aria-current={isActive ? "page" : undefined}
              className={`group block w-[124px] shrink-0 border text-left transition-[background-color,border-color,transform] duration-150 md:w-full ${
                isActive
                  ? "border-hero-red bg-bristol"
                  : "border-ink-black/30 bg-bristol hover:border-ink-black/50"
              }`}
            >
              <div className="aspect-[2480/3508] w-full overflow-hidden bg-[#f3eedf] p-1.5">
                <iframe
                  src={src}
                  title={`Page ${p.page_number} preview`}
                  className="pointer-events-none h-full w-full origin-top-left scale-[0.077] border-0 bg-white"
                  style={{ width: 2480, height: 3508 }}
                  loading="lazy"
                />
              </div>
              <div className="flex items-center justify-between border-t border-ink-black/15 px-2 py-1.5">
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
        <button
          type="button"
          className="mt-1 flex h-8 items-center justify-center border border-ink-black/20 bg-bristol font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55 transition-colors hover:bg-surface-container"
        >
          + ADD PAGE
        </button>
      </div>
    </div>
  );
}
