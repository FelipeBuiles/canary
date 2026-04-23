import { useReflowSinglePage } from "../../api/queries";
import { useComposeStore } from "../../store/compose";
import type { ComicPage, PagePanel } from "../../types/api";
import { pagePreviewUrl } from "../../api/pages";
import { cn } from "../../lib/cn";

const LAYOUT_OPTIONS = [
  {
    id: "3x2",
    label: "3 × 2 CLASSIC",
    description: "Equal panels, reading order",
    grid: [
      ["p1", "p2", "p3"],
      ["p4", "p5", "p6"],
    ],
  },
  {
    id: "splash+4",
    label: "SPLASH + 4",
    description: "Hero panel at top",
    grid: [
      ["hero", "hero", "hero"],
      ["p1", "p2", "p3"],
    ],
  },
  {
    id: "wide_opening",
    label: "WIDE OPENING",
    description: "Cinematic wide band",
    grid: [
      ["wide", "wide"],
      ["p1", "p2"],
      ["p3", "p4"],
    ],
  },
  {
    id: "vertical_trio",
    label: "VERTICAL TRIO",
    description: "Three tall columns",
    grid: [["p1", "p2", "p3"]],
  },
] as const;

interface TryLayoutsModalProps {
  project: string;
  pageNum: number;
  page: ComicPage | undefined;
  onClose: () => void;
}

export function TryLayoutsModal({ project, pageNum, page, onClose }: TryLayoutsModalProps) {
  const reflowMut = useReflowSinglePage();
  const pushUndo = useComposeStore((s) => s.pushUndo);

  function handleApply(presetId: string) {
    if (!page) return;
    pushUndo(page);
    reflowMut.mutate(
      { project, pageNum, layoutPreset: presetId },
      { onSuccess: onClose },
    );
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center bg-ink-black/45 px-6 py-10 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[1320px] border-[3px] border-ink-black bg-pulp-paper shadow-[0_0_0_1px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-6 border-b border-ink-black/15 px-8 py-8">
          <div className="min-w-0">
            <div className="font-meta text-[0.76rem] tracking-[0.28em] text-hero-red/80">
              NON-DESTRUCTIVE · THIS PAGE ONLY
            </div>
            <div className="mt-2 font-display text-[3.15rem] font-black uppercase leading-none tracking-[-0.06em] text-ink-black">
              TRY LAYOUTS — PAGE {String(pageNum).padStart(2, "0")}
            </div>
            <div className="mt-4 max-w-[58rem] border-l-[4px] border-hero-red/80 pl-4 text-[0.98rem] leading-8 text-ink-black/78">
              Reflow only this page. The rest of your comic is untouched. Unlike panels-per-page dropdown,
              nothing gets rewritten until you commit.
            </div>
          </div>
          <button
            onClick={onClose}
            className="inline-flex h-11 items-center gap-3 border border-ink-black/20 bg-bristol px-5 font-meta text-[0.72rem] tracking-[0.18em] text-ink-black transition-colors hover:bg-surface-container"
          >
            × CLOSE
          </button>
        </div>

        <div className="grid gap-4 px-8 py-6 lg:grid-cols-4">
          {LAYOUT_OPTIONS.map((layout) => {
            return (
              <div
                key={layout.id}
                className="flex min-h-[560px] flex-col border border-ink-black/20 bg-[#f4eed9] p-4"
              >
                <LayoutPreview project={project} pageNum={pageNum} page={page} grid={layout.grid} />
                <div className="mt-4 font-meta text-[0.9rem] tracking-[0.22em] text-ink-black">
                  {layout.label}
                </div>
                <div className="mt-1 text-[0.88rem] text-ink-black/42">
                  {layout.description}
                </div>
                <button
                  onClick={() => handleApply(layout.id)}
                  disabled={reflowMut.isPending}
                  className="mt-4 inline-flex h-10 items-center justify-center border border-[#9e4734] bg-[#a84a35] px-4 font-meta text-[0.68rem] tracking-[0.18em] text-bristol transition-colors hover:bg-[#943c28] disabled:opacity-50"
                >
                  APPLY TO THIS PAGE
                </button>
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-dashed border-ink-black/20 px-8 py-4">
          <span className="font-meta text-[0.6rem] tracking-[0.12em] text-ink-black/38">
            Existing "panels-per-page" dropdown rewrites every page. This one doesn’t.
          </span>
          <button
            type="button"
            className="inline-flex h-10 items-center border border-ink-black/20 bg-bristol px-5 font-meta text-[0.66rem] tracking-[0.16em] text-ink-black/70 transition-colors hover:bg-surface-container"
          >
            APPLY VARIANT GLOBALLY INSTEAD…
          </button>
        </div>
      </div>
    </div>
  );
}

function LayoutPreview({
  project,
  pageNum,
  page,
  grid,
}: {
  project: string;
  pageNum: number;
  page: ComicPage | undefined;
  grid: readonly (readonly string[])[];
}) {
  const pagePreview = pagePreviewUrl(project, pageNum);
  const panels = page?.panels ?? [];
  const frameCells = grid.flat();
  const seen = new Set<string>();

  function resolvePanel(cell: string, index: number): PagePanel | undefined {
    if (cell === "hero" || cell === "wide") return panels[0];
    const matched = cell.match(/^p(\d+)$/);
    if (matched) return panels[Number(matched[1]) - 1];
    return panels[index];
  }

  return (
    <div className="relative aspect-[0.72] w-full overflow-hidden border border-ink-black/25 bg-[#f8f4e7] p-3">
      <div className="absolute inset-0 opacity-[0.07]">
        <iframe
          src={pagePreview}
          title={`Page ${pageNum} layout preview`}
          className="pointer-events-none h-full w-full border-0"
          loading="lazy"
        />
      </div>
      <div
        className="relative z-10 grid h-full gap-[4px]"
        style={{
          gridTemplateColumns: `repeat(${grid[0].length}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${grid.length}, minmax(0, 1fr))`,
        }}
      >
        {frameCells.map((cell, index) => {
          if ((cell === "hero" || cell === "wide") && seen.has(cell)) {
            return null;
          }
          seen.add(cell);
          const panel = resolvePanel(cell, index);
          const img = panel ? `/api/projects/${encodeURIComponent(project)}/files/${panel.image_path}` : null;
          const rowIndex = Math.floor(index / grid[0].length);
          const colIndex = index % grid[0].length;
          const colSpan =
            cell === "hero" || cell === "wide"
              ? grid[0].length
              : 1;
          return (
            <div
              key={`${cell}-${index}`}
              className={cn(
                "relative overflow-hidden border border-ink-black/55 bg-white",
                !img && "bg-[#f5f0e2]",
              )}
              style={{
                gridColumn: `${colIndex + 1} / span ${colSpan}`,
                gridRow: `${rowIndex + 1} / span 1`,
              }}
            >
              {img && (
                <img
                  src={img}
                  alt=""
                  className="h-full w-full object-cover grayscale-[0.1]"
                />
              )}
              <div className="absolute left-0 top-0 h-6 w-6 bg-[#f8f4e7]" />
            </div>
          );
        })}
      </div>
    </div>
  );
}
