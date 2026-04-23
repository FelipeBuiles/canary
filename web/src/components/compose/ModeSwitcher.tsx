import { cn } from "../../lib/cn";
import type { ComposeMode } from "./compose-types";

const MODES: { id: ComposeMode; label: string; key: string }[] = [
  { id: "script", label: "SCRIPT", key: "1" },
  { id: "layout", label: "LAYOUT", key: "2" },
  { id: "style", label: "STYLE", key: "3" },
  { id: "preview", label: "PREVIEW", key: "4" },
];

interface ModeSwitcherProps {
  mode: ComposeMode;
  onModeChange: (m: ComposeMode) => void;
}

export function ModeSwitcher({ mode, onModeChange }: ModeSwitcherProps) {
  return (
    <div className="flex shrink-0 border-b-[2px] border-ink-black bg-ink-black">
      {MODES.map((m, i) => (
        <button
          key={m.id}
          onClick={() => onModeChange(m.id)}
          className={cn(
            "flex flex-1 items-center justify-center gap-2 px-4 py-3 font-meta text-[0.65rem] tracking-[0.18em] transition-colors",
            mode === m.id
              ? "bg-pulp-paper text-ink-black"
              : "text-pulp-paper/50 hover:text-pulp-paper/80",
          )}
        >
          <span className="opacity-50">0{i + 1}</span>
          <span>{m.label}</span>
          <kbd
            className={cn(
              "ml-0.5 rounded border px-1 py-0.5 text-[0.48rem] opacity-40",
              mode === m.id ? "border-ink-black" : "border-pulp-paper/30",
            )}
          >
            {m.key}
          </kbd>
        </button>
      ))}
    </div>
  );
}
