import { useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { useBackdropDismiss } from "../../hooks/useBackdropDismiss";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { ShortcutHint } from "../ui/ShortcutHint";

export interface SheetProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Actions pinned under the content. */
  footer?: ReactNode;
  wide?: boolean;
}

/** A modal panel for editing work that needs more room than a confirmation. */
export function Sheet({ open, title, description, onClose, children, footer, wide = false }: SheetProps) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  useDialogFocus(panelRef, { enabled: open, onClose });
  const backdrop = useBackdropDismiss(onClose);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-end justify-center bg-ink-black/70 sm:items-center sm:p-6" {...backdrop} role="presentation">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "flex max-h-[calc(100dvh-1rem)] w-full flex-col border-[2px] border-ink-black bg-pulp-paper text-ink-black shadow-paper",
          wide ? "max-w-[960px]" : "max-w-[720px]",
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b-[2px] border-ink-black/10 px-5 pb-4 pt-5 sm:px-8">
          <div className="min-w-0">
            <h2 id={titleId} className="font-display text-[1.6rem] uppercase leading-[0.95] tracking-[-0.02em]">{title}</h2>
            {description && <div className="mt-2 font-body text-sm leading-6 text-ink-muted">{description}</div>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-11 shrink-0 items-center gap-2 border-[2px] border-ink-black/20 px-3 font-meta text-xs uppercase tracking-[0.08em] text-ink-muted hover:border-ink-black hover:text-ink-black"
          >
            {t("Close")} <ShortcutHint>Esc</ShortcutHint>
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-8">{children}</div>
        {footer && <div className="flex flex-wrap items-center justify-end gap-3 border-t-[2px] border-ink-black/10 px-5 py-4 sm:px-8">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
