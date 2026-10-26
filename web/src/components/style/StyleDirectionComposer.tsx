import { useId, useRef, useState } from "react";
import { Button } from "../ui/Button";
import { FieldLabel, TextAreaField } from "../ui/Field";
import { Icon } from "../ui/Icon";
import { CreditAmount } from "../ui/CreditAmount";
import { useI18n } from "../../i18n";

export type StyleDirectionMode = "single" | "neighbors";

interface StyleDirectionComposerProps {
  automaticCost?: number | null;
  customSingleCost?: number | null;
  customNeighborsCost?: number | null;
  customSingleReferenceCost?: number | null;
  customNeighborsReferenceCost?: number | null;
  imageReferenceSupported?: boolean;
  busy?: boolean;
  disabled?: boolean;
  /** Six new suggestions wait for running proofs; author directions can queue. */
  automaticDisabled?: boolean;
  onRetry?: () => void;
  error?: Error | string | null;
  onAutomatic: () => void;
  onCustom: (input: { direction: string; image: File | null; mode: StyleDirectionMode }) => void;
}

const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const AUTOMATIC_SLOTS = [["Best", true], ["Fit", false], ["Fit", false], ["Near", false], ["Contrast", false], ["Wild", false]] as const;

export function StyleDirectionComposer({
  automaticCost,
  customSingleCost,
  customNeighborsCost,
  customSingleReferenceCost,
  customNeighborsReferenceCost,
  imageReferenceSupported = true,
  busy = false,
  disabled = false,
  automaticDisabled = false,
  onRetry,
  error,
  onAutomatic,
  onCustom,
}: StyleDirectionComposerProps) {
  const { t } = useI18n();
  const fileRef = useRef<HTMLInputElement>(null);
  const idPrefix = useId();
  const [direction, setDirection] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [mode, setMode] = useState<StyleDirectionMode>("single");
  const [fileError, setFileError] = useState<string | null>(null);

  const chooseImage = (next: File | null) => {
    if (!next) return;
    if (!ACCEPTED_IMAGE_TYPES.has(next.type)) {
      setFileError(t("Use a PNG, JPG, or WebP image."));
      return;
    }
    if (next.size > MAX_IMAGE_BYTES) {
      setFileError(t("Reference images must be 10 MB or smaller."));
      return;
    }
    setFileError(null);
    setImage(next);
  };

  const imageNeedsText = image !== null && !imageReferenceSupported && direction.trim().length === 0;
  const neighborsNeedText = mode === "neighbors" && direction.trim().length === 0;
  const canSubmitCustom = (
    direction.trim().length > 0 || (image !== null && imageReferenceSupported)
  ) && !neighborsNeedText;
  const usesReferencePricing = image !== null && imageReferenceSupported;
  const customCredits = (
    mode === "single"
      ? usesReferencePricing ? customSingleReferenceCost : customSingleCost
      : usesReferencePricing ? customNeighborsReferenceCost : customNeighborsCost
  );

  const automaticBlocked = busy || disabled || automaticDisabled;
  return (
    <div className="grid gap-6 lg:grid-cols-2 lg:gap-7">
      <section aria-labelledby={`${idPrefix}-auto`} className="flex flex-col border-[2px] border-pulp-paper bg-[#24251d] p-6 text-pulp-paper shadow-[6px_6px_0_var(--color-narrator-gold)]">
        <h3 id={`${idPrefix}-auto`} className="font-display text-2xl font-black uppercase leading-none tracking-[-0.02em]">{t("Art-direct for me")}</h3>
        <p className="mt-2 font-body text-sm leading-[1.3rem] text-pulp-paper/80">{t("Six directions read from your story, from safe to surprising.")}</p>
        <ol aria-label={t("Six directions")} className="mt-5 grid grid-cols-6 gap-2">
          {AUTOMATIC_SLOTS.map(([label, gold], slot) => (
            <li key={slot} className="benday-ink relative aspect-[4/5] border border-pulp-paper/18">
              <span className={`absolute left-1.5 top-1.5 border border-ink-black px-1 font-meta text-[0.5625rem] font-bold uppercase tracking-[0.08em] text-ink-black ${gold ? "bg-narrator-gold" : "bg-pulp-paper"}`}>{t(label)}</span>
            </li>
          ))}
        </ol>
        <p className="mt-2.5 font-meta text-xs text-on-chrome-muted">{t("Three strong fits · an adjacent look · a contrast · a wildcard")}</p>
        <div className="mt-auto flex flex-wrap items-center gap-3 pt-6">
          <Button variant="onInk" size="lg" onClick={onAutomatic} disabled={automaticBlocked}>
            {busy ? t("Preparing directions…") : t("Create six directions")}
          </Button>
          {automaticCost != null && automaticCost > 0 && (
            <CreditAmount value={automaticCost} approximate label={t("credits")} className="font-meta text-xs font-semibold text-pulp-paper/75" />
          )}
        </div>
      </section>

      <section aria-labelledby={`${idPrefix}-own`} className="flex flex-col border-[2px] border-ink-black bg-bristol p-6 text-ink-black">
        <h3 id={`${idPrefix}-own`} className="font-display text-2xl font-black uppercase leading-none tracking-[-0.02em]">{t("Bring your own")}</h3>
        <p className="mt-2 font-body text-sm leading-[1.3rem] text-ink-muted">{t("Describe a look, add a reference image, or both.")}</p>
        <div className="mt-4">
          <FieldLabel htmlFor={`${idPrefix}-direction`}>{t("Describe it")}</FieldLabel>
          <TextAreaField
            id={`${idPrefix}-direction`}
            value={direction}
            onChange={(event) => setDirection(event.target.value)}
            placeholder={t("Saturated tropical colour, strong black silhouettes, clean expressive faces")}
            maxLength={2000}
            className="min-h-20"
          />
        </div>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            chooseImage(event.dataTransfer.files[0] ?? null);
          }}
          className="mt-2.5 flex w-full items-center gap-3 border border-dashed border-ink-black/40 bg-pulp-paper p-3 text-left transition-colors hover:border-ink-black focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
        >
          <span className="flex size-9 shrink-0 items-center justify-center border border-ink-black bg-bristol">
            <Icon name={image ? "check" : "plus"} size={16} />
          </span>
          <span className="min-w-0">
            <span className="block truncate font-meta text-[0.8125rem] font-semibold">{image ? image.name : t("Add a reference image")}</span>
            <span className="block font-body text-xs text-ink-soft">
              {image ? `${(image.size / 1024 / 1024).toFixed(1)} MB` : t("PNG, JPG or WebP · up to 10 MB")}
            </span>
          </span>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={(event) => chooseImage(event.target.files?.[0] ?? null)}
        />
        {fileError && <p className="mt-2 font-body text-[0.8rem] font-semibold text-hero-red">{fileError}</p>}
        {imageNeedsText && (
          <p className="mt-2 font-body text-[0.8rem] font-semibold text-hero-red">
            {t("This project's image model cannot read style references. Add a text description to continue.")}
          </p>
        )}
        {neighborsNeedText && image !== null && (
          <p className="mt-2 font-body text-[0.8rem] font-semibold text-hero-red">
            {t("Add a short text description so the art director can create meaningful neighboring directions around your reference.")}
          </p>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-2.5 pt-5">
          <div role="radiogroup" aria-label={t("How many proofs")} className="inline-flex border border-ink-black/40">
            {([["single", t("One proof")], ["neighbors", t("Plus five variations")]] as const).map(([value, label]) => (
              <label key={value} className="flex h-9 cursor-pointer items-center px-3 font-meta text-[0.8125rem] font-medium text-ink-muted transition-colors hover:bg-sidebar-tint hover:text-ink-black has-[:checked]:bg-ink-black has-[:checked]:text-pulp-paper has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-hero-red">
                <input type="radio" name={`${idPrefix}-mode`} value={value} checked={mode === value} onChange={() => setMode(value)} className="sr-only" />
                {label}
              </label>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2.5">
            {customCredits != null && customCredits > 0 && (
              <CreditAmount value={customCredits} approximate label={t("credits")} className="font-meta text-xs font-semibold text-ink-soft" />
            )}
            <Button
              variant="secondary"
              size="md"
              disabled={!canSubmitCustom || busy || disabled || !!fileError}
              onClick={() => onCustom({ direction: direction.trim(), image, mode })}
            >
              {busy ? t("Preparing proof…") : mode === "single" ? t("Create my proof") : t("Create six proofs")}
            </Button>
          </div>
        </div>
      </section>

      {(onRetry || error) && (
        <div className="lg:col-span-2">
          {error && <ErrorNotice error={error} operation="generate" />}
          {onRetry && <Button variant="outline" size="sm" className="mt-2" onClick={onRetry} disabled={busy}>{t("Try again")}</Button>}
        </div>
      )}
    </div>
  );
}
import { ErrorNotice } from "../composites/ErrorNotice";
