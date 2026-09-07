import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export interface RoomTab {
  key: string;
  label: ReactNode;
  count?: number;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
}

interface RoomTabsProps {
  tabs: RoomTab[];
  ariaLabel: string;
  className?: string;
}

export function RoomTabs({ tabs, ariaLabel, className }: RoomTabsProps) {
  return (
    <div
      className={cn("flex overflow-x-auto", className)}
      role="group"
      aria-label={ariaLabel}
    >
      {tabs.map((tab, idx) => {
        const isLast = idx === tabs.length - 1;
        return (
          <button
            key={tab.key}
            type="button"
            aria-pressed={tab.active}
            onClick={tab.onClick}
            disabled={tab.disabled}
            title={tab.title}
            className={cn(
              "min-h-11 shrink-0 border-[2px] px-5 py-2.5 font-meta text-xs tracking-[0.1em] uppercase transition-colors",
              !isLast && "border-r-0",
              tab.active
                ? "border-ink-black bg-ink-black text-bristol"
                : "border-ink-black/25 bg-pulp-paper text-ink-black hover:bg-bristol",
              tab.disabled && "cursor-not-allowed opacity-50",
            )}
          >
            {tab.label}
            {typeof tab.count === "number" && (
              <span className={cn("ml-2", tab.active ? "text-bristol/80" : "text-ink-muted")}>
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
