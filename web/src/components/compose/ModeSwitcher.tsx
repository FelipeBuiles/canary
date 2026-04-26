import { cn } from "../../lib/cn";
import type { EditSubMode } from "./compose-types";

interface EditSubTabsProps {
  subMode: EditSubMode;
  onSubModeChange: (m: EditSubMode) => void;
}

export function EditSubTabs({ subMode, onSubModeChange }: EditSubTabsProps) {
  return (
    <div className="flex shrink-0 border-b-[2px] border-ink-black bg-pulp-paper">
      {(["canvas", "script"] as EditSubMode[]).map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => onSubModeChange(m)}
          className={cn(
            "px-5 py-2 font-meta text-[0.52rem] tracking-[0.18em] transition-colors",
            m === subMode
              ? "border-b-[2px] border-ink-black bg-pulp-paper font-bold text-ink-black"
              : "text-ink-black/40 hover:text-ink-black/70",
          )}
        >
          {m.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
