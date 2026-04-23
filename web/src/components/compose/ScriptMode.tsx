import { useState } from "react";
import { cn } from "../../lib/cn";
import { useTranslateSinglePageBubbles, useCharacterVoices, usePutCharacterVoice } from "../../api/queries";
import type { ComicPage, Bubble, PagePanel, CharacterVoice } from "../../types/api";

type FilterType = "all" | "speech" | "thought" | "narration";

interface ScriptModeProps {
  project: string | undefined;
  pages: (ComicPage | undefined)[];
  isLoading: boolean;
  pageIdx: number;
  outputLanguage: "en" | "es" | "fr";
  onPageSelect: (idx: number) => void;
  onUpdateBubble: (
    pageNum: number,
    panelId: string,
    bubbleId: string,
    patch: Partial<Bubble>,
  ) => void;
  onSwitchToLayout: (pageNum: number, panelId: string, bubbleId: string) => void;
}

export function ScriptMode({
  project,
  pages,
  isLoading,
  pageIdx,
  outputLanguage,
  onPageSelect,
  onUpdateBubble,
  onSwitchToLayout,
}: ScriptModeProps) {
  const [filter, setFilter] = useState<FilterType>("all");
  const [findReplaceOpen, setFindReplaceOpen] = useState(false);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const translateSinglePageMut = useTranslateSinglePageBubbles();

  const allBubbles = pages.flatMap((p) => p?.panels.flatMap((panel) => panel.bubbles) ?? []);
  const counts = {
    all: allBubbles.length,
    speech: allBubbles.filter((b) => b.type === "speech").length,
    thought: allBubbles.filter((b) => b.type === "thought").length,
    narration: allBubbles.filter((b) => b.type === "narration").length,
  };

  const FILTERS: { id: FilterType; label: string }[] = [
    { id: "all", label: "All" },
    { id: "speech", label: "Speech" },
    { id: "thought", label: "Thought" },
    { id: "narration", label: "Narration" },
  ];

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {/* Left rail — page list */}
      <aside className="w-[220px] shrink-0 space-y-2 overflow-y-auto border-r-[2px] border-ink-black bg-ink-black/5 p-3">
        {pages.map((page, idx) => {
          const bubbleCount = page?.panels.flatMap((p) => p.bubbles).length ?? 0;
          const panelCount = page?.panels.length ?? 0;
          return (
            <button
              key={idx}
              onClick={() => onPageSelect(idx)}
              className={cn(
                "w-full border-[2px] border-ink-black p-2.5 text-left transition-colors",
                idx === pageIdx ? "bg-hero-red text-bristol" : "bg-pulp-paper hover:bg-bristol",
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
      </aside>

      {/* Center — screenplay */}
      <div className="min-w-0 flex-1 overflow-y-auto">
        {/* Filter pills */}
        <div className="sticky top-0 z-10 flex items-center gap-1.5 border-b-[2px] border-ink-black bg-pulp-paper/95 px-4 py-2.5 backdrop-blur-sm">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={cn(
                "flex items-center gap-1.5 border-[2px] border-ink-black px-3 py-1 font-meta text-[0.6rem] tracking-[0.12em] transition-colors",
                filter === f.id
                  ? "bg-ink-black text-pulp-paper"
                  : "bg-pulp-paper text-ink-black hover:bg-surface-container",
              )}
            >
              {f.label}
              <span className="opacity-50">{counts[f.id]}</span>
            </button>
          ))}
        </div>

        <div className="space-y-6 p-4">
          {isLoading ? (
            <div className="flex h-40 items-center justify-center">
              <p className="font-meta text-[0.6rem] tracking-[0.2em] text-ink-black/40">
                LOADING SCRIPT...
              </p>
            </div>
          ) : (
            pages.map(
              (page, pidx) =>
                page && (
                  <ScriptPageSection
                    key={pidx}
                    page={page}
                    filter={filter}
                    onUpdateBubble={(panelId, bubbleId, patch) =>
                      onUpdateBubble(page.page_number, panelId, bubbleId, patch)
                    }
                    onRevealInLayout={(panelId, bubbleId) =>
                      onSwitchToLayout(page.page_number, panelId, bubbleId)
                    }
                  />
                ),
            )
          )}
        </div>
      </div>

      {/* Right rail — bulk ops + explainer */}
      <aside className="w-[260px] shrink-0 space-y-3 overflow-y-auto border-l-[2px] border-ink-black p-3">
        {/* Character Voices */}
        <CharacterVoicesCard project={project} pages={pages} />

        {/* Bulk Ops */}
        <div className="border-[2px] border-ink-black bg-pulp-paper shadow-ink-sm">
          <div className="border-b-[2px] border-ink-black px-3 py-2">
            <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
              ACTIONS
            </div>
            <div className="font-display text-[0.88rem] font-bold tracking-[-0.02em]">
              BULK OPS
            </div>
          </div>
          <div className="space-y-1.5 p-3">
            <button
              onClick={() => setFilter("narration")}
              className="flex w-full items-center justify-between border-[2px] border-ink-black bg-surface-container px-2.5 py-1.5 text-left transition-colors hover:bg-pulp-paper"
            >
              <span className="font-meta text-[0.6rem] tracking-[0.1em]">Select all narration</span>
              <kbd className="font-meta text-[0.5rem] text-ink-black/50">⇧N</kbd>
            </button>
            <button
              onClick={() => setFindReplaceOpen((o) => !o)}
              className="flex w-full items-center justify-between border-[2px] border-ink-black bg-surface-container px-2.5 py-1.5 text-left transition-colors hover:bg-pulp-paper"
            >
              <span className="font-meta text-[0.6rem] tracking-[0.1em]">Find & replace</span>
              <kbd className="font-meta text-[0.5rem] text-ink-black/50">⌘F</kbd>
            </button>
            <button
              disabled
              className="flex w-full cursor-not-allowed items-center justify-between border-[2px] border-ink-black/20 bg-surface-container px-2.5 py-1.5 text-left opacity-40"
            >
              <span className="font-meta text-[0.6rem] tracking-[0.1em]">Re-attribute speaker</span>
              <kbd className="font-meta text-[0.5rem] text-ink-black/50">⇧A</kbd>
            </button>
            <button
              onClick={() => {
                const page = pages[pageIdx];
                if (project && page) {
                  translateSinglePageMut.mutate({
                    project,
                    pageNum: page.page_number,
                    targetLanguage: outputLanguage,
                  });
                }
              }}
              disabled={!project || translateSinglePageMut.isPending}
              className="flex w-full items-center justify-between border-[2px] border-ink-black bg-surface-container px-2.5 py-1.5 text-left transition-colors hover:bg-pulp-paper disabled:opacity-40"
            >
              <span className="font-meta text-[0.6rem] tracking-[0.1em]">
                {translateSinglePageMut.isPending ? "Translating..." : "Translate page"}
              </span>
              <kbd className="font-meta text-[0.5rem] text-ink-black/50">⌘T</kbd>
            </button>
          </div>

          {/* Find & replace inline UI */}
          {findReplaceOpen && (
            <div className="border-t-[2px] border-ink-black p-3 space-y-2">
              <input
                value={findText}
                onChange={(e) => setFindText(e.target.value)}
                placeholder="Find..."
                className="ui-field w-full border-[2px] border-ink-black px-2 py-1 font-mono text-[0.75rem]"
              />
              <input
                value={replaceText}
                onChange={(e) => setReplaceText(e.target.value)}
                placeholder="Replace with..."
                className="ui-field w-full border-[2px] border-ink-black px-2 py-1 font-mono text-[0.75rem]"
              />
              <button
                onClick={() => {
                  if (!findText) return;
                  for (const page of pages) {
                    if (!page) continue;
                    for (const panel of page.panels) {
                      for (const bubble of panel.bubbles) {
                        if (bubble.text.includes(findText)) {
                          onUpdateBubble(
                            page.page_number,
                            panel.id,
                            bubble.id,
                            { text: bubble.text.replaceAll(findText, replaceText) },
                          );
                        }
                      }
                    }
                  }
                }}
                disabled={!findText}
                className="w-full border-[2px] border-ink-black bg-hero-red px-2 py-1 font-meta text-[0.55rem] tracking-[0.1em] text-bristol disabled:opacity-40"
              >
                REPLACE ALL
              </button>
            </div>
          )}
        </div>

        {/* Explainer */}
        <div className="border-[2px] border-ink-black bg-surface-container p-3">
          <div className="mb-1 font-meta text-[0.52rem] tracking-[0.14em] text-ink-black/50">
            WHY SCRIPT MODE?
          </div>
          <p className="text-[0.78rem] leading-relaxed text-ink-black/60">
            Edit every bubble as inline text, grouped by page and panel. No canvas, no
            drag — just the words. 80% of users live here.
          </p>
        </div>
      </aside>
    </div>
  );
}

function ScriptPageSection({
  page,
  filter,
  onUpdateBubble,
  onRevealInLayout,
}: {
  page: ComicPage;
  filter: FilterType;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onRevealInLayout: (panelId: string, bubbleId: string) => void;
}) {
  return (
    <div>
      <div className="section-rule mb-3">
        PAGE {String(page.page_number).padStart(2, "0")}
      </div>
      <div className="space-y-3">
        {page.panels.map((panel, pidx) => {
          const bubbles =
            filter === "all" ? panel.bubbles : panel.bubbles.filter((b) => b.type === filter);
          if (bubbles.length === 0) return null;
          return (
            <ScriptPanelSection
              key={panel.id}
              panel={panel}
              panelIndex={pidx}
              bubbles={bubbles}
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
  onUpdateBubble,
  onRevealInLayout,
}: {
  panel: PagePanel;
  panelIndex: number;
  bubbles: Bubble[];
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onRevealInLayout: (panelId: string, bubbleId: string) => void;
}) {
  const primaryBubble = bubbles[0];

  return (
    <div className="border-[2px] border-ink-black bg-pulp-paper">
      <div className="flex items-center justify-between border-b-[2px] border-ink-black bg-surface-container px-3 py-2">
        <div className="flex items-center gap-3">
          <span className="font-meta text-[0.58rem] tracking-[0.18em]">
            PANEL {panelIndex + 1}
          </span>
          <span className="font-meta text-[0.52rem] tracking-[0.1em] text-ink-black/50">
            {panel.scene_id}
          </span>
        </div>
        <button
          onClick={() => primaryBubble && onRevealInLayout(panel.id, primaryBubble.id)}
          className="font-meta text-[0.52rem] tracking-[0.1em] text-hero-red hover:underline"
        >
          Reveal in Layout →
        </button>
      </div>
      <div className="divide-y-[1px] divide-ink-black/10">
        {bubbles.map((bubble) => (
          <ScriptBubbleRow
            key={bubble.id}
            bubble={bubble}
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
  onUpdate,
  onFixInLayout,
}: {
  bubble: Bubble;
  onUpdate: (patch: Partial<Bubble>) => void;
  onFixInLayout: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState(bubble.text);

  const speakerLabel = bubble.speaker_name
    ? `${bubble.speaker_name.toUpperCase()} (${bubble.type} · ${bubble.side})`
    : `UNKNOWN (${bubble.type} · ${bubble.side})`;

  function handleBlur() {
    setEditing(false);
    if (draftText !== bubble.text) {
      onUpdate({ text: draftText });
    }
  }

  const TYPE_STYLES: Record<string, string> = {
    speech: "bg-chip-gold text-ink-black",
    thought: "bg-secondary-container text-on-secondary-container",
    narration: "bg-surface-variant text-ink-black/70",
  };

  return (
    <div
      className={cn(
        "grid grid-cols-[180px_1fr]",
        bubble.type === "narration" && "bg-surface-container/40",
      )}
    >
      <div className="border-r-[1px] border-ink-black/10 px-3 py-2.5">
        <div className="font-meta text-[0.56rem] leading-snug tracking-[0.08em] text-ink-black/70">
          {speakerLabel}
        </div>
        <span
          className={cn(
            "mt-1.5 inline-block px-1.5 py-0.5 font-meta text-[0.46rem] tracking-[0.1em] uppercase",
            TYPE_STYLES[bubble.type] ?? "bg-surface-variant",
          )}
        >
          {bubble.type}
        </span>
      </div>
      <div className="px-3 py-2.5">
        <div className="mb-1 flex items-center justify-end">
          <button
            onClick={onFixInLayout}
            className="font-meta text-[0.48rem] tracking-[0.1em] text-hero-red hover:underline"
          >
            fix in Layout
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
            onClick={() => {
              setEditing(true);
              setDraftText(bubble.text);
            }}
          >
            {bubble.text || <span className="opacity-30">Click to edit...</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function CharacterVoicesCard({
  project,
  pages,
}: {
  project: string | undefined;
  pages: (ComicPage | undefined)[];
}) {
  const { data: voices } = useCharacterVoices(project);
  const putVoiceMut = usePutCharacterVoice();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<CharacterVoice>>({});

  // Extract unique speakers from loaded pages
  const speakers = new Map<string, string>();
  for (const page of pages) {
    if (!page) continue;
    for (const panel of page.panels) {
      for (const bubble of panel.bubbles) {
        if (bubble.speaker_id) {
          speakers.set(bubble.speaker_id, bubble.speaker_name ?? bubble.speaker_id);
        }
      }
    }
  }

  function startEdit(id: string, name: string) {
    const existing = voices?.[id];
    setDraft({
      character_id: id,
      character_name: name,
      font_family: existing?.font_family ?? null,
      font_size: existing?.font_size ?? null,
      font_color: existing?.font_color ?? null,
      fill_color: existing?.fill_color ?? null,
      border_color: existing?.border_color ?? null,
      border_width: existing?.border_width ?? null,
      border_radius: existing?.border_radius ?? null,
    });
    setEditingId(id);
  }

  function handleSave() {
    if (!project || !editingId) return;
    putVoiceMut.mutate(
      { project, voice: draft as CharacterVoice },
      { onSuccess: () => setEditingId(null) },
    );
  }

  return (
    <div className="border-[2px] border-ink-black bg-pulp-paper shadow-ink-sm">
      <div className="border-b-[2px] border-ink-black px-3 py-2">
        <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
          INSPECTOR
        </div>
        <div className="font-display text-[0.88rem] font-bold tracking-[-0.02em]">
          CHARACTER VOICES
        </div>
      </div>
      <div className="p-3 space-y-1.5">
        {speakers.size === 0 ? (
          <p className="font-meta text-[0.55rem] tracking-[0.08em] text-ink-black/40">
            No speakers found in loaded pages.
          </p>
        ) : (
          Array.from(speakers.entries()).map(([id, name]) => {
            const hasVoice = !!voices?.[id];
            const isEditing = editingId === id;
            return (
              <div key={id} className="border-[2px] border-ink-black/20 p-2">
                <div className="flex items-center justify-between">
                  <span className="font-meta text-[0.58rem] tracking-[0.08em] font-bold">
                    {name.toUpperCase()}
                  </span>
                  {hasVoice ? (
                    <span className="font-meta text-[0.46rem] tracking-[0.1em] text-hero-red">VOICE SET</span>
                  ) : (
                    <span className="font-meta text-[0.46rem] tracking-[0.1em] text-ink-black/35">DEFAULT</span>
                  )}
                </div>
                {isEditing ? (
                  <div className="mt-2 space-y-1.5">
                    <div className="grid grid-cols-2 gap-1.5">
                      <input
                        value={draft.font_family ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, font_family: e.target.value || null }))}
                        placeholder="Font family"
                        className="ui-field border border-ink-black/20 px-1.5 py-0.5 font-mono text-[0.6rem]"
                      />
                      <input
                        type="number"
                        value={draft.font_size ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, font_size: e.target.value ? Number(e.target.value) : null }))}
                        placeholder="Font size"
                        className="ui-field border border-ink-black/20 px-1.5 py-0.5 font-mono text-[0.6rem]"
                      />
                      <input
                        value={draft.font_color ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, font_color: e.target.value || null }))}
                        placeholder="Text color"
                        className="ui-field border border-ink-black/20 px-1.5 py-0.5 font-mono text-[0.6rem]"
                      />
                      <input
                        value={draft.fill_color ?? ""}
                        onChange={(e) => setDraft((d) => ({ ...d, fill_color: e.target.value || null }))}
                        placeholder="Fill color"
                        className="ui-field border border-ink-black/20 px-1.5 py-0.5 font-mono text-[0.6rem]"
                      />
                    </div>
                    <div className="flex gap-1.5">
                      <button
                        onClick={handleSave}
                        disabled={putVoiceMut.isPending}
                        className="flex-1 border-[2px] border-ink-black bg-hero-red px-2 py-1 font-meta text-[0.5rem] tracking-[0.08em] text-bristol disabled:opacity-40"
                      >
                        {putVoiceMut.isPending ? "Saving..." : "Save"}
                      </button>
                      <button
                        onClick={() => setEditingId(null)}
                        className="border-[2px] border-ink-black/20 px-2 py-1 font-meta text-[0.5rem] tracking-[0.08em]"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => startEdit(id, name)}
                    className="mt-1 font-meta text-[0.5rem] tracking-[0.08em] text-hero-red hover:underline"
                  >
                    {hasVoice ? "Edit voice" : "Set voice"}
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
