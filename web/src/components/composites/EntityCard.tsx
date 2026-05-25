import type { ReactNode } from "react";
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
  className?: string;
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
  className,
}: EntityCardProps) {
  const borderClass = active
    ? "border-ink-black shadow-ink"
    : interactive
      ? "border-ink-black/8 hover:border-ink-black/24"
      : "border-ink-black/8";

  const cursorClass = interactive || onClick ? "cursor-pointer" : "";

  return (
    <article
      onClick={onClick}
      className={cn(
        "flex flex-col overflow-hidden border-[2px] bg-bristol transition-[box-shadow,border-color] duration-150",
        borderClass,
        cursorClass,
        className,
      )}
    >
      {media}
      <div className={cn("flex flex-1 flex-col min-h-0", PADDING_CLASS[padding])}>{children}</div>
      {footer}
    </article>
  );
}
