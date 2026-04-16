import type { HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

interface TagProps extends HTMLAttributes<HTMLSpanElement> {}

export function Tag({ className, ...props }: TagProps) {
  return (
    <span
      className={cn(
        "border border-ink-black px-2 py-1 font-meta text-[0.44rem] tracking-[0.14em]",
        className,
      )}
      {...props}
    />
  );
}
