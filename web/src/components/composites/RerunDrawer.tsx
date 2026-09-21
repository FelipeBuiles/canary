import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { cn } from "../../lib/cn";
import { CreditAmount } from "../ui/CreditAmount";
import { Button } from "../ui/Button";
import { DestructiveButton } from "../ui/DestructiveButton";
import { ShortcutHint } from "../ui/ShortcutHint";
import type { StageName, StageCostEstimate } from "../../types/api";
import { STAGE_DISPLAY_NAMES } from "../../types/api";

export interface RerunDrawerProps {
  open: boolean;
  stageName: string;
  impactStages: StageName[];
  cost?: StageCostEstimate;
  itemsAtRisk?: string;
  onConfirm: () => void;
  onClose: () => void;
  confirmLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  extraBody?: ReactNode;
}

export function RerunDrawer({
  open,
  stageName,
  impactStages,
  cost,
  itemsAtRisk,
  onConfirm,
  onClose,
  confirmLabel,
  busy = false,
  disabled = false,
  extraBody,
}: RerunDrawerProps) {
  const drawerRef = useRef<HTMLDivElement | null>(null);

  useDialogFocus(drawerRef, { enabled: open, onClose });

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-end justify-center bg-ink-black/70"
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
          "relative max-h-[calc(100dvh-1rem)] overflow-y-auto w-full max-w-[700px] border-x-[2px] border-t-[2px] border-ink-black bg-pulp-paper text-ink-black",
          "animate-[slide-up-drawer_var(--motion-settle)_cubic-bezier(0.2,0.8,0.2,1)]",
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
                className="mb-2 inline-block border-[1.5px] border-hero-red px-2 py-0.5 font-meta text-xs tracking-[0.08em] uppercase text-hero-red"
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
              className="inline-flex min-h-11 shrink-0 items-center gap-2 border-[2px] border-ink-black/20 px-3 font-meta text-xs tracking-[0.08em] uppercase text-ink-muted hover:border-ink-black hover:text-ink-black"
            >
              Close <ShortcutHint>Esc</ShortcutHint>
            </button>
          </div>

          <p
            id="rerun-drawer-body"
            className="mt-4 text-[0.9rem] leading-6 text-ink-fade"
          >
            This will clear all downstream work and kick off a fresh run.
            Outputs below will be lost and need to be regenerated.
          </p>

          <div className="mt-4 border-[2px] border-warn-orange/35 bg-bristol p-4">
            <div className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
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
                    className="border-[1.5px] border-ink-black/30 bg-pulp-paper px-2 py-0.5 font-meta text-xs tracking-[0.08em] uppercase"
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
            {cost != null ? (
              <div className="mt-3">
                <div className="flex items-baseline gap-3">
                  <span className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
                    Estimated
                  </span>
                  <span className="font-display text-[1.1rem] font-bold">
                    <CreditAmount value={cost.estimate_credits} approximate />
                  </span>
                </div>
                {cost.reserved_credits > 0 && (
                  <div className="mt-1 flex items-baseline gap-3">
                    <span className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
                      Held
                    </span>
                    <span className="font-display text-[1.0rem]">
                      <CreditAmount value={cost.reserved_credits} />
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-3 flex items-baseline gap-3">
                <span className="font-meta text-xs tracking-[0.08em] uppercase text-ink-muted">
                  Expected use
                </span>
                <span className={cn(
                  "font-display text-[1.1rem] font-bold text-ink-muted",
                )}>
                  …
                </span>
              </div>
            )}
          </div>

          {extraBody && <div className="mt-4">{extraBody}</div>}

          <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
            <Button variant="outline" size="md" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <DestructiveButton
              size="md"
              onClick={onConfirm}
              disabled={busy || disabled}
            >
              {busy ? "Running…" : confirmLabel ?? `Rerun ${stageName}`}
            </DestructiveButton>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
