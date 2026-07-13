import { useId, useState } from "react";
import type { CostEstimate } from "../../types/api";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { ConfirmDrawer } from "./ConfirmDrawer";

interface RegenActionProps {
  assetLabel: string;
  cost?: CostEstimate;
  instructionCost?: CostEstimate;
  hasImage?: boolean;
  allowInstruction?: boolean;
  busy?: boolean;
  busyLabel?: string;
  disabled?: boolean;
  error?: string | null;
  lastInstruction?: string | null;
  onRegenerate: () => void;
  onRegenerateWithInstruction?: (instruction: string) => void;
}

type ConfirmMode = "same" | "instruction" | null;

function creditsLabel(cost: CostEstimate | undefined, fallback: string) {
  if (!cost) return fallback;
  return `~${cost.estimate_credits.toLocaleString()} credits`;
}

/**
 * Canonical single-image regeneration control. It keeps author intent first,
 * confirms every paid generation, and uses the same language and state model
 * for style proofs, cast assets, and panels.
 */
export function RegenAction({
  assetLabel,
  cost,
  instructionCost,
  hasImage = true,
  allowInstruction = true,
  busy = false,
  busyLabel,
  disabled = false,
  error,
  lastInstruction,
  onRegenerate,
  onRegenerateWithInstruction,
}: RegenActionProps) {
  const { t } = useI18n();
  const [instruction, setInstruction] = useState("");
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [confirmMode, setConfirmMode] = useState<ConfirmMode>(null);
  const instructionId = useId();
  const instructionErrorId = useId();
  const costLabel = creditsLabel(cost, t("COST CALCULATING…"));
  const instructionCostLabel = creditsLabel(instructionCost, t("COST CALCULATING…"));
  const unavailable = disabled || busy || !cost;
  const instructionUnavailable = disabled || busy || !instructionCost;

  const requestInstructionRegen = () => {
    const trimmed = instruction.trim();
    if (!trimmed) {
      setInstructionError(t("Describe the visual change you want first."));
      return;
    }
    setInstructionError(null);
    setConfirmMode("instruction");
  };

  const confirm = () => {
    if (confirmMode === "instruction") {
      const trimmed = instruction.trim();
      if (!trimmed || !onRegenerateWithInstruction) return;
      onRegenerateWithInstruction(trimmed);
      setInstruction("");
    } else if (confirmMode === "same") {
      onRegenerate();
    }
    setConfirmMode(null);
  };

  return (
    <section aria-label={`${t("REGENERATE IMAGE")} · ${assetLabel}`}>
      <div className="font-meta text-[0.54rem] tracking-[0.16em] text-ink-black/45">
        {hasImage ? t("MAKE A CHANGE") : t("CREATE IMAGE")}
      </div>
      <p className="mt-1 text-[0.78rem] leading-5 text-ink-black/60">
        {hasImage
          ? t("Describe a visual change, or try another version from the same brief.")
          : t("Generate this missing image from its saved visual brief.")}
      </p>

      {lastInstruction && (
        <details className="mt-3 border-[2px] border-archive-sage/35 bg-archive-sage/8">
          <summary className="cursor-pointer px-3 py-2 font-meta text-[0.54rem] tracking-[0.12em] text-archive-sage">
            {t("LAST CHANGE APPLIED")}
          </summary>
          <p className="break-words px-3 pb-3 text-[0.75rem] leading-5 text-ink-black/70">
            {lastInstruction}
          </p>
        </details>
      )}

      {allowInstruction && onRegenerateWithInstruction && (
        <div className="mt-3">
          <label htmlFor={instructionId} className="mb-1.5 block font-meta text-[0.54rem] tracking-[0.14em] text-ink-black/50">
            {t("WHAT SHOULD CHANGE?")}
          </label>
          <textarea
            id={instructionId}
            value={instruction}
            onChange={(event) => {
              setInstruction(event.target.value);
              if (instructionError) setInstructionError(null);
            }}
            maxLength={500}
            rows={3}
            disabled={disabled || busy}
            aria-invalid={!!instructionError}
            aria-describedby={instructionError ? instructionErrorId : undefined}
            className="w-full resize-y border-[2px] border-ink-black/25 bg-bristol px-3 py-2.5 font-body text-[0.86rem] leading-6 text-ink-black outline-none transition-colors focus:border-ink-black disabled:opacity-55"
            placeholder={t("For example: darker lighting, rain on the window, keep the face unchanged…")}
          />
          <div className="mt-1 flex items-start justify-between gap-3">
            <p
              id={instructionErrorId}
              className={`min-h-5 text-[0.72rem] leading-5 ${instructionError ? "text-hero-red" : "text-ink-black/40"}`}
              aria-live="polite"
            >
              {instructionError ?? `${instruction.length}/500`}
            </p>
          </div>
          <Button
            className="mt-1 w-full"
            size="sm"
            onClick={requestInstructionRegen}
            disabled={instructionUnavailable || !instruction.trim()}
          >
            {busy ? (busyLabel ?? t("STARTING…")) : `${t("REGENERATE WITH CHANGE")} · ${instructionCostLabel}`}
          </Button>
        </div>
      )}

      <Button
        variant="outline"
        className={`${allowInstruction ? "mt-2" : "mt-3"} w-full`}
        size="sm"
        onClick={() => setConfirmMode("same")}
        disabled={unavailable}
      >
        {busy
          ? (busyLabel ?? t("STARTING…"))
          : `${hasImage ? t("TRY ANOTHER VERSION") : t("GENERATE IMAGE")} · ${costLabel}`}
      </Button>

      {error && (
        <div
          role="alert"
          className="mt-3 border-[2px] border-hero-red bg-hero-red/8 p-3 text-[0.76rem] leading-5 text-ink-black"
        >
          <strong className="block font-meta text-[0.54rem] tracking-[0.14em] text-hero-red">
            {t("REGENERATION FAILED")}
          </strong>
          <span className="mt-1 block break-words">{error}</span>
        </div>
      )}

      <ConfirmDrawer
        open={confirmMode !== null}
        title={confirmMode === "instruction" ? t("Regenerate with change") : hasImage ? t("Try another version") : t("Generate image")}
        body={confirmMode === "instruction"
          ? t("Scenewright will apply your visual change and create a new image. The current version stays in history.")
          : hasImage
            ? t("Scenewright will create a new image from the same saved brief. The current version stays in history.")
            : t("Scenewright will create this image from its saved visual brief.")}
        extraBody={confirmMode === "instruction" ? (
          <blockquote className="break-words border-[2px] border-ink-black/10 bg-bristol px-3 py-2 text-[0.8rem] leading-5 text-ink-black/75">
            “{instruction.trim()}”
          </blockquote>
        ) : undefined}
        cost={confirmMode === "instruction" ? instructionCost : cost}
        confirmLabel={confirmMode === "instruction" ? t("REGENERATE WITH CHANGE") : hasImage ? t("TRY ANOTHER VERSION") : t("GENERATE IMAGE")}
        onConfirm={confirm}
        onClose={() => setConfirmMode(null)}
        busy={busy}
      />
    </section>
  );
}
