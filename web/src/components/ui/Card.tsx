import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Tone = "bristol" | "pulp" | "sidebar" | "red" | "gold" | "sage" | "ink";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Background / text tone. Default "bristol" (white). */
  tone?: Tone;
  /** Disable the signature hard-offset ink shadow. */
  flat?: boolean;
  /** Use a smaller shadow offset. */
  shadow?: "sm" | "md" | "lg";
}

const TONE_STYLES: Record<Tone, string> = {
  bristol: "bg-bristol text-ink-black",
  pulp: "bg-pulp-paper text-ink-black",
  sidebar: "bg-sidebar-tint text-ink-black",
  red: "bg-hero-red text-bristol",
  gold: "bg-narrator-gold text-ink-black",
  sage: "bg-archive-sage text-bristol",
  ink: "bg-ink-black text-bristol",
};

export function Card({
  className,
  tone = "bristol",
  flat = false,
  shadow = "md",
  ...props
}: CardProps) {
  const shadowClass = flat
    ? ""
    : shadow === "sm"
      ? "shadow-paper-sm"
      : shadow === "lg"
        ? "shadow-ink"
        : "shadow-paper";

  return (
    <div
      className={cn(
        "group border-[2px] border-ink-black",
        TONE_STYLES[tone],
        shadowClass,
        className,
      )}
      {...props}
    />
  );
}
