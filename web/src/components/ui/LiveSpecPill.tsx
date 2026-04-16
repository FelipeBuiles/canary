import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

/**
 * Bottom-right "LIVE SPEC ACTIVE" pill button from the spec.
 * A persistent floating indicator with a pulsing dot. Render at the app root.
 */
export function LiveSpecPill({
  label = "LIVE SPEC ACTIVE",
  active = true,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  label?: string;
  active?: boolean;
}) {
  return (
    <button
      className={cn(
        "fixed bottom-[50px] right-5 z-40 flex items-center gap-2 rounded-full border-[2px] border-ink-black px-4 py-2 font-meta text-[0.56rem] tracking-[0.2em] uppercase shadow-ink-sm transition-transform hover:-translate-y-[1px]",
        active
          ? "bg-archive-sage text-bristol"
          : "bg-pulp-paper text-ink-black/55",
        className,
      )}
      {...props}
    >
      <span
        className={cn(
          "block h-[7px] w-[7px] rounded-full border border-ink-black",
          active ? "bg-bristol animate-pulse" : "bg-ink-black/20",
        )}
      />
      {label}
    </button>
  );
}
