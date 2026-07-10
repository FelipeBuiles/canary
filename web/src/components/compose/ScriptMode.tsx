import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import { ShortcutHint } from "../ui/ShortcutHint";
import { useStoryBible } from "../../api/queries";
import type { ComicPage, Bubble, PagePanel } from "../../types/api";

type FilterType = "all" | "speech" | "thought" | "narration";

interface ScriptModeProps {
  project: string | undefined;
  pages: (ComicPage | undefined)[];
  isLoading: boolean;
  pageIdx: number;
  onPageSelect: (idx: number) => void;
  onUpdateBubble: (
    pageNum: number,
    panelId: string,
    bubbleId: string,
    patch: Partial<Bubble>,
  ) => void;
  onBulkUpdateBubbles: (
    pageNum: number,
    panelPatches: { id: string; bubbles: (Partial<Bubble> & { id: string })[] }[],
  ) => void;
  onSwitchToLayout: (pageNum: number, panelId: string, bubbleId: string) => void;
}

export function ScriptMode({
  project,
  pages,
  isLoading,
  pageIdx,
  onPageSelect,
  onUpdateBubble,
  onBulkUpdateBubbles,
  onSwitchToLayout,
}: ScriptModeProps) {
  const { data: storyBible } = useStoryBible(project);
  const characterNames = Object.fromEntries(
    (storyBible?.characters ?? []).map((c) => [c.id, c.name])
  );

  const [filter, setFilter] = useState<FilterType>("all");
  const [pageFilter, setPageFilter] = useState<"all" | number>("all");
  const [findReplaceOpen, setFindReplaceOpen] = useState(false);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageSectionRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (pageFilter !== "all") return;
    const target = pageSectionRefs.current[pageIdx];
    const container = scrollRef.current;
    if (!target || !container) return;
    const offset = target.offsetTop - container.offsetTop - 16;
    container.scrollTo({ top: offset, behavior: "smooth" });
  }, [pageIdx, pageFilter]);

  // ⌘F opens find & replace (matches the hint shown on the button).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setFindReplaceOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleReplaceAll() {
    if (!findText) return;
    for (const page of pages) {
      if (!page) continue;
      // Batch all edits on a page into one PATCH — per-bubble requests race
      // each other on the server's read-modify-write of the page file.
      const panelPatches: { id: string; bubbles: (Partial<Bubble> & { id: string })[] }[] = [];
      for (const panel of page.panels) {
        const bubblePatches = panel.bubbles
          .filter((b) => b.text.includes(findText))
          .map((b) => ({ id: b.id, text: b.text.replaceAll(findText, replaceText) }));
        if (bubblePatches.length > 0) {
          panelPatches.push({ id: panel.id, bubbles: bubblePatches });
        }
      }
      if (panelPatches.length > 0) {
        onBulkUpdateBubbles(page.page_number, panelPatches);
      }
    }
  }

  const visiblePages = pageFilter === "all" ? pages : [pages[pageFilter]];
  const allBubbles = visiblePages.flatMap((p) => p?.panels.flatMap((panel) => panel.bubbles) ?? []);
  const counts = {
    all: allBubbles.length,
    speech: allBubbles.filter((b) => b.type === "speech").length,
    thought: allBubbles.filter((b) => b.type === "thought").length,
    narration: allBubbles.filter((b) => b.type === "narration").length,
  };

  const activeFilter = filter !== "all" && counts[filter] === 0 ? "all" : filter;

  const FILTERS: { id: FilterType; label: string }[] = [
    { id: "all", label: "All" },
    { id: "speech", label: "Speech" },
    { id: "thought", label: "Thought" },
    { id: "narration", label: "Narration" },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden bg-pulp-paper px-2 py-3 md:grid md:grid-cols-[166px_minmax(0,1fr)]">
      {/* Left rail — page list (a horizontal strip on mobile, vertical on desktop) */}
      <aside className="shrink-0 border-[2px] border-ink-black bg-pulp-paper p-2 shadow-[3px_3px_0_0_var(--color-ink-black)] md:min-h-0 md:overflow-y-auto">
        <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">PAGES</div>
        <div className="flex gap-2 overflow-x-auto md:flex-col md:overflow-x-visible">
          <button
            onClick={() => setPageFilter("all")}
            className={cn(
              "w-32 shrink-0 border p-2 text-left transition-colors md:w-full",
              pageFilter === "all"
                ? "border-hero-red bg-bristol text-ink-black"
                : "border-ink-black/24 bg-pulp-paper hover:bg-bristol",
            )}
          >
            <div className="font-meta text-[0.52rem] tracking-[0.18em] opacity-70">ALL PAGES</div>
            <div className="mt-0.5 font-display text-[0.88rem] font-bold leading-tight tracking-[-0.02em]">
              {pages.length} page{pages.length !== 1 ? "s" : ""}
            </div>
          </button>
          {pages.map((page, idx) => {
            const bubbleCount = page?.panels.flatMap((p) => p.bubbles).length ?? 0;
            const panelCount = page?.panels.length ?? 0;
            return (
              <button
                key={idx}
                onClick={() => { setPageFilter(idx); onPageSelect(idx); }}
                className={cn(
                  "w-32 shrink-0 border p-2 text-left transition-colors md:w-full",
                  pageFilter === idx
                    ? "border-hero-red bg-bristol text-ink-black"
                    : "border-ink-black/24 bg-pulp-paper hover:bg-bristol",
                )}
              >
                <div className="font-meta text-[0.52rem] tracking-[0.18em] opacity-70">
                  PAGE {String(idx + 1).padStart(2, "0")}
                </div>
                <div className="mt-0.5 font-display text-[0.88rem] font-bold leading-tight tracking-[-0.02em]">
                  {panelCount} panel{panelCount !== 1 ? "s" : ""}
                </div>
                <div className="mt-0.5 font-meta text-[0.5rem] tracking-[0.12em] opacity-60">
                  {bubbleCount} bubble{bubbleCount !== 1 ? "s" : ""}
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      {/* Center — bubble list */}
      <div className="flex min-w-0 flex-col overflow-hidden border-[2px] border-ink-black bg-bristol shadow-[3px_3px_0_0_var(--color-ink-black)]">
        {(() => {
          const activeTypeFilters = FILTERS.filter((f) => f.id !== "all" && counts[f.id] > 0);
          const showFilters = activeTypeFilters.length > 1;
          return (
            <div className="sticky top-0 z-10 border-b-[2px] border-ink-black bg-pulp-paper">
              <div className="flex flex-wrap items-center justify-between gap-1.5 px-4 py-2">
                <button
                  onClick={() => setFindReplaceOpen((o) => !o)}
                  className="flex shrink-0 items-center gap-2 border border-ink-black/30 bg-bristol px-2.5 py-1 font-meta text-[0.52rem] tracking-[0.1em] whitespace-nowrap transition-colors hover:bg-surface-container"
                >
                  Find &amp; replace
                  <ShortcutHint>⌘F</ShortcutHint>
                </button>
                <div className="flex flex-wrap items-center gap-1.5">
                  {showFilters && [{ id: "all" as FilterType, label: "All" }, ...activeTypeFilters].map((f) => (
                    <button
                      key={f.id}
                      onClick={() => setFilter(f.id)}
                      className={cn(
                        "flex items-center gap-1.5 border px-2.5 py-1 font-meta text-[0.52rem] tracking-[0.12em] transition-colors",
                        activeFilter === f.id
                          ? "bg-ink-black text-pulp-paper"
                          : "border-ink-black/22 bg-pulp-paper text-ink-black hover:bg-bristol",
                      )}
                    >
                      {f.label}
                      <span className="opacity-50">{counts[f.id]}</span>
                    </button>
                  ))}
                </div>
              </div>
              {findReplaceOpen && (
                <div className="flex items-center gap-2 border-t border-ink-black/15 px-4 py-2">
                  <input
                    value={findText}
                    onChange={(e) => setFindText(e.target.value)}
                    placeholder="Find..."
                    className="ui-field flex-1 border-[2px] border-ink-black px-2 py-1 font-mono text-[0.75rem]"
                  />
                  <input
                    value={replaceText}
                    onChange={(e) => setReplaceText(e.target.value)}
                    placeholder="Replace with..."
                    className="ui-field flex-1 border-[2px] border-ink-black px-2 py-1 font-mono text-[0.75rem]"
                  />
                  <button
                    onClick={handleReplaceAll}
                    disabled={!findText}
                    className="border-[2px] border-ink-black bg-hero-red px-3 py-1 font-meta text-[0.55rem] tracking-[0.1em] text-bristol disabled:opacity-40"
                  >
                    REPLACE ALL
                  </button>
                </div>
              )}
            </div>
          );
        })()}

        <div ref={scrollRef} className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          {isLoading ? (
            <div className="flex h-40 items-center justify-center">
              <p className="font-meta text-[0.6rem] tracking-[0.2em] text-ink-black/40">LOADING SCRIPT...</p>
            </div>
          ) : (
            visiblePages.map(
              (page, pidx) =>
                page && (
                  <div key={page.page_number} ref={(el) => { pageSectionRefs.current[pidx] = el; }}>
                    <ScriptPageSection
                      page={page}
                      filter={activeFilter}
                      characterNames={characterNames}
                      onUpdateBubble={(panelId, bubbleId, patch) =>
                        onUpdateBubble(page.page_number, panelId, bubbleId, patch)
                      }
                      onRevealInLayout={(panelId, bubbleId) =>
                        onSwitchToLayout(page.page_number, panelId, bubbleId)
                      }
                    />
                  </div>
                ),
            )
          )}
        </div>
      </div>

    </div>
  );
}

function ScriptPageSection({
  page,
  filter,
  characterNames,
  onUpdateBubble,
  onRevealInLayout,
}: {
  page: ComicPage;
  filter: FilterType;
  characterNames: Record<string, string>;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onRevealInLayout: (panelId: string, bubbleId: string) => void;
}) {
  return (
    <div>
      <div className="section-rule mb-3">PAGE {String(page.page_number).padStart(2, "0")}</div>
      <div>
        {page.panels.map((panel, pidx) => {
          const bubbles = filter === "all" ? panel.bubbles : panel.bubbles.filter((b) => b.type === filter);
          if (bubbles.length === 0) return null;
          return (
            <ScriptPanelSection
              key={panel.id}
              panel={panel}
              panelIndex={pidx}
              bubbles={bubbles}
              characterNames={characterNames}
              onUpdateBubble={onUpdateBubble}
              onRevealInLayout={onRevealInLayout}
            />
          );
        })}
      </div>
    </div>
  );
}

function ScriptPanelSection({
  panel,
  panelIndex,
  bubbles,
  characterNames,
  onUpdateBubble,
  onRevealInLayout,
}: {
  panel: PagePanel;
  panelIndex: number;
  bubbles: Bubble[];
  characterNames: Record<string, string>;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onRevealInLayout: (panelId: string, bubbleId: string) => void;
}) {
  const primaryBubble = bubbles[0];
  return (
    <div className="border-t border-ink-black bg-bristol first:border-t-0">
      <div className="flex items-center justify-between border-b border-ink-black/70 bg-bristol px-3 py-2">
        <div className="flex items-center gap-3">
          <span className="font-meta text-[0.58rem] tracking-[0.18em]">PANEL {panelIndex + 1}</span>
          <span className="font-meta text-[0.52rem] tracking-[0.1em] text-ink-black/50">{panel.scene_id}</span>
        </div>
        <button
          onClick={() => primaryBubble && onRevealInLayout(panel.id, primaryBubble.id)}
          className="border border-ink-black/20 bg-pulp-paper px-2 py-1 font-meta text-[0.48rem] tracking-[0.12em] text-ink-black/70 transition-colors hover:bg-bristol"
        >
          Reveal in Canvas →
        </button>
      </div>
      <div className="divide-y-[1px] divide-ink-black/10">
        {bubbles.map((bubble) => (
          <ScriptBubbleRow
            key={bubble.id}
            bubble={bubble}
            characterNames={characterNames}
            onUpdate={(patch) => onUpdateBubble(panel.id, bubble.id, patch)}
            onFixInLayout={() => onRevealInLayout(panel.id, bubble.id)}
          />
        ))}
      </div>
    </div>
  );
}

function ScriptBubbleRow({
  bubble,
  characterNames,
  onUpdate,
  onFixInLayout,
}: {
  bubble: Bubble;
  characterNames: Record<string, string>;
  onUpdate: (patch: Partial<Bubble>) => void;
  onFixInLayout: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(bubble.text);

  // Plain words, never debug output: a narration bubble with no speaker is a
  // CAPTION, anything else without a speaker reads as the narrator.
  const resolvedName =
    bubble.speaker_name ??
    (bubble.speaker_id ? characterNames[bubble.speaker_id] : null) ??
    (bubble.type === "narration" ? "CAPTION" : "NARRATOR");
  const kindLabel = bubble.type === "narration" ? "CAPTION" : bubble.type.toUpperCase();
  const speakerLabel = resolvedName.toUpperCase() === kindLabel
    ? `${kindLabel} · ${bubble.side.toUpperCase()}`
    : `${resolvedName.toUpperCase()} · ${kindLabel} · ${bubble.side.toUpperCase()}`;

  function handleBlur() {
    setEditing(false);
    if (draftText !== bubble.text) onUpdate({ text: draftText });
  }

  const TYPE_STYLES: Record<string, string> = {
    speech: "bg-chip-gold text-ink-black",
    thought: "bg-secondary-container text-on-secondary-container",
    narration: "bg-surface-variant text-ink-black/70",
  };

  return (
    <div className={cn("grid grid-cols-[180px_1fr]", bubble.type === "narration" && "bg-surface-container/35")}>
      <div className="border-r-[1px] border-ink-black/10 px-3 py-2.5">
        <div className="font-meta text-[0.56rem] leading-snug tracking-[0.08em] text-ink-black/70">{speakerLabel}</div>
        <span className={cn("mt-1.5 inline-block px-1.5 py-0.5 font-meta text-[0.46rem] tracking-[0.1em] uppercase", TYPE_STYLES[bubble.type] ?? "bg-surface-variant")}>
          {bubble.type}
        </span>
      </div>
      <div className="px-3 py-2.5">
        <div className="mb-1 flex items-center justify-end">
          <button
            onClick={onFixInLayout}
            className="border border-ink-black/15 bg-pulp-paper px-2 py-0.5 font-meta text-[0.46rem] tracking-[0.1em] text-ink-black/55 transition-colors hover:bg-bristol"
          >
            fix in Canvas
          </button>
        </div>
        {editing ? (
          <textarea
            autoFocus
            value={draftText}
            onChange={(e) => setDraftText(e.target.value)}
            onBlur={handleBlur}
            className="ui-field w-full resize-none font-mono text-[0.82rem] leading-relaxed"
            rows={Math.max(2, draftText.split("\n").length)}
          />
        ) : (
          <div
            className="-mx-1 cursor-text rounded-sm px-1 font-mono text-[0.82rem] leading-relaxed text-ink-black hover:bg-surface-container/60"
            onClick={() => { setEditing(true); setDraftText(bubble.text); }}
          >
            {bubble.text || <span className="opacity-30">Click to edit...</span>}
          </div>
        )}
      </div>
    </div>
  );
}
