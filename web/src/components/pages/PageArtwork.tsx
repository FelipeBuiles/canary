import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ImageOff } from "lucide-react";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";

/** Reserve the reader's space before loading; never draw a border around an unsized image. */
export function PageArtwork({ src, alt, onLoaded }: { src: string; alt: string; onLoaded?: () => void }) {
  const { t } = useI18n();
  const [loadedSource, setLoadedSource] = useState<string | null>(null);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const currentSource = useRef(src);
  useLayoutEffect(() => { currentSource.current = src; }, [src]);
  const loaded = loadedSource === src;
  const failed = failedSource === src;
  useEffect(() => { if (loaded) onLoaded?.(); }, [loaded, onLoaded]);

  return <div className="relative flex h-full w-full items-center justify-center" aria-busy={!loaded && !failed}>
    {!loaded && <div className="flex aspect-[2/3] h-full max-w-full flex-col items-center justify-center gap-3 bg-surface-container px-6 text-center">
      {failed ? <>
        <ImageOff size={24} aria-hidden="true" className="text-ink-muted" />
        <p role="alert" className="font-body text-sm text-ink-muted">{t("The page image could not be loaded.")}</p>
        <Button variant="outline" size="sm" onClick={() => { setFailedSource(null); setLoadedSource(null); setAttempt((value) => value + 1); }}>{t("Try again")}</Button>
      </> : <p role="status" className="font-meta text-sm text-ink-muted">{t("Loading artwork…")}</p>}
    </div>}
    {!failed && <img key={`${src}:${attempt}`} src={src} alt={alt} loading="eager" fetchPriority="high" decoding="async"
      className={`h-full w-auto max-w-full object-contain ${loaded ? "" : "absolute invisible"}`}
      onLoad={() => { if (currentSource.current === src) setLoadedSource(src); }}
      onError={() => { if (currentSource.current === src) setFailedSource(src); }} />}
  </div>;
}
