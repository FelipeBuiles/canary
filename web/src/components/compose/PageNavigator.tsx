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
    <div className="space-y-3 overflow-y-auto pr-1" style={{ maxHeight: "calc(100vh - 260px)" }}>
      <div className="font-meta text-[0.78rem] tracking-[0.18em] text-ink-black/50">
        PAGES ({pages.length})
      </div>
      {pages.map((p) => {
        const isActive = p.page_number === currentPage;
        const src = pagePreviewUrl(project, p.page_number);

        return (
          <button
            key={p.page_number}
            onClick={() => onSelect(p.page_number)}
            className={`group block w-full border-[2px] text-left transition-colors ${
              isActive
                ? "border-hero-red bg-bristol"
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
            <div className="flex items-center justify-between px-2 py-1">
              <span className="font-meta text-[0.64rem] tracking-[0.14em] text-ink-black/65">
                PAGE {String(p.page_number).padStart(2, "0")}
              </span>
              <span className="font-meta text-[0.58rem] tracking-[0.12em] text-ink-black/45">
                {p.panel_count}p
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
