import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/cn";

type Tone = "bristol" | "pulp" | "container" | "ink" | "red" | "gold";
type Shadow = "none" | "paper" | "paper-sm" | "ink" | "ink-sm" | "red";
type Padding = "none" | "sm" | "md" | "lg";
type Border = "hard" | "soft";

const TONE_STYLES: Record<Tone, string> = {
  bristol: "bg-bristol text-ink-black",
  pulp: "bg-pulp-paper text-ink-black",
  container: "bg-surface-container text-ink-black",
  ink: "bg-ink-black text-bristol",
  red: "bg-hero-red text-bristol",
  gold: "bg-narrator-gold text-ink-black",
};

const SHADOW_STYLES: Record<Shadow, string> = {
  none: "",
  paper: "shadow-paper",
  "paper-sm": "shadow-paper-sm",
  ink: "shadow-ink",
  "ink-sm": "shadow-ink-sm",
  red: "shadow-panel-red",
};

const PADDING_STYLES: Record<Padding, string> = {
  none: "",
  sm: "p-3",
  md: "p-4 md:p-5",
  lg: "p-5 md:p-8",
};

const BORDER_STYLES: Record<Border, string> = {
  hard: "border-ink-black",
  soft: "border-ink-black/10",
};

interface SurfaceProps extends HTMLAttributes<HTMLDivElement> {
  tone?: Tone;
  shadow?: Shadow;
  padding?: Padding;
  border?: Border;
  benday?: boolean;
}

export function Surface({
  tone = "bristol",
  shadow = "paper",
  padding = "none",
  border = "hard",
  benday = false,
  className,
  ...props
}: SurfaceProps) {
  return (
    <div
      className={cn(
        "border-[2px]",
        BORDER_STYLES[border],
        TONE_STYLES[tone],
        SHADOW_STYLES[shadow],
        PADDING_STYLES[padding],
        benday && "benday-paper",
        className,
      )}
      {...props}
    />
  );
}

interface SurfaceHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  kicker?: ReactNode;
  title: ReactNode;
  actions?: ReactNode;
}

export function SurfaceHeader({
  kicker,
  title,
  actions,
  className,
  ...props
}: SurfaceHeaderProps) {
  return (
    <div
      className={cn("ui-surface-header flex items-center justify-between gap-3", className)}
      {...props}
    >
      <div className="min-w-0">
        {kicker && <div className="ui-kicker">{kicker}</div>}
        <div className="ui-title truncate">{title}</div>
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </div>
  );
}
