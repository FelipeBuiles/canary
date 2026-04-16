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
  xs: "px-2 py-1 font-meta text-[0.42rem] tracking-[0.12em]",
  sm: "px-3 py-1 font-meta text-[0.52rem] tracking-[0.16em]",
  md: "px-4 py-2 font-meta text-[0.58rem] tracking-[0.16em]",
  lg: "px-6 py-2.5 font-display text-[0.9rem] font-bold tracking-[-0.03em]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(VARIANT_STYLES[variant], SIZE_STYLES[size], className)}
      {...props}
    />
  );
}
