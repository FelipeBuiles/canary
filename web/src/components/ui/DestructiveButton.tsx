import type { ButtonHTMLAttributes, Ref } from "react";
import { cn } from "../../lib/cn";

type Size = "xs" | "sm" | "md";

const SIZE_STYLES: Record<Size, string> = {
  xs: "min-h-8 px-2.5 py-1.5 font-meta text-[0.62rem] tracking-[0.12em]",
  sm: "min-h-9 px-3.5 py-2 font-meta text-[0.72rem] tracking-[0.14em]",
  md: "min-h-11 px-4.5 py-2.5 font-meta text-[0.82rem] tracking-[0.14em]",
};

interface DestructiveButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  size?: Size;
  fullWidth?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

/**
 * Visually distinct destructive action (rerun / regenerate / clear).
 * Orange outline + hero-red focus ring so it never reads as the primary CTA.
 */
export function DestructiveButton({
  size = "sm",
  fullWidth = false,
  className,
  type = "button",
  ref,
  ...props
}: DestructiveButtonProps) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex min-w-0 cursor-pointer items-center justify-center gap-2 text-center uppercase leading-tight transition-[background-color,color,box-shadow,transform] duration-150 disabled:cursor-not-allowed disabled:opacity-40",
        "border-[2px] border-[var(--color-warn-orange)] bg-transparent text-[var(--color-warn-orange)]",
        "hover:bg-[var(--color-warn-orange)] hover:text-pulp-paper",
        "active:translate-x-[1px] active:translate-y-[1px]",
        SIZE_STYLES[size],
        fullWidth && "w-full",
        className,
      )}
      {...props}
    />
  );
}
