import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";
import { TextField } from "../ui/Field";

export interface ConfirmModalProps {
  open: boolean;
  title: string;
  body: string;
  confirmInput?: string;
  confirmLabel?: string;
  busy?: boolean;
  destructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmModal({
  open,
  title,
  body,
  confirmInput,
  confirmLabel = "Confirm",
  busy = false,
  destructive = false,
  onConfirm,
  onClose,
}: ConfirmModalProps) {
  const modalRef = useRef<HTMLDivElement | null>(null);
  const [input, setInput] = useState("");

  const inputMatches = !confirmInput || input === confirmInput;

  useEffect(() => {
    if (!open) return;
    setInput("");
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !modalRef.current) return;
      const focusable = modalRef.current.querySelectorAll<HTMLElement>(
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
      className="fixed inset-0 z-[120] flex items-center justify-center bg-ink-black/55 backdrop-blur-[2px]"
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={modalRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        aria-describedby="confirm-modal-body"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[500px] border-[2px] border-ink-black bg-pulp-paper text-ink-black shadow-ink"
      >
        <div className="px-6 pt-5 pb-6 sm:px-8">
          <div className="flex items-start justify-between gap-4">
            <h2
              id="confirm-modal-title"
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
            id="confirm-modal-body"
            className="mt-4 text-[0.9rem] leading-6 text-ink-fade"
          >
            {body}
          </p>

          {confirmInput && (
            <div className="mt-4">
              <label className="block font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/55 mb-2">
                TYPE <span className="font-bold text-ink-black">{confirmInput}</span> TO CONFIRM
              </label>
              <TextField
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={confirmInput}
                className="w-full max-w-sm bg-bristol"
                autoFocus
              />
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
            <Button variant="outline" size="md" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="md"
              onClick={onConfirm}
              disabled={busy || !inputMatches}
              className={cn(
                destructive &&
                  "border-[2px] border-ink-black bg-hero-red text-bristol shadow-panel-red hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm",
              )}
            >
              {busy ? "Deleting…" : confirmLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
