import { LazyImage } from "../ui/LazyImage";

interface PanelImageProps {
  /** Full URL to the panel image (HTTP or data URL) */
  src: string;
  imageOffsetX: number | null;
  imageOffsetY: number | null;
}

/** Panel image with object-fit:cover — mirrors .panel-art CSS */
export function PanelImage({ src, imageOffsetX, imageOffsetY }: PanelImageProps) {
  const style = {
    ...(imageOffsetX != null ? { ["--panel-art-offset-x" as const]: `${Math.round(imageOffsetX)}px` } : {}),
    ...(imageOffsetY != null ? { ["--panel-art-offset-y" as const]: `${Math.round(imageOffsetY)}px` } : {}),
  } as React.CSSProperties;

  return (
    <LazyImage
      containerClassName="panel-art-frame"
      className="panel-art"
      src={src}
      alt=""
      style={Object.keys(style).length ? style : undefined}
      draggable={false}
    />
  );
}
