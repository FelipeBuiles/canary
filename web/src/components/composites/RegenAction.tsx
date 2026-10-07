import { type ReactNode, useId, useState } from "react";
import type { CostEstimate } from "../../types/api";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { CreditAmount } from "../ui/CreditAmount";
import { ConfirmDrawer } from "./ConfirmDrawer";
import { ErrorNotice } from "./ErrorNotice";

interface RegenActionProps {
  assetLabel: string;
  instructionControls?: ReactNode;
  instructionPlaceholder?: string;
  instructionSummary?: ReactNode;
  cost?: CostEstimate;
  instructionCost?: CostEstimate;
  hasImage?: boolean;
  allowInstruction?: boolean;
  busy?: boolean;
  busyLabel?: string;
  disabled?: boolean;
  error?: Error | string | null;
  lastInstruction?: string | null;
  instruction?: string;
  onInstructionChange?: (instruction: string) => void;
  onRegenerate: () => void;
  onRegenerateWithInstruction?: (instruction: string) => void;
}

type ConfirmMode = "same" | "instruction" | null;

/**
 * Canonical single-image regeneration control. It keeps author intent first,
 * confirms every paid generation, and uses the same language and state model
 * for style proofs, cast assets, and panels.
 */
export function RegenAction({
  assetLabel,
  instructionControls,
  instructionPlaceholder,
  instructionSummary,
  cost,
  instructionCost,
  hasImage = true,
  allowInstruction = true,
  busy = false,
  busyLabel,
  disabled = false,
  error,
  lastInstruction,
  instruction: controlledInstruction,
  onInstructionChange,
  onRegenerate,
  onRegenerateWithInstruction,
}: RegenActionProps) {
  const { t } = useI18n();
  const [localInstruction, setLocalInstruction] = useState("");
  const instruction = controlledInstruction ?? localInstruction;
  const setInstruction = onInstructionChange ?? setLocalInstruction;
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [confirmMode, setConfirmMode] = useState<ConfirmMode>(null);
  const instructionId = useId();
  const instructionErrorId = useId();
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
    } else if (confirmMode === "same") {
      onRegenerate();
    }
    setConfirmMode(null);
  };

  return (
    <section aria-label={`${t("REGENERATE IMAGE")} · ${assetLabel}`}>
      <div className="font-meta text-xs tracking-[0.08em] text-ink-muted">
        {hasImage ? t("MAKE A CHANGE") : t("CREATE IMAGE")}
      </div>
      <p className="mt-1 text-[0.78rem] leading-5 text-ink-black/60">
        {hasImage
          ? t("Describe a visual change, or try another version from the same brief.")
          : t("Generate this missing image from its saved visual brief.")}
      </p>

      {lastInstruction && (
        <details className="mt-3 border-[2px] border-archive-sage/35 bg-archive-sage/8">
          <summary className="min-h-11 cursor-pointer px-3 py-3 font-meta text-xs tracking-[0.08em] text-ready">
            {t("LAST CHANGE APPLIED")}
          </summary>
          <p className="break-words px-3 pb-3 text-[0.75rem] leading-5 text-ink-black/70">
            {lastInstruction}
          </p>
        </details>
      )}

      {allowInstruction && onRegenerateWithInstruction && (
        <div className="mt-3">
          <label htmlFor={instructionId} className="mb-1.5 block font-meta text-xs tracking-[0.08em] text-ink-muted">
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
            placeholder={instructionPlaceholder ?? t("For example: darker lighting, rain on the window, keep the face unchanged…")}
          />
          <div className="mt-1 flex items-start justify-between gap-3">
            <p
              id={instructionErrorId}
              className={`min-h-5 text-xs leading-5 ${instructionError ? "text-hero-red" : "text-ink-muted"}`}
              aria-live="polite"
            >
              {instructionError ?? `${instruction.length}/500`}
            </p>
          </div>
          {instructionControls}
          <Button
            className="mt-1 w-full"
            size="sm"
            onClick={requestInstructionRegen}
            disabled={instructionUnavailable || !instruction.trim()}
          >
            {busy ? (busyLabel ?? t("STARTING…")) : (
              <>
                {t("REGENERATE WITH CHANGE")} <span aria-hidden="true">·</span>{" "}
                {instructionCost
                  ? <CreditAmount value={instructionCost.estimate_credits} approximate label={t("credits")} />
                  : t("COST CALCULATING…")}
              </>
            )}
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
        {busy ? (busyLabel ?? t("STARTING…")) : (
          <>
            {hasImage ? t("TRY ANOTHER VERSION") : t("GENERATE IMAGE")} <span aria-hidden="true">·</span>{" "}
            {cost
              ? <CreditAmount value={cost.estimate_credits} approximate label={t("credits")} />
              : t("COST CALCULATING…")}
          </>
        )}
      </Button>

      {error && <ErrorNotice error={error} operation="generate" />}

      <ConfirmDrawer
        open={confirmMode !== null}
        title={confirmMode === "instruction" ? t("Regenerate with change") : hasImage ? t("Try another version") : t("Generate image")}
        body={confirmMode === "instruction"
          ? t("Scenewright will apply your visual change and create a new image. The current version stays in history.")
          : hasImage
            ? t("Scenewright will create a new image from the same saved brief. The current version stays in history.")
            : t("Scenewright will create this image from its saved visual brief.")}
        extraBody={confirmMode === "instruction" ? (
          <div>{instructionSummary}<blockquote className="break-words border-[2px] border-ink-black/10 bg-bristol px-3 py-2 text-[0.8rem] leading-5 text-ink-black/75">
            “{instruction.trim()}”
          </blockquote></div>
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
