import { useEffect, useState, type ReactNode } from "react";
import { useI18n } from "../../i18n";
import { Stamp } from "../ui/motion";

const STORAGE_PREFIX = "canary.wholeBookShown.";

function seen(key: string): boolean {
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + key) === "1";
  } catch {
    return true; // Without storage, never risk replaying on every visit.
  }
}

function markSeen(key: string) {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + key, "1");
  } catch {
    // Per-viewer convenience only.
  }
}

/**
 * Once per edition, when every page is drawn, the gallery pulls back into a
 * tilted wall of the whole book and settles. `editionKey` changes when the
 * plan changes, which is what makes a new edition worth another look.
 */
export function WholeBookReveal({
  ready,
  editionKey,
  className,
  children,
}: {
  ready: boolean;
  editionKey: string;
  className?: string;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!ready || seen(editionKey)) return;
    const timer = window.setTimeout(() => setPlaying(true), 0);
    return () => window.clearTimeout(timer);
  }, [ready, editionKey]);

  return (
    <div className="relative">
      {playing && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-8 z-10 flex justify-center">
          <Stamp play rotate={-4} className="text-base shadow-ink-sm">{t("The whole book")}</Stamp>
        </div>
      )}
      <div
        data-testid="whole-book-gallery"
        className={`${className ?? ""} ${playing ? "animate-whole-book" : ""}`}
        onAnimationEnd={(event) => {
          if (event.target !== event.currentTarget) return;
          markSeen(editionKey);
          setPlaying(false);
        }}
      >
        {children}
      </div>
    </div>
  );
}
