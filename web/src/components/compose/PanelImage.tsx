interface PanelImageProps {
  /** Full URL to the panel image (HTTP or data URL) */
  src: string;
}

/** Panel image with object-fit:cover — mirrors .panel-art CSS */
export function PanelImage({ src }: PanelImageProps) {
  return (
    <img
      className="panel-art"
      src={src}
      alt=""
      draggable={false}
    />
  );
}
