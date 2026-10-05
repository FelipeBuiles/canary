import { useRef, type MouseEvent, type PointerEvent } from "react";

/** A backdrop click must start and end outside the panel, including text-selection drags. */
export function useBackdropDismiss(onClose: () => void) {
  const gesture = useRef<{ pointerId: number; released: boolean } | null>(null);

  return {
    onPointerDownCapture(event: PointerEvent<HTMLElement>) {
      gesture.current = event.button === 0 && event.target === event.currentTarget
        ? { pointerId: event.pointerId, released: false }
        : null;
    },
    onPointerUpCapture(event: PointerEvent<HTMLElement>) {
      if (gesture.current?.pointerId === event.pointerId && event.target === event.currentTarget) {
        gesture.current.released = true;
      } else {
        gesture.current = null;
      }
    },
    onPointerCancelCapture() {
      gesture.current = null;
    },
    onClick(event: MouseEvent<HTMLElement>) {
      const dismiss = gesture.current?.released && event.target === event.currentTarget;
      gesture.current = null;
      if (dismiss) onClose();
    },
  };
}
