import { useRef, type ReactNode } from "react";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";
import { CostBreakdown } from "../cost/CostBreakdown";
import { ShortcutHint } from "../ui/ShortcutHint";
import type { CostEstimate } from "../../types/api";

export interface ConfirmDrawerProps {
  open: boolean;
  title: string;
  body: string;
  cost?: CostEstimate;
  /** Optional content rendered between the body and the cost breakdown. */
  extraBody?: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}

export function ConfirmDrawer({
  open,
  title,
  body,
  cost,
  extraBody,
  confirmLabel = "Confirm",
  onConfirm,
  onClose,
  busy = false,
}: ConfirmDrawerProps) {
  const drawerRef = useRef<HTMLDivElement | null>(null);

  useDialogFocus(drawerRef, { enabled: open, onClose });

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-end justify-center bg-ink-black/70"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={drawerRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-drawer-title"
        aria-describedby="confirm-drawer-body"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "relative max-h-[calc(100dvh-1rem)] overflow-y-auto w-full max-w-[700px] border-x-[2px] border-t-[2px] border-ink-black bg-pulp-paper text-ink-black",
          "animate-[slide-up-drawer_var(--motion-settle)_cubic-bezier(0.2,0.8,0.2,1)]",
        )}
      >
        <style>{`
          @keyframes slide-up-drawer {
            from { transform: translateY(100%); opacity: 0.4; }
            to   { transform: translateY(0);    opacity: 1; }
          }
        `}</style>

        <div className="px-6 pt-5 pb-6 sm:px-8">
          <div className="flex items-start justify-between gap-4">
            <h2
              id="confirm-drawer-title"
              className="font-display text-[1.75rem] leading-[0.95] tracking-[-0.02em] uppercase"
            >
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Cancel"
              className="inline-flex min-h-11 shrink-0 items-center gap-2 border-[2px] border-ink-black/20 px-3 font-meta text-xs tracking-[0.08em] uppercase text-ink-muted hover:border-ink-black hover:text-ink-black"
            >
              Close <ShortcutHint>Esc</ShortcutHint>
            </button>
          </div>

          <p
            id="confirm-drawer-body"
            className="mt-4 text-[0.9rem] leading-6 text-ink-fade"
          >
            {body}
          </p>

          {extraBody && <div className="mt-4">{extraBody}</div>}

          {cost != null && <CostBreakdown cost={cost} />}

          <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
            <Button variant="outline" size="md" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="md"
              onClick={onConfirm}
              disabled={busy}
            >
              {busy ? "Starting…" : confirmLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
