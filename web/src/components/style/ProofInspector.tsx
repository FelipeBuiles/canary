import { useState } from "react";
import { Check, ChevronRight, Columns2, Eye, EyeOff, Info, Pencil, ScanLine } from "lucide-react";
import { useImageGenerationMeta, useSetActiveStyle, useUpdateStylePresentation } from "../../api/queries";
import { isAuthorDirection, styleName, type StyleSuggestion } from "../../api/styles";
import { proofRole } from "./proofRole";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";
import { GenerationDetailsModal } from "../ui/GenerationDetailsModal";
import { LazyImage } from "../ui/LazyImage";
import { ErrorNotice } from "../composites/ErrorNotice";

const ICON_BUTTON = "flex size-9 shrink-0 items-center justify-center text-ink-muted transition-colors hover:bg-surface-container hover:text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red disabled:opacity-40";
const LABEL = "font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-soft";

/**
 * Everything about the proof on the stage: why it fits, what to watch for,
 * and the one decision. Browsing and comparing never select a style.
 */
export function ProofInspector({
  suggestion,
  projectName,
  imageSrc,
  imageAvailable,
  isGenerating,
  generationDisabled,
  retryDisabled,
  selectionDisabled,
  isCompared,
  compareDisabled,
  onToggleCompare,
  validationBusy,
  onValidate,
  onRefresh,
  fallbackPrompt,
  fallbackParameters,
  coldOpenFavoriteId,
}: {
  suggestion: StyleSuggestion;
  projectName: string;
  imageSrc: string;
  imageAvailable: boolean;
  isGenerating: boolean;
  /** Blocks auditions, which wait for proofs already drawing. */
  generationDisabled: boolean;
  /** Blocks queueing this proof again; other proofs in flight do not. */
  retryDisabled: boolean;
  selectionDisabled: boolean;
  isCompared: boolean;
  compareDisabled: boolean;
  onToggleCompare: () => void;
  validationBusy: boolean;
  onValidate: () => void;
  onRefresh: () => void;
  fallbackPrompt: string;
  fallbackParameters: Record<string, unknown>;
  /** The look the author picked on their first pages; highlighted, never selected. */
  coldOpenFavoriteId?: string | null;
}) {
  const { t } = useI18n();
  const name = styleName(suggestion);
  const yours = isAuthorDirection(suggestion);
  const presentation = useUpdateStylePresentation();
  const setActive = useSetActiveStyle();
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(name);
  const [error, setError] = useState<Error | string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const { data: meta, isLoading: metaLoading } = useImageGenerationMeta(
    projectName, `samples/style_${suggestion.index}.png`, detailsOpen, 0,
  );
  const isActive = suggestion.is_active;
  const canSelect = suggestion.has_sample && !isActive && !isGenerating && !selectionDisabled && !setActive.isPending;

  const updatePresentation = (changes: { display_label?: string; hidden?: boolean }, onSuccess?: () => void) => {
    setError(null);
    presentation.mutate({ project: projectName, id: suggestion.id, changes }, { onSuccess, onError: (failure) => setError(failure) });
  };
  const saveName = () => {
    const next = draftName.trim();
    if (!next || next === name) { setRenaming(false); return; }
    updatePresentation({ display_label: next }, () => setRenaming(false));
  };
  const select = () => {
    if (!canSelect) return;
    setError(null);
    setActive.mutate({ project: projectName, id: suggestion.id }, { onSuccess: () => undefined, onError: (failure) => setError(failure) });
  };

  const specs = [
    ["Palette", suggestion.palette],
    ["Line & finish", suggestion.line_rendering],
    ["Watch for", suggestion.risk],
  ].filter(([, value]) => value);
  const direction = [
    ["Character design", suggestion.character_design],
    ["Lighting", suggestion.lighting_value],
    ["Sequential strengths", suggestion.sequential_art_strengths],
  ].filter(([, value]) => value);

  return (
    <aside aria-label={name} className="flex w-full min-w-0 flex-col bg-bristol text-ink-black studio-desktop:w-[22rem] studio-desktop:shrink-0 studio-desktop:border-l studio-desktop:border-ink-black/12 xl:w-[23rem]">
      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-4">
        <div className="flex items-center gap-1">
          <span className={cn(
            "mr-1 inline-flex h-[22px] shrink-0 items-center border border-ink-black px-1.5 font-meta text-[0.65625rem] font-bold uppercase tracking-[0.08em]",
            suggestion.role === "story_fit_primary" || yours || suggestion.id === coldOpenFavoriteId ? "bg-narrator-gold" : "bg-pulp-paper",
          )}>{t(proofRole(suggestion, coldOpenFavoriteId))}</span>
          <span className="min-w-0 flex-1 truncate font-meta text-xs text-ink-soft" title={suggestion.medium}>{suggestion.medium}</span>
          <button type="button" className={cn(ICON_BUTTON, isCompared && "bg-ink-black! text-narrator-gold!")}
            onClick={onToggleCompare} disabled={!isCompared && (compareDisabled || !suggestion.has_sample)} aria-pressed={isCompared}
            aria-label={`${t("Compare")} · ${name}`} title={isCompared ? t("In comparison") : compareDisabled ? t("Three proofs added. Remove one to compare another.") : t("Add to comparison")}>
            <Columns2 size={17} aria-hidden="true" />
          </button>
          {yours && !renaming && (
            <button type="button" className={ICON_BUTTON} onClick={() => { setDraftName(name); setRenaming(true); }}
              aria-label={`${t("Rename")} · ${name}`} title={t("Rename")}>
              <Pencil size={16} aria-hidden="true" />
            </button>
          )}
          {!isActive && (
            <button type="button" className={ICON_BUTTON} disabled={presentation.isPending}
              onClick={() => updatePresentation({ hidden: !suggestion.hidden })}
              aria-label={`${t(suggestion.hidden ? "Show" : "Hide")} · ${name}`} title={t(suggestion.hidden ? "Show" : "Hide")}>
              {suggestion.hidden ? <Eye size={17} aria-hidden="true" /> : <EyeOff size={17} aria-hidden="true" />}
            </button>
          )}
          <button type="button" className={ICON_BUTTON} onClick={() => setDetailsOpen(true)}
            aria-label={`${t("Generation details")} · ${name}`} title={t("Generation details")}>
            <Info size={17} aria-hidden="true" />
          </button>
        </div>

        {renaming ? (
          <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={(event) => { event.preventDefault(); saveName(); }}>
            <input
              autoFocus
              aria-label={t("Proof name")}
              value={draftName}
              maxLength={60}
              onChange={(event) => setDraftName(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setRenaming(false); } }}
              className="min-h-10 min-w-0 flex-[1_1_12rem] border border-ink-black bg-bristol px-3 font-display text-lg font-black uppercase text-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
            />
            <Button type="submit" size="sm" variant="secondary" disabled={presentation.isPending || !draftName.trim()}>{t("Save")}</Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setRenaming(false)}>{t("Cancel")}</Button>
          </form>
        ) : (
          <h2 className="mt-3 text-balance font-display text-[1.5625rem] font-black uppercase leading-[0.98] tracking-[-0.03em] [overflow-wrap:anywhere]">{name}</h2>
        )}
        {yours && suggestion.origin !== "user_image" && suggestion.template && (
          <blockquote className="mt-3 line-clamp-3 border-l-[3px] border-narrator-gold pl-3 font-body text-sm italic leading-6 text-ink-black/75" title={suggestion.template}>
            “{suggestion.template}”
          </blockquote>
        )}
        {suggestion.story_fit && <p className="mt-3 font-body text-[0.9375rem] leading-[1.45rem]">{suggestion.story_fit}</p>}

        {specs.length > 0 && (
          <dl className="mt-4 space-y-3 border-t border-ink-black/10 pt-4">
            {specs.map(([label, value]) => (
              <div key={label}>
                <dt className={LABEL}>{t(label!)}</dt>
                <dd className="mt-0.5 font-body text-[0.8125rem] leading-5 text-ink-black/80">{value}</dd>
              </div>
            ))}
          </dl>
        )}

        <details className="group mt-3">
          <summary className="inline-flex min-h-8 cursor-pointer list-none items-center gap-1.5 font-meta text-[0.8125rem] font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red [&::-webkit-details-marker]:hidden">
            <ChevronRight size={14} aria-hidden="true" className="transition-transform group-open:rotate-90" />{t("Full direction")}
          </summary>
          <div className="pb-1 pt-1">
            <p className="font-body text-[0.8125rem] leading-5 text-ink-muted">{suggestion.template}</p>
            {direction.length > 0 && (
              <dl className="mt-3 space-y-3">
                {direction.map(([label, value]) => (
                  <div key={label}>
                    <dt className={LABEL}>{t(label!)}</dt>
                    <dd className="mt-0.5 font-body text-[0.8125rem] leading-5 text-ink-muted">{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </details>

        {suggestion.sample_stale && (
          <div className="mt-4 flex items-center justify-between gap-3 border border-ink-black/10 bg-sidebar-tint px-3 py-2.5">
            <span className="font-meta text-[0.8125rem] font-medium text-ink-muted">{t("Drawn with older rendering rules")}</span>
            <Button variant="outline" size="xs" disabled={retryDisabled || isGenerating} onClick={onRefresh}>{t("Refresh proof")}</Button>
          </div>
        )}

        <section aria-label={t("Action audition")} className="mt-4 flex items-center gap-3 border border-ink-black/8 bg-sidebar-tint p-3">
          {suggestion.has_validation && suggestion.validation_url ? (
            <LazyImage src={suggestion.validation_url} alt={`${name} · ${t("Action audition")}`} width={44} height={55}
              containerClassName="h-[55px] w-11 shrink-0" className="object-cover" />
          ) : (
            <span aria-hidden="true" className="benday-ink flex h-[55px] w-11 shrink-0 items-center justify-center text-narrator-gold"><ScanLine size={18} /></span>
          )}
          <div className="min-w-0 flex-1">
            <div className="font-meta text-[0.8125rem] font-semibold">{t("See it in action")}</div>
            <div className="font-body text-xs leading-[1.05rem] text-ink-soft">
              {validationBusy ? t("Testing in action…") : suggestion.has_validation ? t("Action proof ready") : t("A second proof with a scene in motion.")}
            </div>
          </div>
          <Button variant="outline" size="sm" disabled={validationBusy || generationDisabled} onClick={onValidate} aria-busy={validationBusy}>
            {suggestion.has_validation ? t("Retest") : t("Test")}
          </Button>
        </section>

        {error && <ErrorNotice error={error} operation="save" />}
      </div>

      <div className="shrink-0 border-t border-ink-black/10 bg-pulp-paper px-5 py-4">
        {isActive ? (
          <div role="status" className="flex h-11 items-center justify-center gap-2 border-[2px] border-ink-black bg-narrator-gold font-meta text-sm font-bold">
            <Check size={16} aria-hidden="true" />{t("Your style")}
          </div>
        ) : (
          <Button fullWidth size="md" className="h-11" disabled={!canSelect} onClick={select} aria-busy={setActive.isPending}>
            {setActive.isPending ? t("Selecting…") : t("Use this style")}
          </Button>
        )}
      </div>

      <GenerationDetailsModal
        isOpen={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        title={name}
        imageUrl={imageSrc}
        metadata={meta}
        prompt={fallbackPrompt}
        parameters={fallbackParameters}
        isFallback={!meta}
        isLoading={metaLoading}
        imageAvailable={imageAvailable}
        overview={(
          <div>
            <div className="font-meta text-[0.54rem] tracking-[0.16em] text-ink-black/45">{t("VISUAL DIRECTION")}</div>
            <p className="mt-1 text-[0.8rem] leading-6 text-ink-black/75">{suggestion.template}</p>
          </div>
        )}
      />
    </aside>
  );
}
