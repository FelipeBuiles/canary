import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";
import { TextField } from "../ui/Field";
import { ShortcutHint } from "../ui/ShortcutHint";

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
  const handleClose = useCallback(() => {
    setInput("");
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        handleClose();
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
  }, [handleClose, open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center bg-ink-black/55 backdrop-blur-[2px]"
      onClick={handleClose}
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
        <form
          className="px-6 pt-5 pb-6 sm:px-8"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy && inputMatches) {
              setInput("");
              onConfirm();
            }
          }}
        >
          <div className="flex items-start justify-between gap-4">
            <h2
              id="confirm-modal-title"
              className="font-display text-[1.75rem] leading-[0.95] tracking-[-0.02em] uppercase"
            >
              {title}
            </h2>
            <button
              type="button"
              onClick={handleClose}
              aria-label="Cancel"
              className="inline-flex min-h-11 shrink-0 items-center gap-2 border-[2px] border-ink-black/20 px-3 font-meta text-[0.62rem] tracking-[0.12em] uppercase text-ink-black/60 hover:border-ink-black hover:text-ink-black"
            >
              Close <ShortcutHint>Esc</ShortcutHint>
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
            <Button type="button" variant="outline" size="md" onClick={handleClose} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="md"
              type="submit"
              disabled={busy || !inputMatches}
              className={cn(
                destructive &&
                  "border-[2px] border-ink-black bg-hero-red text-bristol shadow-panel-red hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-paper-sm",
              )}
            >
              {busy ? "Deleting…" : confirmLabel}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
