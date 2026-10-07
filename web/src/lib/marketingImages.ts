import images from "../assets/marketing-images.json";

const manifest: Record<string, { width: number; height: number; variants: { src: string; width: number }[] }> = images;

/** Accurate aspect ratios reserve space; lazy images use their rendered width. */
export function responsiveMarketingImage(src: string, fallbackSizes: string) {
  const image = manifest[src];
  return {
    width: image.width,
    height: image.height,
    srcSet: [...image.variants, { src, width: image.width }].map(variant => `${variant.src} ${variant.width}w`).join(", "),
    sizes: `auto, ${fallbackSizes}`,
  };
}
