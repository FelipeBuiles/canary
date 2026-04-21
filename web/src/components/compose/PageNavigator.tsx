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
    <div className="min-h-0 border-[2px] border-ink-black bg-bristol shadow-[4px_4px_0_0_var(--color-ghost-shadow)] md:flex md:max-h-[calc(100vh-236px)] md:flex-col">
      <div className="flex items-center justify-between border-b-[2px] border-ink-black bg-pulp-paper px-3 py-2">
        <div>
          <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">
            CONTACT SHEET
          </div>
          <div className="font-display text-[1rem] font-bold leading-none tracking-[-0.02em] text-ink-black">
            Pages
          </div>
        </div>
        <div className="border-[2px] border-ink-black bg-bristol px-2 py-1 font-meta text-[0.52rem] tracking-[0.14em] text-ink-black/60">
          {pages.length}
        </div>
      </div>
      <div className="flex gap-3 overflow-x-auto p-3 md:min-h-0 md:flex-1 md:flex-col md:overflow-x-hidden md:overflow-y-auto">
        {pages.map((p) => {
          const isActive = p.page_number === currentPage;
          const src = pagePreviewUrl(project, p.page_number);

          return (
            <button
              key={p.page_number}
              onClick={() => onSelect(p.page_number)}
              aria-current={isActive ? "page" : undefined}
              className={`group block w-[132px] shrink-0 border-[2px] text-left transition-[background-color,border-color,transform] duration-150 hover:-translate-y-0.5 md:w-full ${
                isActive
                  ? "border-hero-red bg-bristol shadow-[3px_3px_0_0_var(--color-hero-red)]"
                  : "border-ink-black/30 bg-pulp-paper hover:border-ink-black"
              }`}
            >
              <div className="aspect-[2480/3508] w-full overflow-hidden bg-ink-black/5">
                <iframe
                  src={src}
                  title={`Page ${p.page_number} preview`}
                  className="h-full w-full origin-top-left scale-[0.087] border-0 bg-white pointer-events-none"
                  style={{ width: 2480, height: 3508 }}
                  loading="lazy"
                />
              </div>
              <div className="flex items-center justify-between border-t border-ink-black/20 px-2 py-1">
                <span className="font-meta text-[0.58rem] tracking-[0.12em] text-ink-black/65">
                  PAGE {String(p.page_number).padStart(2, "0")}
                </span>
                <span className="font-meta text-[0.52rem] tracking-[0.1em] text-ink-black/45">
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
