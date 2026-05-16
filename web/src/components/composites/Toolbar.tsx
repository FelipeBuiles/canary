import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface ToolbarProps {
  children: ReactNode;
  className?: string;
  bottomRule?: boolean;
}

export function Toolbar({ children, className, bottomRule = true }: ToolbarProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2",
        bottomRule && "border-b-[2px] border-ink-black/10 pb-4",
        className,
      )}
    >
      {children}
    </div>
  );
}
