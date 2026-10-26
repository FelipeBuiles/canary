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
  /** A main image's looks: the confirmation offers to redraw them from the new image too. */
  looks?: { count: number; estimate_credits: number } | null;
  onRegenerate: (withLooks: boolean) => void;
  onRegenerateWithInstruction?: (instruction: string, withLooks: boolean) => void;
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
  looks,
  onRegenerate,
  onRegenerateWithInstruction,
}: RegenActionProps) {
  const { t } = useI18n();
  const [localInstruction, setLocalInstruction] = useState("");
  const instruction = controlledInstruction ?? localInstruction;
  const setInstruction = onInstructionChange ?? setLocalInstruction;
  const [instructionError, setInstructionError] = useState<string | null>(null);
  const [confirmMode, setConfirmMode] = useState<ConfirmMode>(null);
  // On by default: looks drawn from the old image would otherwise turn outdated.
  const [includeLooks, setIncludeLooks] = useState(true);
  const withLooks = !!looks && includeLooks;
  const looksId = useId();
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
      onRegenerateWithInstruction(trimmed, withLooks);
    } else if (confirmMode === "same") {
      onRegenerate(withLooks);
    }
    setConfirmMode(null);
  };

  const withLooksCost = (estimate?: CostEstimate) => estimate && looks && withLooks
    ? { ...estimate, estimate_credits: estimate.estimate_credits + looks.estimate_credits }
    : estimate;
  const looksChoice = looks && hasImage ? (
    <div className="flex items-start gap-3 border border-ink-black/15 bg-bristol px-3 py-2">
      <input id={looksId} type="checkbox" checked={includeLooks} onChange={(event) => setIncludeLooks(event.target.checked)}
        className="mt-1 h-5 w-5 shrink-0 accent-ink-black" />
      <label htmlFor={looksId} className="font-body text-[0.8rem] leading-5 text-ink-black">
        {t("{count, plural, one {Also redraw its look from the new image} other {Also redraw its # looks from the new image}}", { count: looks.count })}
        {" · "}<CreditAmount value={looks.estimate_credits} approximate label={t("credits")} />
        <span className="block text-ink-muted">{t("Looks drawn from the current image would otherwise be out of date.")}</span>
      </label>
    </div>
  ) : null;

  return (
    <section aria-label={`${t("REGENERATE IMAGE")} · ${assetLabel}`}>
      {lastInstruction && (
        <details className="mb-3 border border-archive-sage/35 bg-archive-sage/8">
          <summary className="min-h-10 cursor-pointer px-3 py-2.5 font-meta text-xs font-medium text-ready">
            {t("Last change applied")}
          </summary>
          <p className="break-words px-3 pb-3 text-[0.8125rem] leading-5 text-ink-black/75">
            {lastInstruction}
          </p>
        </details>
      )}

      {allowInstruction && onRegenerateWithInstruction ? (
        <div>
          <label htmlFor={instructionId} className="block font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">
            {t("Make a change")}
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
            className="mt-2 block w-full resize-y border border-ink-black/45 bg-bristol px-3 py-2.5 font-body text-sm leading-5 text-ink-black outline-none transition-colors placeholder:text-ink-soft focus:border-ink-black disabled:opacity-55"
            placeholder={instructionPlaceholder ?? t("For example: darker lighting, rain on the window, keep the face unchanged…")}
          />
          <p
            id={instructionErrorId}
            className={`mt-1 min-h-4 text-right font-meta text-[0.6875rem] tabular-nums ${instructionError ? "text-left text-hero-red" : "text-ink-soft"}`}
            aria-live="polite"
          >
            {instructionError ?? (instruction.length > 0 ? `${instruction.length}/500` : "")}
          </p>
          {instructionControls}
          <Button
            variant="secondary"
            className="mt-1 w-full"
            size="md"
            onClick={requestInstructionRegen}
            disabled={instructionUnavailable || !instruction.trim()}
          >
            {busy ? (busyLabel ?? t("Starting…")) : (
              <>
                {t("Redraw with change")} <span aria-hidden="true" className="opacity-60">·</span>{" "}
                {instructionCost
                  ? <CreditAmount value={instructionCost.estimate_credits} approximate label={t("credits")} />
                  : t("cost calculating…")}
              </>
            )}
          </Button>
        </div>
      ) : (
        <p className="font-body text-sm leading-5 text-ink-muted">
          {hasImage
            ? t("Try another version from the same brief.")
            : t("Draw this missing image from its saved visual brief.")}
        </p>
      )}

      <Button
        variant={hasImage ? "outline" : "secondary"}
        className="mt-2 w-full"
        size="md"
        onClick={() => setConfirmMode("same")}
        disabled={unavailable}
      >
        {busy ? (busyLabel ?? t("Starting…")) : (
          <>
            {hasImage ? t("Try another version") : t("Draw this image")} <span aria-hidden="true" className="opacity-60">·</span>{" "}
            {cost
              ? <CreditAmount value={cost.estimate_credits} approximate label={t("credits")} />
              : t("cost calculating…")}
          </>
        )}
      </Button>
      {hasImage && <p className="mt-2 font-body text-xs text-ink-muted">{t("The current image stays in Versions.")}</p>}

      {error && <ErrorNotice error={error} operation="generate" />}

      <ConfirmDrawer
        open={confirmMode !== null}
        title={confirmMode === "instruction" ? t("Redraw with change") : hasImage ? t("Try another version") : t("Draw this image")}
        body={confirmMode === "instruction"
          ? t("Scenewright will apply your visual change and create a new image. The current version stays in history.")
          : hasImage
            ? t("Scenewright will create a new image from the same saved brief. The current version stays in history.")
            : t("Scenewright will create this image from its saved visual brief.")}
        extraBody={confirmMode === "instruction" || looksChoice ? (
          <div className="space-y-3">
            {confirmMode === "instruction" && <div>{instructionSummary}<blockquote className="break-words border border-ink-black/15 bg-bristol px-3 py-2 text-[0.8rem] leading-5 text-ink-black/75">
              “{instruction.trim()}”
            </blockquote></div>}
            {looksChoice}
          </div>
        ) : undefined}
        cost={withLooksCost(confirmMode === "instruction" ? instructionCost : cost)}
        confirmLabel={confirmMode === "instruction" ? t("Redraw with change") : hasImage ? t("Try another version") : t("Draw this image")}
        onConfirm={confirm}
        onClose={() => setConfirmMode(null)}
        busy={busy}
      />
    </section>
  );
}
