import type { PageSummary } from "../../types/api";

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
    <div className="space-y-2 overflow-y-auto pr-1" style={{ maxHeight: "calc(100vh - 260px)" }}>
      <div className="font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
        PAGES ({pages.length})
      </div>
      {pages.map((p) => {
        const isActive = p.page_number === currentPage;
        const src = `/api/projects/${encodeURIComponent(project)}/files/assembly/pages/page_${String(p.page_number).padStart(3, "0")}.png`;

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
              <img
                src={src}
                alt={`Page ${p.page_number}`}
                className="h-full w-full object-contain"
                loading="lazy"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = "none";
                }}
              />
            </div>
            <div className="flex items-center justify-between px-2 py-1">
              <span className="font-meta text-[0.44rem] tracking-[0.14em] text-ink-black/60">
                PAGE {String(p.page_number).padStart(2, "0")}
              </span>
              <span className="font-meta text-[0.40rem] tracking-[0.12em] text-ink-black/40">
                {p.panel_count}p
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
