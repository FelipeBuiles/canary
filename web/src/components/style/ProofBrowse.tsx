import { Check, EyeOff, Plus, TriangleAlert } from "lucide-react";
import { proofImageUrl, styleName, type StyleSuggestion } from "../../api/styles";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { proofRole } from "./proofRole";
import { ScrollStripControls } from "../ui/ScrollStrip";
import { useScrollStrip } from "../ui/useScrollStrip";

function ProofThumbArt({ projectName, suggestion, busy }: { projectName: string; suggestion: StyleSuggestion; busy: boolean }) {
  if (suggestion.has_sample) {
    return <img src={proofImageUrl(projectName, suggestion)} alt="" loading="lazy" className="block h-full w-full object-cover" />;
  }
  return (
    <span className={cn("benday-ink flex h-full w-full items-center justify-center text-narrator-gold", busy && "animate-pulse")}>
      {suggestion.generation_status === "failed" && !busy && <TriangleAlert size={16} aria-hidden="true" />}
    </span>
  );
}

/** Every proof in a row under the stage; the current one is lit. */
export function ProofFilmstrip({
  projectName,
  suggestions,
  currentId,
  compareIds,
  isBusy,
  onPick,
  onNew,
  newDisabled,
  moreProofs = false,
}: {
  projectName: string;
  suggestions: StyleSuggestion[];
  currentId: string | null;
  compareIds: string[];
  isBusy: (suggestion: StyleSuggestion) => boolean;
  onPick: (id: string) => void;
  onNew: () => void;
  newDisabled: boolean;
  /** Only the author's first pages are here: name the tile for what it adds. */
  moreProofs?: boolean;
}) {
  const { t } = useI18n();
  const { attach: stripRef, ...strip } = useScrollStrip<HTMLUListElement>();
  return (
    <div className="relative shrink-0 border-t border-pulp-paper/8 bg-[#141510]/60">
      <ScrollStripControls strip={strip} />
      {/* Centred with auto margins, not justify-center, so an overflowing strip still starts at its first proof. */}
      <ul ref={stripRef} aria-label={t("All proofs")} className="flex items-center gap-3.5 overflow-x-auto px-5 pb-4 pt-3.5 [scrollbar-width:none] sm:[&>li:first-child]:ml-auto sm:[&>li:last-child]:mr-auto">
        {suggestions.map((suggestion) => {
          const name = styleName(suggestion);
          const current = suggestion.id === currentId;
          const compared = compareIds.indexOf(suggestion.id);
          return (
            <li key={suggestion.id} className="shrink-0">
              <button
                type="button"
                onClick={() => onPick(suggestion.id)}
                aria-current={current ? "true" : undefined}
                aria-label={`${name}${suggestion.is_active ? ` · ${t("Your style")}` : ""}`}
                title={name}
                className="group relative block w-[3.75rem] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold"
              >
                <span className={cn(
                  "block h-[4.6875rem] w-[3.75rem] outline transition-opacity duration-150",
                  current ? "opacity-100 outline-2 outline-offset-[3px] outline-narrator-gold"
                    : cn("outline-1 outline-pulp-paper/14 group-hover:opacity-100", suggestion.hidden ? "opacity-30" : "opacity-55"),
                )}>
                  <ProofThumbArt projectName={projectName} suggestion={suggestion} busy={isBusy(suggestion)} />
                </span>
                {suggestion.is_active && (
                  <span aria-hidden="true" className="absolute -right-1.5 -top-1.5 flex size-[1.125rem] items-center justify-center border border-ink-black bg-narrator-gold text-ink-black">
                    <Check size={11} strokeWidth={3} />
                  </span>
                )}
                {compared >= 0 && (
                  <span aria-hidden="true" className="absolute bottom-1 left-1 flex size-4 items-center justify-center border border-narrator-gold bg-ink-black font-meta text-[0.625rem] font-bold text-narrator-gold">
                    {compared + 1}
                  </span>
                )}
                {suggestion.hidden && (
                  <span aria-hidden="true" className="absolute bottom-1 right-1 flex size-4 items-center justify-center bg-ink-black text-on-chrome-muted">
                    <EyeOff size={10} />
                  </span>
                )}
              </button>
            </li>
          );
        })}
        <li className="shrink-0">
          <button type="button" onClick={onNew} disabled={newDisabled}
            className="flex h-[4.6875rem] w-[3.75rem] flex-col items-center justify-center gap-1 border border-dashed border-pulp-paper/35 text-center font-meta text-[0.625rem] font-semibold leading-tight text-pulp-paper/85 transition-colors hover:border-narrator-gold hover:text-narrator-gold disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold">
            <Plus size={16} aria-hidden="true" />{moreProofs ? t("More proofs") : t("New direction")}
          </button>
        </li>
      </ul>
    </div>
  );
}

/** All proofs at once, art first; opening one puts it on the table. */
export function ProofSheet({
  projectName,
  suggestions,
  isBusy,
  onOpen,
}: {
  projectName: string;
  suggestions: StyleSuggestion[];
  isBusy: (suggestion: StyleSuggestion) => boolean;
  onOpen: (id: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-2">
      <ul data-testid="style-proof-grid" aria-label={t("Proof sheet")}
        className="mx-auto grid max-w-[60rem] grid-cols-2 gap-x-7 gap-y-6 sm:grid-cols-3 xl:grid-cols-4">
        {suggestions.map((suggestion) => {
          const name = styleName(suggestion);
          return (
            <li key={suggestion.id}>
              <button type="button" onClick={() => onOpen(suggestion.id)} aria-label={`${t("Open")} ${name}`}
                className="group block w-full text-left text-pulp-paper focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold">
                <span className="block aspect-[4/5] w-full shadow-[0_18px_40px_-16px_rgb(0_0_0/0.7),0_0_0_1px_rgb(252_250_237/0.12)] transition-[transform,box-shadow] duration-150 group-hover:-translate-x-0.5 group-hover:-translate-y-0.5 group-hover:shadow-[4px_4px_0_var(--color-narrator-gold),0_0_0_1px_var(--color-ink-black)]">
                  <ProofThumbArt projectName={projectName} suggestion={suggestion} busy={isBusy(suggestion)} />
                </span>
              </button>
              <h3 className="mt-2 font-display text-sm font-extrabold uppercase leading-[1.1] tracking-[-0.01em] text-pulp-paper">{name}</h3>
              <p className="mt-0.5 font-meta text-xs text-on-chrome-muted">
                {suggestion.is_active && <span className="font-semibold text-narrator-gold">{t("Your style")} · </span>}
                {t(proofRole(suggestion))}
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
