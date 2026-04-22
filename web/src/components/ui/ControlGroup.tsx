import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

interface ControlGroupProps extends HTMLAttributes<HTMLDivElement> {
  label?: ReactNode;
  bleed?: boolean;
}

export function ControlGroup({
  label,
  bleed = false,
  className,
  children,
  ...props
}: ControlGroupProps) {
  return (
    <div
      role="group"
      aria-label={typeof label === "string" ? label : undefined}
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-1 sm:gap-1.5",
        !bleed && "sm:border-r-[2px] sm:border-ink-black/15 sm:pr-2 last:border-r-0",
        className,
      )}
      {...props}
    >
      {label && (
        <div className="mr-1 hidden font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45 lg:block">
          {label}
        </div>
      )}
      {children}
    </div>
  );
}
