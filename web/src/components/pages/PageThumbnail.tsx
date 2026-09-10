import { useState } from "react";
import { ImageOff } from "lucide-react";
import { useI18n } from "../../i18n";

/** A failed preview never hides the page's saved-render review action. */
export function PageThumbnail({ src, alt, reveal, onRevealEnd }: {
  src: string;
  alt: string;
  reveal: boolean;
  onRevealEnd: () => void;
}) {
  const { t } = useI18n();
  const [failedSource, setFailedSource] = useState<string | null>(null);
  return failedSource === src ? (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center text-ink-muted">
      <ImageOff size={24} aria-hidden="true" />
      <p className="font-meta text-xs font-bold">{t("Preview unavailable")}</p>
      <p className="font-body text-xs leading-6">{t("Open the page to inspect its saved artwork.")}</p>
    </div>
  ) : <img src={src} alt={alt} loading="lazy" decoding="async"
    className={`h-full w-full object-contain ${reveal ? "animate-proof-reveal" : ""}`}
    onError={() => setFailedSource(src)} onAnimationEnd={onRevealEnd} />;
}
