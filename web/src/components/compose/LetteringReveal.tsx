import type { LetteringStyle } from "../../types/api";

/**
 * One-time "it thought of everything" beat shown on first entry to the Book
 * after compose: surfaces the lettering label + rationale the AI generated
 * (otherwise invisible). Dismissible; the caller persists the seen flag.
 */
export function LetteringReveal({
  lettering,
  onDismiss,
}: {
  lettering: LetteringStyle;
  onDismiss: () => void;
}) {
  return (
    <div className="relative border-[2px] border-ink-black bg-narrator-gold px-4 py-3 shadow-ink-sm">
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center font-meta text-[0.7rem] text-ink-black/55 transition-colors hover:text-ink-black"
      >
        ✕
      </button>
      <div className="font-meta text-[0.5rem] tracking-[0.2em] text-ink-black/60">
        ✦ YOUR PAGES ARE LETTERED TO MATCH
      </div>
      <div className="mt-1 font-display text-[1.3rem] font-black uppercase leading-[0.9] tracking-[-0.03em] text-ink-black [font-stretch:75%]">
        {lettering.label || "Matched lettering"}
      </div>
      {lettering.rationale && (
        <p className="mt-1.5 max-w-prose pr-6 font-body text-[0.9rem] leading-relaxed text-ink-black/75">
          {lettering.rationale}
        </p>
      )}
    </div>
  );
}
