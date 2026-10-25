import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";
import { safeReplayLabel } from "../../lib/replayPrivacy";

type Variant = "primary" | "onInk" | "secondary" | "outline";
type Size = "xs" | "sm" | "md" | "lg";

// One strong primary per view; secondaries step back from the artwork.
const VARIANT_STYLES: Record<Variant, string> = {
  primary:
    "border-[2px] border-ink-black bg-hero-red font-semibold text-bristol shadow-press hover:translate-x-[1px] hover:translate-y-[1px] hover:bg-hero-red-press hover:shadow-[2px_2px_0_0_var(--color-ink-black)] active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-55 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0 disabled:hover:bg-hero-red",
  onInk:
    "border-[2px] border-bristol bg-hero-red font-semibold text-bristol shadow-[3px_3px_0_0_var(--color-narrator-gold)] hover:translate-x-[1px] hover:translate-y-[1px] hover:bg-hero-red-press hover:shadow-[2px_2px_0_0_var(--color-narrator-gold)] active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-55 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0 disabled:hover:bg-hero-red",
  secondary:
    "border border-ink-black bg-ink-black text-pulp-paper hover:bg-ink-black/85 disabled:opacity-40 disabled:hover:bg-ink-black",
  outline:
    "border border-ink-black/55 bg-transparent text-ink-black hover:border-ink-black hover:bg-sidebar-tint disabled:opacity-40 disabled:hover:border-ink-black/55 disabled:hover:bg-transparent",
};

const SIZE_STYLES: Record<Size, string> = {
  xs: "min-h-8 px-2.5 py-1 font-meta text-xs tracking-[0.02em]",
  sm: "min-h-8 px-3 py-1.5 font-meta text-[0.8125rem] tracking-[0.02em]",
  md: "min-h-10 px-4 py-2 font-meta text-[0.8125rem] tracking-[0.02em]",
  lg: "min-h-12 px-6 py-3 font-meta text-sm font-semibold tracking-[0.02em]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  fullWidth?: boolean;
}

export function Button({
  variant = "primary",
  size = "md",
  fullWidth = false,
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex min-w-0 cursor-pointer items-center justify-center gap-2 text-center leading-tight transition-[background-color,box-shadow,color,opacity,transform] duration-[var(--motion-press)] ease-[cubic-bezier(0.22,1,0.36,1)] disabled:cursor-not-allowed",
        VARIANT_STYLES[variant],
        SIZE_STYLES[size],
        fullWidth && "w-full",
        className,
      )}
      {...props}
      data-ph-safe-label={safeReplayLabel(props.children)}
    />
  );
}
