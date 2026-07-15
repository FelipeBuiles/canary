import { useI18n } from "../i18n";

type RegenerationPhase = "preparing" | "queued" | "running";

interface PanelRegenerationOverlayProps {
  phase: RegenerationPhase;
  compact?: boolean;
}

const PHASE_COPY: Record<RegenerationPhase, { label: string; detail: string }> = {
  preparing: {
    label: "PREPARING YOUR CHANGE…",
    detail: "Updating the image brief",
  },
  queued: {
    label: "REGENERATION QUEUED",
    detail: "The current version stays visible",
  },
  running: {
    label: "REDRAWING PANEL…",
    detail: "The current version stays visible",
  },
};

/** A legible, image-local status for the full instructed regeneration cycle. */
export function PanelRegenerationOverlay({
  phase,
  compact = false,
}: PanelRegenerationOverlayProps) {
  const { t } = useI18n();
  const copy = PHASE_COPY[phase];

  return (
    <div
      className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-ink-black/70 px-4 text-center"
      role="status"
      aria-live="polite"
      aria-label={t(copy.label)}
    >
      <div
        className={`animate-register-stamp border-[3px] border-ink-black bg-narrator-gold font-display font-black uppercase leading-none text-ink-black shadow-paper-sm ${
          compact
            ? "px-3 py-2 text-[0.8rem] tracking-[-0.02em]"
            : "px-6 py-3 text-[1.15rem] tracking-[-0.03em]"
        }`}
      >
        {t(copy.label)}
      </div>
      {!compact && (
        <p className="mt-3 font-meta text-[0.62rem] font-bold uppercase tracking-[0.12em] text-bristol">
          {t(copy.detail)}
        </p>
      )}
      <div className={`${compact ? "mt-3 w-28" : "mt-4 w-44"} h-2 overflow-hidden border-[2px] border-bristol/70 bg-ink-black`} aria-hidden>
        <span className="panel-regen-progress block h-full w-1/2 bg-narrator-gold" />
      </div>
    </div>
  );
}
