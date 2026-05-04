import { cn } from "../../lib/cn";
import type { EditSubMode } from "./compose-types";

interface EditSubTabsProps {
  subMode: EditSubMode;
  onSubModeChange: (m: EditSubMode) => void;
  issueCount?: number;
}

export function EditSubTabs({ subMode, onSubModeChange, issueCount = 0 }: EditSubTabsProps) {
  return (
    <div className="flex shrink-0 border-b-[2px] border-ink-black bg-pulp-paper">
      {(["canvas", "script", "issues"] as EditSubMode[]).map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => onSubModeChange(m)}
          className={cn(
            "relative flex items-center px-5 py-2 font-meta text-[0.52rem] tracking-[0.18em] transition-colors",
            m === subMode
              ? "border-b-[2px] border-ink-black bg-pulp-paper font-bold text-ink-black"
              : "text-ink-black/40 hover:text-ink-black/70",
          )}
        >
          {m.toUpperCase()}
          {m === "issues" && issueCount > 0 && (
            <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-hero-red px-1 font-meta text-[0.48rem] text-bristol">
              {issueCount}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
