import { useState } from "react";
import { Check, X } from "lucide-react";
import { useSetActiveStyle } from "../../api/queries";
import { proofImageUrl, styleName, type StyleSuggestion } from "../../api/styles";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { ErrorNotice } from "../composites/ErrorNotice";
import { InspectButton } from "../ui/InspectButton";
import { proofRole } from "./proofRole";

const SEGMENT = "h-8 px-3 font-meta text-[0.8125rem] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40";

/** Two or three proofs side by side, at the same size, under the same lamp. */
export function ProofComparison({
  projectName,
  suggestions,
  proofName,
  selectionDisabled,
  onRemove,
}: {
  projectName: string;
  suggestions: StyleSuggestion[];
  proofName: (suggestion: StyleSuggestion) => string;
  selectionDisabled: boolean;
  onRemove: (id: string) => void;
}) {
  const { t } = useI18n();
  const setActive = useSetActiveStyle();
  const [view, setView] = useState<"proof" | "action">("proof");
  const [error, setError] = useState<Error | null>(null);
  const actionAvailable = suggestions.every((suggestion) => suggestion.has_validation && !!suggestion.validation_url);
  const showingAction = view === "action" && actionAvailable;
  const images = suggestions.map((suggestion) => ({
    src: showingAction ? suggestion.validation_url! : proofImageUrl(projectName, suggestion),
    alt: proofName(suggestion),
  }));

  return (
    <section aria-label={t("Compare proofs")} className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 pb-4">
      {(actionAvailable || suggestions.some((suggestion) => suggestion.has_validation)) && (
        <div role="group" aria-label={t("Comparison images")} className="mb-4 inline-flex self-center border border-pulp-paper/22">
          <button type="button" aria-pressed={!showingAction} onClick={() => setView("proof")}
            className={cn(SEGMENT, !showingAction ? "bg-pulp-paper text-ink-black" : "text-pulp-paper/85 hover:bg-pulp-paper/8")}>{t("Story proofs")}</button>
          <button type="button" aria-pressed={showingAction} disabled={!actionAvailable} onClick={() => setView("action")}
            title={actionAvailable ? undefined : t("Each compared proof needs an action audition first.")}
            className={cn(SEGMENT, showingAction ? "bg-pulp-paper text-ink-black" : "text-pulp-paper/85 hover:bg-pulp-paper/8")}>{t("Action auditions")}</button>
        </div>
      )}
      <div className="flex min-h-[24rem] flex-1 justify-center gap-7">
        {suggestions.map((suggestion, position) => {
          const name = proofName(suggestion);
          return (
            <div key={suggestion.id} className="flex min-h-0 min-w-0 max-w-[26rem] flex-1 flex-col gap-3">
              {/* The image keeps its own ratio inside whatever height the room has. */}
              <div className="flex min-h-0 flex-1 items-start justify-center">
                <img src={images[position].src} alt={name}
                  className="block max-h-full max-w-full object-contain shadow-[0_24px_50px_-18px_rgb(0_0_0/0.75),0_0_0_1px_rgb(252_250_237/0.12)]" />
              </div>
              <div className="shrink-0">
                <h3 className="line-clamp-2 min-h-[2.2em] font-display text-base font-extrabold uppercase leading-[1.1] tracking-[-0.01em] text-pulp-paper">{styleName(suggestion)}</h3>
                <p className="mt-0.5 truncate font-meta text-xs text-on-chrome-muted">{t(proofRole(suggestion))}{suggestion.medium && ` · ${suggestion.medium}`}</p>
                <div className="mt-2.5 flex items-center gap-1.5">
                  {suggestion.is_active ? (
                    <p className="flex h-8 items-center gap-1.5 font-meta text-[0.8125rem] font-semibold text-narrator-gold"><Check size={14} aria-hidden="true" />{t("Your style")}</p>
                  ) : (
                    <button type="button" disabled={selectionDisabled || setActive.isPending || !suggestion.has_sample}
                      onClick={() => { setError(null); setActive.mutate({ project: projectName, id: suggestion.id }, { onError: setError }); }}
                      className="inline-flex h-8 items-center border border-pulp-paper/30 px-3 font-meta text-[0.8125rem] font-medium text-pulp-paper hover:bg-pulp-paper hover:text-ink-black disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold">
                      {t("Use this style")}
                    </button>
                  )}
                  <span className="ml-auto" />
                  <InspectButton images={images} index={position} tone="toolbar" />
                  <button type="button" onClick={() => onRemove(suggestion.id)} aria-label={`${t("Remove from comparison")} · ${name}`}
                    className="flex size-8 shrink-0 items-center justify-center border border-pulp-paper/22 text-pulp-paper hover:bg-pulp-paper/8 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold">
                    <X size={14} aria-hidden="true" />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {error && <ErrorNotice error={error} operation="save" />}
    </section>
  );
}
