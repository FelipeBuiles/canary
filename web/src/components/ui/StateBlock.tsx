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
              tone === "danger" ? "bg-hero-red text-bristol" : "bg-narrator-gold text-ink-black",
            )}
          >
            <Icon name={icon} size={20} />
          </div>
        )}
        <div
          className={cn(
            "font-display text-[1.5rem] font-black uppercase tracking-[-0.03em]",
            tone === "danger" ? "text-hero-red" : "text-ink-black",
          )}
        >
          {title}
        </div>
        {description && (
          <p className="mt-2 font-body text-[0.84rem] font-semibold leading-6 text-ink-muted">{description}</p>
        )}
        {action && <div className="mt-4 flex justify-center">{action}</div>}
      </div>
    </div>
  );
}

export function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center" role="status" aria-live="polite">
      <div className="flex items-center gap-3 border-[2px] border-ink-black bg-bristol px-4 py-3 shadow-paper-sm">
        <span aria-hidden="true" className="animate-press-blink h-3 w-3 bg-hero-red" />
        <p className="font-meta text-[0.68rem] font-bold tracking-[0.1em] text-ink-muted">{label}</p>
      </div>
    </div>
  );
}
