import { cn } from "../../lib/cn";

interface CreditAmountProps {
  value: number | string;
  approximate?: boolean;
  sign?: "+" | "-";
  /** Use only in compact counters where the mark replaces the word credits. */
  showMark?: boolean;
  showLabel?: boolean;
  label?: string;
  className?: string;
  markClassName?: string;
}

/**
 * Canonical credit notation. Prose and transactional costs default to
 * "~30 credits". Compact counters can opt into "◆ 30"; the accessible name
 * always remains plain-language.
 */
export function CreditAmount({
  value,
  approximate = false,
  sign,
  showMark = false,
  showLabel = true,
  label = value === 1 ? "credit" : "credits",
  className,
  markClassName,
}: CreditAmountProps) {
  const formatted = typeof value === "number" ? value.toLocaleString() : value;
  const visibleText = `${approximate ? "~" : ""}${sign ?? ""}${formatted}${showLabel ? ` ${label}` : ""}`;
  const spokenText = `${approximate ? "about " : ""}${sign === "+" ? "plus " : sign === "-" ? "minus " : ""}${formatted} ${label}`;

  return (
    <span className={cn("inline-flex items-baseline tabular-nums", showMark && "gap-[0.42em]", className)} aria-label={spokenText}>
      {showMark && (
        <span aria-hidden="true" className={cn("text-[0.72em] leading-none", markClassName)}>◆</span>
      )}
      <span aria-hidden="true">{visibleText}</span>
    </span>
  );
}

/** Decorative navigation mark for links whose visible label already says Credits. */
export function CreditMark({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cn("leading-none", className)}>◆</span>;
}
