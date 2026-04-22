import { useEffect, useRef } from "react";
import { cn } from "../../lib/cn";
import { Button } from "./Button";
import { DestructiveButton } from "./DestructiveButton";
import type { StageName } from "../../types/api";
import { STAGE_DISPLAY_NAMES } from "../../types/api";

export interface RerunDrawerProps {
  open: boolean;
  stageName: string;
  impactStages: StageName[];
  estimatedCost: string;
  costIsPlaceholder?: boolean;
  itemsAtRisk?: string;
  onConfirm: () => void;
  onClose: () => void;
  confirmLabel?: string;
  busy?: boolean;
}

export function RerunDrawer({
  open,
  stageName,
  impactStages,
  estimatedCost,
  costIsPlaceholder = false,
  itemsAtRisk,
  onConfirm,
  onClose,
  confirmLabel,
  busy = false,
}: RerunDrawerProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    confirmRef.current?.focus();

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
        aria-labelledby="rerun-drawer-title"
        aria-describedby="rerun-drawer-body"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "relative w-full max-w-[700px] border-x-[2px] border-t-[2px] border-ink-black bg-pulp-paper text-ink-black",
          "animate-[slide-up-drawer_320ms_cubic-bezier(0.2,0.8,0.2,1)]",
        )}
        style={{ borderTop: "4px solid var(--color-warn-orange)" }}
      >
        <style>{`
          @keyframes slide-up-drawer {
            from { transform: translateY(100%); opacity: 0.4; }
            to   { transform: translateY(0);    opacity: 1; }
          }
        `}</style>

        <div className="px-6 pt-5 pb-6 sm:px-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div
                className="mb-2 inline-block border-[1.5px] border-[var(--color-warn-orange)] px-2 py-0.5 font-meta text-[0.58rem] tracking-[0.2em] uppercase text-[var(--color-warn-orange)]"
              >
                Destructive Action
              </div>
              <h2
                id="rerun-drawer-title"
                className="font-display text-[1.75rem] leading-[0.95] tracking-[-0.02em] uppercase"
              >
                Rerun {stageName}?
              </h2>
            </div>
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
            id="rerun-drawer-body"
            className="mt-4 text-[0.9rem] leading-6 text-ink-fade"
          >
            This will clear all downstream work and kick off a fresh run.
            Outputs below will be lost and need to be regenerated.
          </p>

          <div
            className="mt-4 bg-bristol p-4"
            style={{ borderLeft: "3px solid var(--color-warn-orange)" }}
          >
            <div className="font-meta text-[0.58rem] tracking-[0.16em] uppercase text-ink-black/60">
              Impact
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {impactStages.length === 0 ? (
                <span className="font-meta text-[0.72rem] text-ink-fade">
                  No downstream rooms.
                </span>
              ) : (
                impactStages.map((s) => (
                  <span
                    key={s}
                    className="border-[1.5px] border-ink-black/30 bg-pulp-paper px-2 py-0.5 font-meta text-[0.62rem] tracking-[0.14em] uppercase"
                  >
                    {STAGE_DISPLAY_NAMES[s]}
                  </span>
                ))
              )}
            </div>
            {itemsAtRisk && (
              <p className="mt-3 text-[0.82rem] leading-5 text-ink-black">
                {itemsAtRisk}
              </p>
            )}
            <div className="mt-3 flex items-baseline gap-3">
              <span className="font-meta text-[0.58rem] tracking-[0.16em] uppercase text-ink-black/60">
                Estimated cost{costIsPlaceholder ? " (placeholder)" : ""}
              </span>
              <span className="font-display text-[1.1rem] font-bold">
                {estimatedCost}
              </span>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
            <Button variant="outline" size="md" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <DestructiveButton
              ref={confirmRef}
              size="md"
              onClick={onConfirm}
              disabled={busy}
            >
              {busy ? "Running…" : confirmLabel ?? `Rerun ${stageName}`}
            </DestructiveButton>
          </div>
        </div>
      </div>
    </div>
  );
}
