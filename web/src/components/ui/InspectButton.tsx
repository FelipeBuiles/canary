import { Expand } from "lucide-react";
import { useImageViewer, type ViewerSource } from "../../hooks/useImageViewer";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";

/** Corner control that opens an image (or a set, at `index`) in the viewer. */
export function InspectButton({ images, index = 0, placement = "right-3 top-3", onIndexChange, tone = "overlay" }: {
  images: ViewerSource;
  index?: number;
  /** Position utilities inside the nearest positioned ancestor. */
  placement?: string;
  onIndexChange?: (index: number) => void;
  /** "toolbar": a labelled button for the dark review stage's tool strip. */
  tone?: "overlay" | "toolbar";
}) {
  const { t } = useI18n();
  const { open, viewer } = useImageViewer({ onIndexChange });
  const image = Array.isArray(images) ? images[index] : images;
  return <>
    <button
      type="button"
      aria-label={`${t("Zoom and inspect")} · ${image?.alt ?? ""}`}
      title={t("Zoom and inspect")}
      onClick={(event) => { event.stopPropagation(); open(images, index); }}
      onPointerDown={(event) => event.stopPropagation()}
      className={tone === "toolbar"
        ? "flex h-8 items-center gap-1.5 px-2.5 font-meta text-xs font-medium text-pulp-paper/85 transition-colors hover:bg-pulp-paper/10 hover:text-pulp-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-narrator-gold"
        : cn(
          "absolute z-10 flex h-10 w-10 items-center justify-center border border-pulp-paper/40 bg-ink-black/70 text-bristol transition-colors hover:bg-ink-black focus-visible:bg-hero-red focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-hero-red",
          placement,
        )}
    >
      <Expand size={tone === "toolbar" ? 14 : 16} aria-hidden="true" />{tone === "toolbar" && t("Zoom")}
    </button>
    {viewer}
  </>;
}

/** The corner mark for surfaces whose whole area already opens the viewer. */
export function InspectBadge() {
  return (
    <span aria-hidden="true" className="pointer-events-none absolute right-3 top-3 flex h-9 w-9 items-center justify-center border-[2px] border-bristol bg-ink-black/75 text-bristol transition-colors group-hover:bg-hero-red group-focus-visible:bg-hero-red">
      <Expand size={15} />
    </span>
  );
}
