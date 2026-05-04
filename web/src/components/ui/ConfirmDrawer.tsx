import { useEffect, useRef } from "react";
import { cn } from "../../lib/cn";
import { Button } from "./Button";
import { CostBreakdown } from "../cost/CostBreakdown";
import type { CostEstimate } from "../../types/api";

export interface ConfirmDrawerProps {
  open: boolean;
  title: string;
  body: string;
  cost?: CostEstimate;
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
  confirmLabel = "Confirm",
  onConfirm,
  onClose,
  busy = false,
}: ConfirmDrawerProps) {
  const drawerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !drawerRef.current) return;
      const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-end justify-center bg-ink-black/55 backdrop-blur-[2px]"
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
          "relative w-full max-w-[700px] border-x-[2px] border-t-[2px] border-ink-black bg-pulp-paper text-ink-black",
          "animate-[slide-up-drawer_320ms_cubic-bezier(0.2,0.8,0.2,1)]",
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
              className="shrink-0 border-[2px] border-ink-black/20 px-2 py-1 font-meta text-[0.65rem] tracking-[0.14em] uppercase text-ink-black/60 hover:border-ink-black hover:text-ink-black"
            >
              Esc
            </button>
          </div>

          <p
            id="confirm-drawer-body"
            className="mt-4 text-[0.9rem] leading-6 text-ink-fade"
          >
            {body}
          </p>

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
