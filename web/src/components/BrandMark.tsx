type BrandMarkVariant = "primary" | "reversed" | "micro";

const BRAND_MARK_SOURCES: Record<BrandMarkVariant, string> = {
  primary: "/brand/scenewright-panel-frame/scenewright-symbol-primary.svg",
  reversed: "/brand/scenewright-panel-frame/scenewright-symbol-reversed.svg",
  micro: "/brand/scenewright-panel-frame/scenewright-symbol-micro.svg",
};

export function BrandMark({
  className,
  title,
  variant = "micro",
}: {
  className?: string;
  title?: string;
  variant?: BrandMarkVariant;
}) {
  return (
    <img
      className={className}
      src={BRAND_MARK_SOURCES[variant]}
      alt={title ?? ""}
      aria-hidden={title ? undefined : true}
      draggable={false}
    />
  );
}
