import type { CSSProperties } from "react";
import { cn } from "../../lib/cn";

interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  aspect?: string;
  className?: string;
}

export function Skeleton({ width, height, aspect, className }: SkeletonProps) {
  const style: CSSProperties = {};
  if (width !== undefined) style.width = typeof width === "number" ? `${width}px` : width;
  if (height !== undefined) style.height = typeof height === "number" ? `${height}px` : height;
  if (aspect) style.aspectRatio = aspect;

  return (
    <div
      aria-hidden="true"
      className={cn("skeleton-benday block w-full", className)}
      style={style}
    />
  );
}
