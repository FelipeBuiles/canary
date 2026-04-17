import { cn } from "../lib/cn";
import { useI18n } from "../i18n";

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
  const { t } = useI18n();
  return (
    <div className={cn("section-rule", className)}>
      <span className="font-meta text-ink-black">{t("SECTION")} {String(number).padStart(2, "0")}</span>
      <span className="text-ink-black/45">//</span>
      <span className="font-meta text-ink-black/80">{t(label)}</span>
    </div>
  );
}
