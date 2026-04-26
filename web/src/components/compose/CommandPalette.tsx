import { useState, useEffect, useRef } from "react";
import { cn } from "../../lib/cn";
interface Command {
  id: string;
  group: string;
  label: string;
  shortcut?: string;
  accent?: boolean;
  action: () => void;
}

interface CommandPaletteProps {
  onClose: () => void;
  onSwitchMode: (mode: "script" | "layout" | "style" | "preview") => void;
  onExport: (format: "pdf" | "cbz") => void;
  onMatchStyle: () => void;
  onTranslate: () => void;
  onAddBubble: (type: "speech" | "thought" | "narration") => void;
  onAddSfx: () => void;
}

export function CommandPalette({
  onClose,
  onSwitchMode,
  onExport,
  onMatchStyle,
  onTranslate,
  onAddBubble,
  onAddSfx,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const allCommands: Command[] = [
    // Go to mode
    { id: "mode-script", group: "GO TO MODE", label: "Script mode", shortcut: "1", action: () => { onSwitchMode("script"); onClose(); } },
    { id: "mode-layout", group: "GO TO MODE", label: "Layout mode", shortcut: "2", action: () => { onSwitchMode("layout"); onClose(); } },
    { id: "mode-style", group: "GO TO MODE", label: "Style mode", shortcut: "3", action: () => { onSwitchMode("style"); onClose(); } },
    { id: "mode-preview", group: "GO TO MODE", label: "Preview mode", shortcut: "4", action: () => { onSwitchMode("preview"); onClose(); } },
    // Add
    { id: "add-speech", group: "ADD", label: "Add speech bubble", shortcut: "B", action: () => { onAddBubble("speech"); onClose(); } },
    { id: "add-thought", group: "ADD", label: "Add thought bubble", shortcut: "T", action: () => { onAddBubble("thought"); onClose(); } },
    { id: "add-narration", group: "ADD", label: "Add narration box", shortcut: "N", action: () => { onAddBubble("narration"); onClose(); } },
    { id: "add-sfx", group: "ADD", label: "Add SFX", shortcut: "X", action: () => { onAddSfx(); onClose(); } },
    // Magic
    { id: "match-style", group: "MAGIC", label: "Match lettering to art", shortcut: "⌘M", accent: true, action: () => { onMatchStyle(); onClose(); } },
    { id: "translate", group: "MAGIC", label: "Translate project", action: () => { onTranslate(); onClose(); } },
    // Export
    { id: "export-pdf", group: "EXPORT", label: "Export PDF", shortcut: "⌘E", accent: true, action: () => { onExport("pdf"); onClose(); } },
    { id: "export-cbz", group: "EXPORT", label: "Export CBZ", action: () => { onExport("cbz"); onClose(); } },
  ];

  const filtered = query.trim()
    ? allCommands.filter((c) => c.label.toLowerCase().includes(query.toLowerCase()))
    : allCommands;

  useEffect(() => { setSelectedIdx(0); }, [query]);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const paletteRef = useRef<HTMLDivElement>(null);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSelectedIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); filtered[selectedIdx]?.action(); }
    else if (e.key === "Escape") { onClose(); }
    else if (e.key === "Tab") {
      e.preventDefault();
      const palette = paletteRef.current;
      if (!palette) return;
      const focusable = palette.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const activeIdx = Array.from(focusable).indexOf(document.activeElement as HTMLElement);
      const next = e.shiftKey
        ? (activeIdx - 1 + focusable.length) % focusable.length
        : (activeIdx + 1) % focusable.length;
      focusable[next].focus();
    }
  }

  // Group commands while tracking a flat index for keyboard selection
  const grouped: { group: string; commands: (Command & { flatIdx: number })[] }[] = [];
  let flatIdx = 0;
  for (const cmd of filtered) {
    let grp = grouped.find((g) => g.group === cmd.group);
    if (!grp) { grp = { group: cmd.group, commands: [] }; grouped.push(grp); }
    grp.commands.push({ ...cmd, flatIdx: flatIdx++ });
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center bg-ink-black/40 pt-[15vh] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        ref={paletteRef}
        className="w-full max-w-[640px] border-[2px] border-ink-black bg-pulp-paper shadow-ink-lg"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Search */}
        <div className="flex items-center border-b-[2px] border-ink-black px-4">
          <span className="mr-3 font-meta text-[0.58rem] tracking-[0.1em] text-ink-black/40">
            ⌘K
          </span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command..."
            className="flex-1 bg-transparent py-4 font-body text-[0.9rem] text-ink-black placeholder:text-ink-black/30 focus:outline-none"
          />
          <button
            onClick={onClose}
            className="font-meta text-[0.6rem] tracking-[0.1em] text-ink-black/40 hover:text-ink-black/70"
          >
            ESC
          </button>
        </div>

        {/* Commands */}
        <div className="max-h-[400px] overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/40">
              NO COMMANDS FOUND
            </div>
          ) : (
            grouped.map(({ group, commands }) => (
              <div key={group}>
                <div className="border-t-[1px] border-ink-black/10 px-4 pb-1 pt-3">
                  <span className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">
                    {group}
                  </span>
                </div>
                {commands.map((cmd) => (
                  <button
                    key={cmd.id}
                    onClick={cmd.action}
                    className={cn(
                      "flex w-full items-center justify-between px-4 py-2.5 text-left transition-colors",
                      cmd.flatIdx === selectedIdx
                        ? "bg-ink-black text-pulp-paper"
                        : "hover:bg-surface-container",
                    )}
                  >
                    <div className="flex items-center gap-2.5">
                      {cmd.accent ? (
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-hero-red" />
                      ) : (
                        <span className="h-1.5 w-1.5 shrink-0" />
                      )}
                      <span className="font-body text-[0.85rem]">{cmd.label}</span>
                    </div>
                    {cmd.shortcut && (
                      <kbd
                        className={cn(
                          "rounded border px-2 py-0.5 font-meta text-[0.58rem] tracking-[0.08em]",
                          cmd.flatIdx === selectedIdx
                            ? "border-pulp-paper/30 text-pulp-paper/60"
                            : "border-ink-black/20 text-ink-black/40",
                        )}
                      >
                        {cmd.shortcut}
                      </kbd>
                    )}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 border-t-[2px] border-ink-black px-4 py-2">
          {["↑↓ NAVIGATE", "↵ RUN", "ESC CLOSE"].map((hint) => (
            <span key={hint} className="font-meta text-[0.52rem] tracking-[0.1em] text-ink-black/40">
              {hint}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
