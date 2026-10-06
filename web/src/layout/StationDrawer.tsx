import { useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { useBackdropDismiss } from "../hooks/useBackdropDismiss";
import { useI18n } from "../i18n";

/**
 * The compact shell's station navigator: the desktop pressroom sidebar,
 * slid in from the left edge as a modal drawer. Callers pass the same body
 * the desktop sidebar renders, so both navigators stay one design.
 */
export function StationDrawer({ open, label, onClose, children }: {
  open: boolean;
  label: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement | null>(null);
  useDialogFocus(panelRef, { enabled: open, onClose });
  const backdrop = useBackdropDismiss(onClose);
  if (!open) return null;
  return createPortal(
    <div role="presentation" className="animate-drawer-scrim fixed inset-0 z-[120] bg-ink-black/60" {...backdrop}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onClick={(event) => event.stopPropagation()}
        className="pressroom-sidebar animate-drawer-in relative flex h-full w-[min(20rem,calc(100vw-3.5rem))] flex-col bg-ink-black text-bristol shadow-[6px_0_0_0_var(--color-hero-red)]"
      >
        {children}
        <button
          type="button"
          onClick={onClose}
          aria-label={t("Close navigation")}
          className="absolute -right-[3.25rem] top-2 flex h-11 w-11 items-center justify-center border-[2px] border-ink-black bg-bristol text-ink-black shadow-paper-sm transition-[box-shadow,transform] duration-150 active:translate-x-[3px] active:translate-y-[3px] active:shadow-none"
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>
    </div>,
    document.body,
  );
}
