import { useEffect, useEffectEvent, useRef } from "react";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { LazyImage } from "./LazyImage";
import { useI18n } from "../../i18n";

interface ImageModalProps {
  isOpen: boolean;
  onClose: () => void;
  src: string;
  alt: string;
  /** Optional heading shown in the modal title bar above the image. */
  title?: string;
  actions?: ReactNode;
  /** When provided, renders a sidebar panel alongside the image. */
  sidebar?: ReactNode;
  imageAvailable?: boolean;
  emptyLabel?: string;
}

export function ImageModal({ isOpen, onClose, src, alt, title, actions, sidebar, imageAvailable = true, emptyLabel = "No image generated" }: ImageModalProps) {
  const { t } = useI18n();
  const closeModal = useEffectEvent(onClose);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";

    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !document.querySelector('[role="alertdialog"]')) {
        closeModal();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (!focusable.length) return;
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
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = prev;
      opener?.focus();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title ?? alt}
    >
      <div
        ref={dialogRef}
        className={`flex max-h-[calc(100dvh-2rem)] w-full flex-col overflow-hidden border-[2px] border-ink-black bg-bristol shadow-ink sm:max-h-[94vh] ${sidebar ? "max-w-[1300px]" : "max-w-[1100px]"}`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Title bar */}
        <div className="flex items-center justify-between border-b-[2px] border-ink-black px-4 py-3 shrink-0">
          <div>
            {title && (
              <div className="font-display text-[1.25rem] font-bold uppercase leading-none tracking-[-0.04em] text-ink-black">
                {title}
              </div>
            )}
            <div className="mt-0.5 font-meta text-[0.48rem] tracking-[0.18em] text-ink-black/45">
              {title ? alt : ""}
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="flex h-11 w-11 items-center justify-center border-[2px] border-ink-black/20 text-ink-black/60 transition-colors hover:border-ink-black hover:text-ink-black"
          >
            <Icon name="x" size={14} />
          </button>
        </div>

        {/* Body: image + optional sidebar */}
        <div
          data-testid="image-modal-body"
          className={`min-h-0 flex-1 overflow-hidden ${sidebar ? "flex flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]" : "flex flex-col"}`}
        >
          <div
            data-testid="image-modal-image-pane"
            className="flex h-[36dvh] min-h-0 shrink-0 items-center justify-center overflow-hidden bg-ink-black lg:h-auto lg:min-h-[60vh] lg:shrink"
          >
            {imageAvailable ? (
              <LazyImage
                src={src}
                alt={alt}
                containerClassName="w-full h-full"
                preserveAspectBox
              />
            ) : (
              <p className="px-6 text-center font-meta text-[0.68rem] tracking-[0.14em] text-bristol/60">
                {emptyLabel}
              </p>
            )}
          </div>
          {sidebar && (
            <div className="min-h-0 flex-1 overflow-y-auto border-t-[2px] border-ink-black bg-bristol p-5 lg:max-h-none lg:border-l-[2px] lg:border-t-0">
              {sidebar}
            </div>
          )}
        </div>

        {/* Actions */}
        {actions && (
          <div className="flex items-center justify-end gap-2 border-t-[2px] border-ink-black px-4 py-3 shrink-0">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
