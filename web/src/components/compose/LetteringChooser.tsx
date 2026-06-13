import type { LetteringStyle } from "../../types/api";
import { cn } from "../../lib/cn";
import { FlowingDotsPlaceholder } from "../ui/FlowingDotsPlaceholder";
import { LetteringPreview } from "./LetteringPreview";

const PRESETS: { id: string; label: string }[] = [
  { id: "auto", label: "✦ MATCH MY STYLE" },
  { id: "default", label: "DEFAULT" },
  { id: "noir", label: "NOIR" },
  { id: "manga", label: "MANGA" },
  { id: "vintage", label: "VINTAGE" },
  { id: "painted", label: "PAINTED" },
];

interface LetteringChooserProps {
  lettering: LetteringStyle | undefined;
  isGenerating: boolean;
  disabled?: boolean;
  onMatchMyStyle: () => void;
  onReroll: () => void;
  onSelectPreset: (preset: string) => void;
}

/**
 * The Look-station "Page & lettering" decision: a live preview + the AI's
 * rationale, with "Match my style" (auto) as the default and the named presets
 * beside it. This is the integrated home for the choice that used to hide in a
 * dropdown at the bottom of the grid.
 */
export function LetteringChooser({
  lettering,
  isGenerating,
  disabled,
  onMatchMyStyle,
  onReroll,
  onSelectPreset,
}: LetteringChooserProps) {
  const activeId = lettering?.mode === "preset" ? lettering.preset ?? "default" : "auto";

  return (
    <section className="mt-8 border-t-[2px] border-ink-black/10 pt-5">
      <div className="font-meta text-[0.56rem] tracking-[0.2em] text-ink-black/45">PAGE &amp; LETTERING</div>
      <p className="mt-1 max-w-prose font-body text-[0.86rem] leading-relaxed text-ink-black/60">
        How captions, speech, thought bubbles, SFX, panel borders and paper are styled across the book.
      </p>

      <div className="mt-4 grid gap-5 md:grid-cols-[260px_minmax(0,1fr)]">
        <div className="border-[2px] border-ink-black bg-bristol p-1.5 shadow-ink-sm">
          {isGenerating ? (
            <FlowingDotsPlaceholder aspect="3 / 2" className="h-full w-full" label="TUNING LETTERING…" />
          ) : (
            <LetteringPreview lettering={lettering} />
          )}
        </div>

        <div className="min-w-0">
          <div className="font-display text-[1.2rem] font-bold leading-tight tracking-[-0.03em] text-ink-black">
            {isGenerating ? "Tuning lettering…" : lettering?.label || "Matched lettering"}
          </div>
          <p className="mt-1.5 max-w-prose font-body text-[0.92rem] leading-relaxed text-ink-black/68">
            {isGenerating
              ? "Reading your style and choosing colors, borders, and a typeface to match."
              : lettering?.rationale || "Lettering tuned to your selected style."}
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => (p.id === "auto" ? onMatchMyStyle() : onSelectPreset(p.id))}
                disabled={disabled || isGenerating}
                className={cn(
                  "border-[2px] border-ink-black px-3 py-1.5 font-meta text-[0.52rem] tracking-[0.14em] transition-colors disabled:opacity-50",
                  activeId === p.id ? "bg-ink-black text-bristol" : "bg-bristol hover:bg-surface-container",
                )}
              >
                {p.label}
              </button>
            ))}
            {activeId === "auto" && !isGenerating && (
              <button
                type="button"
                onClick={onReroll}
                disabled={disabled}
                className="border-[2px] border-ink-black/30 px-3 py-1.5 font-meta text-[0.52rem] tracking-[0.14em] text-ink-black/60 transition-colors hover:border-ink-black hover:text-ink-black disabled:opacity-50"
              >
                ↺ ANOTHER TAKE
              </button>
            )}
          </div>

          {activeId === "auto" && (
            <p className="mt-2 font-meta text-[0.48rem] tracking-[0.12em] text-ink-black/35">
              ✦ RECOMMENDED — PULP CHOSE THIS TO MATCH YOUR ART
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
