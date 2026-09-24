import type { KeyboardEvent, ReactNode } from "react";
import { cn } from "../../lib/cn";

type EntityCardPadding = "cozy" | "tight" | "comfortable";

interface EntityCardProps {
  children: ReactNode;
  media?: ReactNode;
  footer?: ReactNode;
  active?: boolean;
  interactive?: boolean;
  padding?: EntityCardPadding;
  onClick?: () => void;
  ariaLabel?: string;
  ariaPressed?: boolean;
  className?: string;
  /**
   * Span this many rows of a parent grid and align each child to them
   * (CSS subgrid), so sibling cards line up section by section. Children are
   * placed directly, one per row, and own their padding.
   */
  subgridRows?: number;
}

const PADDING_CLASS: Record<EntityCardPadding, string> = {
  cozy: "p-3",
  tight: "p-5",
  comfortable: "px-7 py-6",
};

export function EntityCard({
  children,
  media,
  footer,
  active = false,
  interactive = false,
  padding = "comfortable",
  onClick,
  ariaLabel,
  ariaPressed,
  className,
  subgridRows,
}: EntityCardProps) {
  const borderClass = active
    ? "border-ink-black shadow-ink"
    : interactive
      ? "border-ink-black/8 hover:border-ink-black/24"
      : "border-ink-black/8";

  const cursorClass = interactive || onClick ? "cursor-pointer" : "";

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== event.currentTarget || !onClick || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onClick();
  };

  return (
    <article
      onClick={onClick}
      onKeyDown={handleKeyDown}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={ariaLabel}
      aria-pressed={onClick ? ariaPressed : undefined}
      style={subgridRows ? { gridRow: `span ${subgridRows}` } : undefined}
      className={cn(
        "relative overflow-hidden",
        subgridRows ? "grid grid-rows-subgrid gap-y-0" : "flex flex-col",
        "border-[2px] bg-bristol transition-[box-shadow,border-color,transform] duration-[180ms] ease-[cubic-bezier(0.22,1,0.36,1)] focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-4 focus-visible:outline-hero-red",
        borderClass,
        active && "-translate-x-[2px] -translate-y-[2px]",
        interactive && !active && "hover:-translate-y-[2px]",
        cursorClass,
        className,
      )}
    >
      {active && (
        <span
          aria-hidden="true"
          className="absolute right-0 top-0 z-10 h-4 w-4 bg-narrator-gold [clip-path:polygon(100%_0,100%_100%,0_0)]"
        />
      )}
      {media}
      {subgridRows
        ? children
        : <div className={cn("flex flex-1 flex-col min-h-0", PADDING_CLASS[padding])}>{children}</div>}
      {footer}
    </article>
  );
}
