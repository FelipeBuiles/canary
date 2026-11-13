import { useState } from "react";
import { approximateWords, useAccountOffer } from "../api/cardGrant";
import { useI18n } from "../i18n";

const DISMISSED_KEY = "scenewright.freeOpeningBanner.dismissed";

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** Tells an account that has not used its free opening what it is, before the first upload. */
export function FreeOpeningBanner({ tone = "paper" }: { tone?: "paper" | "ink" }) {
  const { t } = useI18n();
  const { data } = useAccountOffer();
  const [dismissed, setDismissed] = useState(readDismissed);
  const opening = data?.free_opening;
  if (dismissed || opening?.status !== "available" || !opening.max_characters) return null;

  function dismiss() {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      // The banner simply returns next visit.
    }
  }

  const ink = tone === "ink";
  return (
    <aside aria-labelledby="free-opening-title"
      className={ink
        ? "flex flex-wrap items-start justify-between gap-3 border-[2px] border-narrator-gold px-4 py-3 text-pulp-paper"
        : "flex flex-wrap items-start justify-between gap-3 border-[2px] border-ink-black bg-narrator-gold px-4 py-3 text-ink-black shadow-paper-sm"}>
      <div className="min-w-0 max-w-[48rem]">
        <h2 id="free-opening-title" className="font-display text-lg font-black uppercase tracking-tight">
          {t("Your opening is on us")}
        </h2>
        <p className={ink ? "mt-1 font-body text-sm leading-6 text-pulp-paper/80" : "mt-1 font-body text-sm leading-6"}>
          {t("Upload your first story, up to about {words} words, and we read it free and draw your opening page in three looks. No credits needed. One per person.", {
            words: approximateWords(opening.max_characters).toLocaleString(),
          })}
        </p>
      </div>
      <button type="button" onClick={dismiss}
        className="min-h-11 shrink-0 px-2 font-meta text-xs font-bold uppercase tracking-[0.08em] underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
        {t("Dismiss")}
      </button>
    </aside>
  );
}
