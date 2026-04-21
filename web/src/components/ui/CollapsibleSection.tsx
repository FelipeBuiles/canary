import { useState, useEffect, type ReactNode } from "react";
import { Icon } from "./Icon";
import { cn } from "../../lib/cn";

interface CollapsibleSectionProps {
  title: string;
  children: ReactNode;
  defaultExpanded?: boolean;
  preview?: ReactNode;
  actions?: ReactNode;
  className?: string;
  storageKey?: string;
}

function loadExpanded(key: string, fallback: boolean): boolean {
  try {
    const stored = localStorage.getItem(`collapse:${key}`);
    return stored !== null ? stored === "true" : fallback;
  } catch {
    return fallback;
  }
}

function saveExpanded(key: string, value: boolean): void {
  try {
    localStorage.setItem(`collapse:${key}`, String(value));
  } catch {
    // ignore quota errors
  }
}

export function CollapsibleSection({
  title,
  children,
  defaultExpanded = false,
  preview,
  actions,
  className,
  storageKey,
}: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(() =>
    storageKey ? loadExpanded(storageKey, defaultExpanded) : defaultExpanded,
  );

  useEffect(() => {
    if (storageKey) {
      saveExpanded(storageKey, expanded);
    }
  }, [expanded, storageKey]);

  return (
    <div className={cn("border-b border-panel-line", className)}>
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 py-2 text-left hover:bg-ink-black/5 transition-colors"
      >
        <Icon
          name={expanded ? "chevron-down" : "chevron-left"}
          size={12}
          className="shrink-0 text-ink-black/45"
        />
        <span className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/65 uppercase">
          {title}
        </span>
        {preview && !expanded && (
          <span className="text-[0.72rem] text-ink-black/50 truncate ml-2">
            {preview}
          </span>
        )}
        {actions && expanded && <div className="ml-auto">{actions}</div>}
      </button>
      {expanded && <div className="pb-3 pl-5">{children}</div>}
    </div>
  );
}
