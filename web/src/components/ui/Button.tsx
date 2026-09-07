import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "onInk" | "secondary" | "outline";
type Size = "xs" | "sm" | "md" | "lg";

const VARIANT_STYLES: Record<Variant, string> = {
  primary:
    "border-[2px] border-ink-black bg-hero-red text-bristol shadow-ink-sm hover:translate-x-[1px] hover:translate-y-[1px] hover:bg-[#94141c] hover:shadow-[2px_2px_0_0_var(--color-ink-black)] active:translate-x-[4px] active:translate-y-[4px] active:shadow-none disabled:opacity-55 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0 disabled:hover:bg-hero-red",
  onInk:
    "border-[2px] border-bristol bg-hero-red text-bristol shadow-[4px_4px_0_0_var(--color-narrator-gold)] hover:translate-x-[1px] hover:translate-y-[1px] hover:bg-[#94141c] hover:shadow-[2px_2px_0_0_var(--color-narrator-gold)] active:translate-x-[4px] active:translate-y-[4px] active:shadow-none disabled:opacity-55 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0 disabled:hover:bg-hero-red",
  secondary:
    "border-[2px] border-ink-black bg-secondary-container text-on-secondary-container shadow-ink-sm hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-40 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0",
  outline:
    "border-[2px] border-ink-black bg-pulp-paper text-ink-black shadow-paper-sm hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-40 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0",
};

const SIZE_STYLES: Record<Size, string> = {
  xs: "min-h-11 px-2.5 py-1.5 font-meta text-xs tracking-[0.08em]",
  sm: "min-h-11 px-3.5 py-2 font-meta text-xs tracking-[0.1em]",
  md: "min-h-11 px-4.5 py-2.5 font-meta text-sm tracking-[0.1em]",
  lg: "min-h-12 px-7 py-3 font-meta text-sm font-bold tracking-[0.08em]",
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
    />
  );
}
