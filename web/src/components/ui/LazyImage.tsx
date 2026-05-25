import type { ImgHTMLAttributes } from "react";
import { useState } from "react";
import { cn } from "../../lib/cn";
import { Skeleton } from "./Skeleton";

interface LazyImageProps extends ImgHTMLAttributes<HTMLImageElement> {
  aspect?: string;
  skeletonClassName?: string;
  containerClassName?: string;
  preserveAspectBox?: boolean;
}

export function LazyImage({
  aspect,
  skeletonClassName,
  containerClassName,
  className,
  preserveAspectBox = false,
  onLoad,
  onError,
  alt,
  ...imgProps
}: LazyImageProps) {
  const [state, setState] = useState<"loading" | "loaded" | "error">("loading");

  return (
    <div
      className={cn(
        containerClassName?.includes("absolute") ? "absolute" : "relative",
        "overflow-hidden",
        preserveAspectBox ? "flex items-center justify-center" : "block",
        containerClassName,
      )}
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
          preserveAspectBox
            ? "relative block h-full w-full object-contain transition-opacity duration-200"
            : "relative block w-full h-full object-cover transition-opacity duration-200",
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
