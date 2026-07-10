import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "secondary" | "outline";
type Size = "xs" | "sm" | "md" | "lg";

const VARIANT_STYLES: Record<Variant, string> = {
  primary:
    "border-[2px] border-ink-black bg-[linear-gradient(135deg,var(--color-hero-red),#d93537)] text-bristol shadow-panel-red hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-55 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0",
  secondary:
    "border-[2px] border-ink-black bg-secondary-container text-on-secondary-container shadow-ink-sm hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-40 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0",
  outline:
    "border-[2px] border-ink-black bg-pulp-paper text-ink-black shadow-paper-sm hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-40 disabled:shadow-none disabled:hover:translate-x-0 disabled:hover:translate-y-0",
};

const SIZE_STYLES: Record<Size, string> = {
  xs: "min-h-9 px-2.5 py-1.5 font-meta text-[0.62rem] tracking-[0.12em]",
  sm: "min-h-11 px-3.5 py-2 font-meta text-[0.72rem] tracking-[0.14em]",
  md: "min-h-11 px-4.5 py-2.5 font-meta text-[0.82rem] tracking-[0.14em]",
  lg: "min-h-12 px-7 py-3 font-display text-[1.05rem] font-bold tracking-[-0.02em]",
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
        "inline-flex min-w-0 cursor-pointer items-center justify-center gap-2 text-center leading-tight transition-[background-color,box-shadow,color,opacity,transform] duration-150 disabled:cursor-not-allowed",
        VARIANT_STYLES[variant],
        SIZE_STYLES[size],
        fullWidth && "w-full",
        className,
      )}
      {...props}
    />
  );
}
