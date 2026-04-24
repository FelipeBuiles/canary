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
    <div className="mx-2 flex shrink-0 border-[2px] border-ink-black bg-ink-black">
      {MODES.map((m, i) => (
        <button
          key={m.id}
          onClick={() => onModeChange(m.id)}
          className={cn(
            "inline-flex min-h-8 items-center justify-center gap-2 border-r border-pulp-paper/10 px-4 py-2 font-meta text-[0.56rem] tracking-[0.18em] transition-colors md:min-w-[120px]",
            mode === m.id
              ? "bg-pulp-paper text-ink-black"
              : "text-pulp-paper/45 hover:text-pulp-paper/85",
          )}
        >
          <span className="opacity-50">0{i + 1}</span>
          <span>{m.label}</span>
          <kbd
            className={cn(
              "ml-1 rounded-[2px] border px-1 py-0.5 text-[0.46rem] opacity-55",
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
