import type { ReactNode } from "react";
import { Card } from "./Card";

/**
 * Narrator-gold callout card — "NOTE FROM THE EDITOR" in the spec.
 * Used for advisory copy, editorial context, sidebar commentary.
 */
export function EditorNote({
  label = "NOTE FROM THE EDITOR",
  children,
  className,
}: {
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card tone="gold" className={className}>
      <div className="p-4 md:p-5">
        <div className="font-meta text-[0.5rem] tracking-[0.2em] uppercase text-ink-black/65">
          {label}
        </div>
        <div className="mt-3 text-[0.88rem] leading-6 text-ink-black/85">
          {children}
        </div>
      </div>
    </Card>
  );
}
