import { useEffect } from "react";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { LazyImage } from "./LazyImage";

interface ImageModalProps {
  isOpen: boolean;
  onClose: () => void;
  src: string;
  alt: string;
  actions?: ReactNode;
}

export function ImageModal({ isOpen, onClose, src, alt, actions }: ImageModalProps) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="relative max-h-full max-w-full">
        <button 
          onClick={onClose}
          className="absolute -right-10 -top-10 p-2 text-bristol hover:text-hero-red transition-colors"
        >
          <Icon name="x" size={24} />
        </button>
        <LazyImage
          src={src} 
          alt={alt} 
          containerClassName="max-h-[90vh] max-w-[90vw] border-[4px] border-ink-black bg-bristol"
          className="max-h-[90vh] max-w-[90vw] object-contain"
          onClick={(e) => e.stopPropagation()}
        />
        {actions && (
          <div
            className="mt-3 flex justify-end gap-2"
            onClick={(e) => e.stopPropagation()}
          >
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
