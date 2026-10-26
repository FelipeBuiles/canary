import { ChevronLeft, ChevronRight } from "lucide-react";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import type { ScrollStrip } from "./useScrollStrip";

const FADE = {
  ink: { before: "from-ink-black via-ink-black/85", after: "from-ink-black via-ink-black/85" },
  paper: { before: "from-bristol via-bristol/85", after: "from-bristol via-bristol/85" },
};

/**
 * The fades and arrows for a strip. Place it beside the scrolling element
 * inside a `relative` wrapper. The arrows stay out of the tab order: every
 * item in the strip is focusable and scrolls itself into view.
 */
export function ScrollStripControls({ strip, tone = "ink" }: { strip: ScrollStrip; tone?: "ink" | "paper" }) {
  const { t } = useI18n();
  const button = cn(
    "pointer-events-auto flex size-9 items-center justify-center border transition-colors",
    tone === "ink"
      ? "border-pulp-paper/30 bg-ink-black text-pulp-paper hover:border-pulp-paper hover:bg-pulp-paper hover:text-ink-black"
      : "border-ink-black/25 bg-bristol text-ink-black hover:border-ink-black hover:bg-ink-black hover:text-pulp-paper",
  );
  return (
    <>
      {strip.before && (
        <div data-strip-edge="before" className={cn("pointer-events-none absolute inset-y-0 left-0 z-10 flex w-16 items-center bg-gradient-to-r to-transparent pl-2", FADE[tone].before)}>
          <button type="button" tabIndex={-1} aria-label={t("Scroll left")} title={t("Scroll left")} onClick={() => strip.page(-1)} className={button}>
            <ChevronLeft size={18} aria-hidden="true" />
          </button>
        </div>
      )}
      {strip.after && (
        <div data-strip-edge="after" className={cn("pointer-events-none absolute inset-y-0 right-0 z-10 flex w-16 items-center justify-end bg-gradient-to-l to-transparent pr-2", FADE[tone].after)}>
          <button type="button" tabIndex={-1} aria-label={t("Scroll right")} title={t("Scroll right")} onClick={() => strip.page(1)} className={button}>
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        </div>
      )}
    </>
  );
}
