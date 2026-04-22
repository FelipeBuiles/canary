import type { ImgHTMLAttributes } from "react";
import { useState } from "react";
import { cn } from "../../lib/cn";
import { Skeleton } from "./Skeleton";

interface LazyImageProps extends ImgHTMLAttributes<HTMLImageElement> {
  aspect?: string;
  skeletonClassName?: string;
  containerClassName?: string;
}

export function LazyImage({
  aspect,
  skeletonClassName,
  containerClassName,
  className,
  onLoad,
  onError,
  alt,
  ...imgProps
}: LazyImageProps) {
  const [state, setState] = useState<"loading" | "loaded" | "error">("loading");

  return (
    <div
      className={cn("relative block overflow-hidden", containerClassName)}
      style={aspect ? { aspectRatio: aspect } : undefined}
    >
      {state !== "loaded" && (
        <Skeleton
          className={cn("absolute inset-0 h-full w-full", skeletonClassName)}
        />
      )}
      <img
        {...imgProps}
        alt={alt ?? ""}
        className={cn(
          "relative block w-full h-full object-cover transition-opacity duration-200",
          state === "loaded" ? "opacity-100" : "opacity-0",
          className,
        )}
        onLoad={(e) => {
          setState("loaded");
          onLoad?.(e);
        }}
        onError={(e) => {
          setState("error");
          onError?.(e);
        }}
      />
    </div>
  );
}
