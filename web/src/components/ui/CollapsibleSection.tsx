import { useState, type ReactNode } from "react";
import { Icon } from "./Icon";
import { cn } from "../../lib/cn";

interface CollapsibleSectionProps {
  title: string;
  children: ReactNode;
  defaultExpanded?: boolean;
  preview?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function CollapsibleSection({
  title,
  children,
  defaultExpanded = false,
  preview,
  actions,
  className,
}: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

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
