import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { pagePreviewUrl } from "../../api/pages";

export interface PagePreviewHandle {
  refresh: () => void;
  getIframeDoc: () => Document | null;
  scaleFactor: number;
}

interface PagePreviewProps {
  project: string;
  pageNum: number;
  onLoad?: () => void;
}

export const PagePreview = forwardRef<PagePreviewHandle, PagePreviewProps>(
  function PagePreview({ project, pageNum, onLoad }, ref) {
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [scale, setScale] = useState(1);
    const [bustKey, setBustKey] = useState(0);

    const src = `${pagePreviewUrl(project, pageNum)}${bustKey ? `?t=${bustKey}` : ""}`;

    const computeScale = useCallback(() => {
      if (!containerRef.current) return;
      const containerWidth = containerRef.current.clientWidth;
      setScale(containerWidth / 2480);
    }, []);

    useEffect(() => {
      computeScale();
      const ro = new ResizeObserver(computeScale);
      if (containerRef.current) ro.observe(containerRef.current);
      return () => ro.disconnect();
    }, [computeScale]);

    useImperativeHandle(ref, () => ({
      refresh: () => setBustKey(Date.now()),
      getIframeDoc: () => {
        try {
          return iframeRef.current?.contentDocument ?? null;
        } catch {
          return null;
        }
      },
      scaleFactor: scale,
    }), [scale]);

    function handleLoad() {
      computeScale();
      onLoad?.();
    }

    return (
      <div
        ref={containerRef}
        className="relative w-full border-[2px] border-ink-black bg-ink-black/5"
        style={{ aspectRatio: "2480 / 3508" }}
      >
        <iframe
          ref={iframeRef}
          src={src}
          title={`Page ${pageNum} preview`}
          onLoad={handleLoad}
          style={{
            width: 2480,
            height: 3508,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
            border: "none",
          }}
        />
      </div>
    );
  },
);
