import { useEffect, useRef } from "react";
import { cn } from "../../lib/cn";
import { Button } from "./Button";
import { DestructiveButton } from "./DestructiveButton";
import { CostBreakdown } from "../cost/CostBreakdown";
import type { CostEstimate, PromptWarning } from "../../types/api";

export interface WarningOverrideDrawerProps {
  open: boolean;
  warnings: PromptWarning[];
  cost?: CostEstimate;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}

export function WarningOverrideDrawer({
  open,
  warnings,
  cost,
  onConfirm,
  onClose,
  busy = false,
}: WarningOverrideDrawerProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);
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

  // Group warnings by panel
  const byPanel = new Map<string, PromptWarning[]>();
  for (const w of warnings) {
    const key = `${w.scene_id}:${w.panel_number}`;
    const list = byPanel.get(key) ?? [];
    list.push(w);
    byPanel.set(key, list);
  }

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
        aria-labelledby="warning-drawer-title"
        aria-describedby="warning-drawer-body"
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
                className="mb-2 inline-block border-[1.5px] px-2 py-0.5 font-meta text-[0.58rem] tracking-[0.2em] uppercase"
                style={{ borderColor: "var(--color-warn-orange)", color: "var(--color-warn-orange)" }}
              >
                Prompt Warnings
              </div>
              <h2
                id="warning-drawer-title"
                className="font-display text-[1.75rem] leading-[0.95] tracking-[-0.02em] uppercase"
              >
                Review Prompt Warnings
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
            id="warning-drawer-body"
            className="mt-4 text-[0.9rem] leading-6 text-ink-fade"
          >
            These warnings may cause generation issues. You can continue, but consider fixing them first to get the best results.
          </p>

          {/* Warning list grouped by panel */}
          <div
            className="mt-4 max-h-[240px] overflow-y-auto bg-bristol p-4"
            style={{ borderLeft: "3px solid var(--color-warn-orange)" }}
          >
            <div className="font-meta text-[0.58rem] tracking-[0.16em] uppercase text-ink-black/60">
              {warnings.length} Warning{warnings.length !== 1 ? "s" : ""}
            </div>
            <div className="mt-3 space-y-3">
              {Array.from(byPanel.entries()).map(([key, panelWarnings]) => {
                const first = panelWarnings[0];
                const panelLabel = `Scene ${first.scene_id.replace(/_/g, " ")} · Panel ${String(first.panel_number).padStart(2, "0")}`;
                return (
                  <div key={key}>
                    <div className="mb-1.5 font-meta text-[0.6rem] font-bold tracking-[0.12em] uppercase text-ink-black/45">
                      {panelLabel}
                    </div>
                    <div className="space-y-1.5">
                      {panelWarnings.map((w) => (
                        <div key={w.code} className="flex items-start gap-2.5 bg-pulp-paper px-3 py-2.5">
                          <span
                            className="mt-0.5 shrink-0 font-meta text-[0.75rem] leading-none"
                            style={{ color: "var(--color-warn-orange)" }}
                            aria-hidden="true"
                          >
                            ⚠
                          </span>
                          <div>
                            <div className="font-meta text-[0.72rem] font-bold tracking-[0.06em] text-ink-black">
                              {w.label}
                            </div>
                            <div className="mt-0.5 font-body text-[0.78rem] leading-[1.4] text-ink-black/65">
                              {w.detail}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {cost != null && (
            <div className="mt-4">
              <CostBreakdown cost={cost} />
            </div>
          )}

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
              {busy ? "Starting…" : "Approve Anyway"}
            </DestructiveButton>
          </div>
        </div>
      </div>
    </div>
  );
}
