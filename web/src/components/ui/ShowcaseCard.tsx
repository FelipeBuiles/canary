import type { ReactNode } from "react";
import { Card } from "./Card";
import { cn } from "../../lib/cn";

/**
 * White "showcase" card with a divided title band and content area —
 * mirrors "COLOR PALETTE" and "TYPOGRAPHY SCALE" in the spec.
 */
export function ShowcaseCard({
  label,
  title,
  meta,
  children,
  className,
}: {
  label?: string;
  title: string;
  meta?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("flex flex-col", className)}>
      <div className="flex items-end justify-between gap-4 border-b-[2px] border-ink-black p-4 md:px-5 md:pt-5 md:pb-4">
        <div>
          {label && (
            <div className="font-meta text-[0.5rem] tracking-[0.2em] uppercase text-ink-black/55">
              {label}
            </div>
          )}
          <h3 className="mt-1 font-display text-[1.55rem] font-bold leading-none tracking-[-0.05em] text-ink-black">
            {title}
          </h3>
        </div>
        {meta && (
          <div className="font-meta text-[0.48rem] tracking-[0.18em] uppercase text-ink-black/45">
            {meta}
          </div>
        )}
      </div>
      <div className="flex-1 p-4 md:p-5">{children}</div>
    </Card>
  );
}
