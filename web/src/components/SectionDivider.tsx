import { cn } from "../lib/cn";

/**
 * "SECTION 01 // PALETTE & PULP" rule line used above card grids in the spec.
 * Shows a small-caps label followed by an ink rule to the right edge.
 */
export function SectionDivider({
  number,
  label,
  className,
}: {
  number: string | number;
  label: string;
  className?: string;
}) {
  return (
    <div className={cn("section-rule", className)}>
      <span className="font-meta text-ink-black">SECTION {String(number).padStart(2, "0")}</span>
      <span className="text-ink-black/45">//</span>
      <span className="font-meta text-ink-black/80">{label}</span>
    </div>
  );
}
