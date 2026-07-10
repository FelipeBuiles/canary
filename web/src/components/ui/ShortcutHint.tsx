import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface ShortcutHintProps {
  children: ReactNode;
  className?: string;
}

/** A consistent visual hint for keyboard actions that are actually supported. */
export function ShortcutHint({ children, className }: ShortcutHintProps) {
  return (
    <kbd
      className={cn(
        "inline-flex min-h-5 min-w-5 items-center justify-center border border-current/20 bg-current/5 px-1 font-meta text-[0.46rem] font-normal leading-none tracking-[0.08em] opacity-70",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
