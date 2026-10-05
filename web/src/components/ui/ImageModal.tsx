import { useRef } from "react";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { useBackdropDismiss } from "../../hooks/useBackdropDismiss";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { LazyImage } from "./LazyImage";
import { InspectBadge } from "./InspectButton";
import { useImageViewer } from "../../hooks/useImageViewer";
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const inspector = useImageViewer();

  useDialogFocus(dialogRef, { enabled: isOpen, onClose, initialFocusRef: closeButtonRef });
  const backdrop = useBackdropDismiss(onClose);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4"
      {...backdrop}
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
            <div className="mt-0.5 font-meta text-xs tracking-[0.08em] text-ink-muted">
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
              <button
                type="button"
                onClick={() => inspector.open({ src, alt, label: title })}
                aria-label={`${t("Zoom and inspect")} · ${alt}`}
                title={t("Zoom and inspect")}
                className="group relative h-full w-full cursor-zoom-in focus-visible:outline-[3px] focus-visible:-outline-offset-[3px] focus-visible:outline-narrator-gold"
              >
                <LazyImage
                  src={src}
                  alt={alt}
                  containerClassName="w-full h-full"
                  preserveAspectBox
                />
                <InspectBadge />
              </button>
            ) : (
              <p className="px-6 text-center font-meta text-xs tracking-[0.08em] text-bristol/80">
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
      {inspector.viewer}
    </div>
  );
}
