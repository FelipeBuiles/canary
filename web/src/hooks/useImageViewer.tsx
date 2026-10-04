import { useCallback, useState } from "react";
import { createPortal } from "react-dom";
import { ImageViewer, type ViewerImage } from "../components/ui/ImageViewer";

export type ViewerSource = ViewerImage | ViewerImage[];

/**
 * Full-screen close inspection for any image: wheel, pinch or buttons zoom,
 * drag pans, double-click/tap toggles fit and close-up. Render `viewer`
 * wherever the hook is used; it portals to the document body.
 */
export function useImageViewer({ onIndexChange }: { onIndexChange?: (index: number) => void } = {}) {
  const [state, setState] = useState<{ images: ViewerImage[]; index: number } | null>(null);
  const open = useCallback((source: ViewerSource, index = 0) => {
    const images = Array.isArray(source) ? source : [source];
    if (images.length) setState({ images, index: Math.min(Math.max(index, 0), images.length - 1) });
  }, []);
  const viewer = state ? createPortal(
    <ImageViewer
      images={state.images}
      index={state.index}
      onIndexChange={(index) => { setState({ ...state, index }); onIndexChange?.(index); }}
      onClose={() => setState(null)}
    />,
    document.body,
  ) : null;
  return { open, viewer };
}
