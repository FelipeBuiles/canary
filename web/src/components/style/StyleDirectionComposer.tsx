import { useRef, useState } from "react";
import { Button } from "../ui/Button";
import { FieldLabel, TextAreaField } from "../ui/Field";
import { Icon } from "../ui/Icon";
import { CreditAmount } from "../ui/CreditAmount";
import { Surface } from "../ui/Surface";
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
  onRetry?: () => void;
  error?: string | null;
  onAutomatic: () => void;
  onCustom: (input: { direction: string; image: File | null; mode: StyleDirectionMode }) => void;
}

const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

export function StyleDirectionComposer({
  automaticCost,
  customSingleCost,
  customNeighborsCost,
  customSingleReferenceCost,
  customNeighborsReferenceCost,
  imageReferenceSupported = true,
  busy = false,
  disabled = false,
  onRetry,
  error,
  onAutomatic,
  onCustom,
}: StyleDirectionComposerProps) {
  const { t } = useI18n();
  const fileRef = useRef<HTMLInputElement>(null);
  const [lane, setLane] = useState<"automatic" | "custom">("automatic");
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

  return (
    <Surface padding="lg" className="relative overflow-hidden">
      <div className="max-w-[70ch]">
        <div className="font-meta text-[0.68rem] font-bold tracking-[0.12em] text-ink-black/65">
          {t("YOUR ART DIRECTOR")}
        </div>
        <h2 className="mt-2 font-display text-[2rem] font-black uppercase leading-none tracking-[-0.035em] text-ink-black">
          {t("How should we find the look?")}
        </h2>
        <p className="mt-3 font-body text-[0.95rem] leading-6 text-ink-black/70">
          {t("Let Scenewright explore the story, or bring a direction you already have. Nothing is generated until you choose.")}
        </p>
      </div>

      <div className="mt-7 grid gap-3 md:grid-cols-2" role="radiogroup" aria-label={t("Style starting point")}>
        <button
          type="button"
          role="radio"
          aria-checked={lane === "automatic"}
          onClick={() => setLane("automatic")}
          className={`min-h-28 border-[2px] p-4 text-left transition-colors focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-4 focus-visible:outline-hero-red ${
            lane === "automatic"
              ? "border-ink-black bg-narrator-gold shadow-ink-sm"
              : "border-ink-black/15 bg-bristol hover:border-ink-black/40"
          }`}
        >
          <span className="font-display text-[1.15rem] font-black uppercase tracking-[-0.025em] text-ink-black">
            {t("Art-direct for me")}
          </span>
          <span className="mt-2 block text-[0.83rem] leading-5 text-ink-black/70">
            {t("Five story-aware directions: two strong fits, an adjacent option, a contrast, and one wildcard.")}
          </span>
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={lane === "custom"}
          onClick={() => setLane("custom")}
          className={`min-h-28 border-[2px] p-4 text-left transition-colors focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-4 focus-visible:outline-hero-red ${
            lane === "custom"
              ? "border-ink-black bg-narrator-gold shadow-ink-sm"
              : "border-ink-black/15 bg-bristol hover:border-ink-black/40"
          }`}
        >
          <span className="font-display text-[1.15rem] font-black uppercase tracking-[-0.025em] text-ink-black">
            {t("Bring a direction")}
          </span>
          <span className="mt-2 block text-[0.83rem] leading-5 text-ink-black/70">
            {t("Describe the look, upload a visual reference, or use both. Generate one faithful proof or explore nearby options.")}
          </span>
        </button>
      </div>

      {lane === "automatic" ? (
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button size="lg" onClick={onAutomatic} disabled={busy || disabled}>
            {busy ? t("PREPARING DIRECTIONS…") : t("CREATE FIVE DIRECTIONS")}
          </Button>
          {automaticCost != null && automaticCost > 0 && (
            <CreditAmount
              value={automaticCost}
              approximate
              label={t("credits")}
              className="text-[0.78rem] font-semibold text-ink-black/65"
            />
          )}
        </div>
      ) : (
        <div className="mt-6 space-y-5">
          <div>
            <FieldLabel htmlFor="style-direction">{t("DESCRIBE THE DIRECTION")}</FieldLabel>
            <TextAreaField
              id="style-direction"
              value={direction}
              onChange={(event) => setDirection(event.target.value)}
              placeholder={t("For example: saturated tropical colors, strong black silhouettes, clean expressive faces, and readable action at small panel sizes.")}
              maxLength={2000}
              className="min-h-28"
            />
          </div>

          <div>
            <FieldLabel>{t("VISUAL REFERENCE (OPTIONAL)")}</FieldLabel>
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                chooseImage(event.dataTransfer.files[0] ?? null);
              }}
              className="flex min-h-24 w-full items-center gap-4 border-[2px] border-dashed border-ink-black/35 bg-pulp-paper px-4 py-4 text-left transition-colors hover:border-ink-black focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-4 focus-visible:outline-hero-red"
            >
              <span className="flex h-11 w-11 shrink-0 items-center justify-center border-[2px] border-ink-black bg-bristol">
                <Icon name={image ? "check" : "plus"} size={18} />
              </span>
              <span>
                <span className="block text-[0.86rem] font-bold text-ink-black">
                  {image ? image.name : t("Drop an image or choose a file")}
                </span>
                <span className="mt-1 block text-[0.74rem] text-ink-black/60">
                  {image ? `${(image.size / 1024 / 1024).toFixed(1)} MB` : t("PNG, JPG, or WebP · up to 10 MB")}
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
            {fileError && <p className="mt-2 text-[0.8rem] font-semibold text-hero-red">{fileError}</p>}
            {imageNeedsText && (
              <p className="mt-2 text-[0.8rem] font-semibold text-hero-red">
                {t("This project's image model cannot read style references. Add a text description to continue.")}
              </p>
            )}
          </div>

          <fieldset>
            <legend className="font-meta text-[0.68rem] font-bold tracking-[0.1em] text-ink-black/65">
              {t("WHAT SHOULD WE GENERATE?")}
            </legend>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <label className="flex min-h-11 flex-1 cursor-pointer items-center gap-3 border-[2px] border-ink-black/15 bg-bristol px-3 py-2 has-[:checked]:border-ink-black has-[:checked]:bg-narrator-gold/45">
                <input
                  type="radio"
                  name="style-direction-mode"
                  value="single"
                  checked={mode === "single"}
                  onChange={() => setMode("single")}
                />
                <span className="text-[0.82rem] font-semibold">{t("One faithful proof")}</span>
              </label>
              <label className="flex min-h-11 flex-1 cursor-pointer items-center gap-3 border-[2px] border-ink-black/15 bg-bristol px-3 py-2 has-[:checked]:border-ink-black has-[:checked]:bg-narrator-gold/45">
                <input
                  type="radio"
                  name="style-direction-mode"
                  value="neighbors"
                  checked={mode === "neighbors"}
                  onChange={() => setMode("neighbors")}
                />
                <span className="text-[0.82rem] font-semibold">{t("This direction + four neighbors")}</span>
              </label>
            </div>
            {neighborsNeedText && image !== null && (
              <p className="mt-2 text-[0.8rem] font-semibold text-hero-red">
                {t("Add a short text description so the art director can create meaningful neighboring directions around your reference.")}
              </p>
            )}
          </fieldset>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              size="lg"
              disabled={!canSubmitCustom || busy || disabled || !!fileError}
              onClick={() => onCustom({ direction: direction.trim(), image, mode })}
            >
              {busy ? t("PREPARING PROOF…") : mode === "single" ? t("CREATE MY PROOF") : t("CREATE FIVE DIRECTIONS")}
            </Button>
            {customCredits != null && customCredits > 0 && (
              <CreditAmount
                value={customCredits}
                approximate
                label={t("credits")}
                className="text-[0.78rem] font-semibold text-ink-black/65"
              />
            )}
          </div>
        </div>
      )}

      {onRetry && <Button size="sm" onClick={onRetry} disabled={busy}>{t("TRY AGAIN")}</Button>}

      {error && (
        <p role="alert" className="mt-5 border-[2px] border-hero-red bg-chip-red/30 px-3 py-2 text-[0.82rem] font-semibold text-hero-red">
          {error}
        </p>
      )}
    </Surface>
  );
}
