import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Tone = "neutral" | "red" | "gold" | "sage" | "ink" | "pulp";

// Status pairs a tinted ground, a square mark and a word, so state never
// rides on hue alone. Ink marks work in progress.
const TONE_STYLES: Record<Tone, string> = {
  neutral: "text-ink-soft shadow-[inset_0_0_0_1px_rgb(27_28_21/0.12)]",
  red: "bg-chip-red text-status-blocked-text",
  gold: "bg-chip-gold text-on-gold",
  sage: "bg-chip-sage text-ready",
  ink: "bg-secondary-container text-on-secondary-container",
  pulp: "bg-pulp-paper text-ink-black",
};

interface StatusPillProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function StatusPill({ tone = "neutral", className, ...props }: StatusPillProps) {
  return (
    <span
      className={cn(
        "inline-flex min-h-[22px] items-center gap-1.5 px-2 py-0.5 font-meta text-xs font-medium leading-tight before:size-1.5 before:shrink-0 before:bg-current before:content-['']",
        TONE_STYLES[tone],
        className,
      )}
      {...props}
    />
  );
}
