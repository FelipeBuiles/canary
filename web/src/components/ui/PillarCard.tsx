import type { ReactNode } from "react";
import { Card } from "./Card";

/**
 * Red inverse call-out card — "THE CORE PILLARS" in the spec.
 * Used for mission statements, key principles, highlighted lists.
 */
export function PillarCard({
  label,
  title,
  children,
  className,
}: {
  label?: string;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card tone="red" className={className}>
      <div className="p-4 md:p-5">
        {label && (
          <div className="font-meta text-[0.5rem] tracking-[0.2em] uppercase text-bristol/75">
            {label}
          </div>
        )}
        <h3 className="mt-2 font-display text-[1.55rem] font-bold leading-[0.95] tracking-[-0.04em] text-bristol">
          {title}
        </h3>
        <div className="mt-4 space-y-2 text-[0.82rem] leading-6 text-bristol/90">
          {children}
        </div>
      </div>
    </Card>
  );
}

export function PillarItem({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2 border-t border-bristol/25 pt-2 first:border-t-0 first:pt-0">
      <span className="mt-1 block h-[6px] w-[6px] shrink-0 bg-bristol" />
      <span>{children}</span>
    </div>
  );
}
