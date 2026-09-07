import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Tone = "neutral" | "red" | "gold" | "sage" | "ink" | "pulp";

const TONE_STYLES: Record<Tone, string> = {
  neutral: "bg-bristol text-ink-black",
  red: "bg-hero-red text-bristol",
  gold: "bg-narrator-gold text-ink-black",
  sage: "bg-archive-sage text-bristol",
  ink: "bg-ink-black text-bristol",
  pulp: "bg-pulp-paper text-ink-black",
};

interface StatusPillProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function StatusPill({ tone = "neutral", className, ...props }: StatusPillProps) {
  return (
    <span
      className={cn(
        "inline-flex min-h-7 items-center border border-ink-black px-2 py-1 font-meta text-xs leading-tight tracking-[0.08em] uppercase",
        TONE_STYLES[tone],
        className,
      )}
      {...props}
    />
  );
}
