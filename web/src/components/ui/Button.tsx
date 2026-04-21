import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "secondary" | "outline";
type Size = "xs" | "sm" | "md" | "lg";

const VARIANT_STYLES: Record<Variant, string> = {
  primary:
    "border-[2px] border-ink-black bg-hero-red text-bristol disabled:opacity-55",
  secondary:
    "border-[2px] border-ink-black bg-bristol text-ink-black disabled:opacity-40",
  outline:
    "border-[2px] border-ink-black bg-pulp-paper text-ink-black disabled:opacity-40",
};

const SIZE_STYLES: Record<Size, string> = {
  xs: "px-2.5 py-1.5 font-meta text-[0.62rem] tracking-[0.12em]",
  sm: "px-3.5 py-2 font-meta text-[0.72rem] tracking-[0.14em]",
  md: "px-4.5 py-2.5 font-meta text-[0.82rem] tracking-[0.14em]",
  lg: "px-7 py-3 font-display text-[1.05rem] font-bold tracking-[-0.02em]",
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
        "inline-flex min-w-0 cursor-pointer items-center justify-center gap-2 text-center leading-tight transition-[background-color,color,opacity,transform] duration-150 disabled:cursor-not-allowed",
        VARIANT_STYLES[variant],
        SIZE_STYLES[size],
        fullWidth && "w-full",
        className,
      )}
      {...props}
    />
  );
}
