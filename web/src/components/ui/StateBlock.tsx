import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import { cn } from "../../lib/cn";

interface StateBlockProps {
  title: string;
  description?: string;
  icon?: IconName;
  minHeight?: string;
  tone?: "muted" | "danger";
  action?: ReactNode;
}

export function StateBlock({
  title,
  description,
  icon,
  minHeight = "min-h-[40vh]",
  tone = "muted",
  action,
}: StateBlockProps) {
  return (
    <div className={cn("flex items-center justify-center", minHeight)}>
      <div className="max-w-sm text-center">
        {icon && (
          <div
            className={cn(
              "mx-auto mb-4 flex h-12 w-12 items-center justify-center border-[2px] border-ink-black",
              tone === "danger" ? "bg-hero-red text-bristol" : "bg-pulp-paper text-ink-black/45",
            )}
          >
            <Icon name={icon} size={20} />
          </div>
        )}
        <div
          className={cn(
            "font-display text-[1.5rem] font-bold tracking-[-0.05em]",
            tone === "danger" ? "text-hero-red" : "text-ink-black/35",
          )}
        >
          {title}
        </div>
        {description && (
          <p className="mt-2 text-[0.82rem] leading-6 text-ink-black/50">{description}</p>
        )}
        {action && <div className="mt-4 flex justify-center">{action}</div>}
      </div>
    </div>
  );
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="flex items-center gap-3 border-[2px] border-ink-black bg-bristol px-4 py-3 shadow-paper-sm">
        <span className="h-2.5 w-2.5 animate-pulse bg-hero-red" />
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/45">{label}</p>
      </div>
    </div>
  );
}
