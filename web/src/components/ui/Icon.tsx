import type { SVGProps, ReactElement } from "react";
import { cn } from "../../lib/cn";

/**
 * Small ink-weight line icons for sidebar items and buttons.
 * Uses currentColor so Tailwind text utilities control stroke color.
 */
type IconName =
  | "draft"
  | "assets"
  | "styles"
  | "history"
  | "export"
  | "settings"
  | "support"
  | "plus"
  | "arrow-right";

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 14, className, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={cn("shrink-0", className)}
      {...props}
    >
      {PATHS[name]}
    </svg>
  );
}

const PATHS: Record<IconName, ReactElement> = {
  draft: (
    <>
      <rect x="3" y="2" width="10" height="12" />
      <path d="M5 5h6M5 8h6M5 11h4" />
    </>
  ),
  assets: (
    <>
      <rect x="2" y="3" width="12" height="10" />
      <path d="M2 11l4-4 3 3 2-2 3 3" />
      <circle cx="6" cy="6" r="1" />
    </>
  ),
  styles: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 2.5v11M2.5 8h11" />
    </>
  ),
  history: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 4.5V8l2.5 1.5" />
    </>
  ),
  export: (
    <>
      <path d="M8 2v8M5 5l3-3 3 3" />
      <path d="M3 11v2h10v-2" />
    </>
  ),
  settings: (
    <>
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.3 3.3l1.4 1.4M11.3 11.3l1.4 1.4M3.3 12.7l1.4-1.4M11.3 4.7l1.4-1.4" />
    </>
  ),
  support: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M6 6.5a2 2 0 1 1 2.8 1.8c-.5.2-.8.5-.8 1v.2" />
      <circle cx="8" cy="11.8" r="0.4" fill="currentColor" stroke="none" />
    </>
  ),
  plus: <path d="M8 3v10M3 8h10" />,
  "arrow-right": <path d="M3 8h10M9 4l4 4-4 4" />,
};
