import { cn } from "../lib/cn";

type Tone = "gold" | "red" | "sage" | "bristol" | "ink";

const TONE_STYLES: Record<Tone, string> = {
  gold: "bg-narrator-gold text-ink-black border-ink-black",
  red: "bg-hero-red text-bristol border-ink-black",
  sage: "bg-archive-sage text-bristol border-ink-black",
  bristol: "bg-bristol text-ink-black border-ink-black",
  ink: "bg-ink-black text-bristol border-ink-black",
};

export function SectionLabel({
  children,
  tone = "gold",
  className,
}: {
  children: string;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex border-[2px] px-3 py-1 font-meta text-[0.5rem] tracking-[0.18em] uppercase",
        TONE_STYLES[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}
