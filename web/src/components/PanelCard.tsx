import type { ImageStatus } from "../types/api";
import { LazyImage } from "./ui/LazyImage";
import { getPanelDisplayState, type PanelDisplayState } from "../lib/panelState";

const STATE_BADGE: Record<PanelDisplayState, { label: string; className: string }> = {
  accepted: { label: "ACCEPTED", className: "bg-archive-sage text-bristol" },
  generated: { label: "GENERATED", className: "bg-archive-sage/70 text-ink-black" },
  regenerated: { label: "REGENERATED", className: "bg-teal-600 text-bristol" },
  generating: { label: "GENERATING…", className: "bg-narrator-gold text-ink-black animate-pulse" },
  pending: { label: "PENDING", className: "bg-narrator-gold/60 text-ink-black" },
  failed: { label: "FAILED", className: "bg-hero-red text-bristol" },
  stale: { label: "STALE", className: "bg-ink-black/30 text-bristol" },
};

interface PanelCardProps {
  sceneId: string;
  panelNumber: number;
  status: ImageStatus["status"];
  imageUrl: string;
  imageAvailable?: boolean;
  failureClassification?: string | null;
  errorMessage?: string;
  accepted?: boolean;
  regenMode?: "queued" | "running" | null;
  regenError?: string | null;
  isDrawRunning?: boolean;
  isRetryFailedRunning?: boolean;
  title?: string;
  description?: string;
  onPanelClick?: () => void;
}

export function PanelCard({
  sceneId,
  panelNumber,
  status,
  imageUrl,
  imageAvailable = true,
  failureClassification,
  errorMessage,
  accepted = false,
  regenMode = null,
  regenError,
  isDrawRunning = false,
  isRetryFailedRunning = false,
  title,
  description,
  onPanelClick,
}: PanelCardProps) {
  const displayState = getPanelDisplayState(
    { status, accepted, version_count: undefined },
    regenMode,
    isDrawRunning,
    isRetryFailedRunning,
  );
  const badge = STATE_BADGE[displayState];
  const panelNum = String(panelNumber).padStart(2, "0");
  const sceneLabel = sceneId.replace(/_/g, " ").toUpperCase();
  const cardTitle = title ?? `${sceneLabel} · PANEL ${panelNum}`;
  const imageDownloadUrl = imageUrl;

  const isInteractive = displayState !== "pending" && displayState !== "generating";

  const failedCopyBody =
    regenError ||
    errorMessage ||
    (failureClassification === "provider_blocked"
      ? "Edit the prompt and re-run before composing."
      : "Open the panel detail to edit the prompt, then use Quick Re-Do.");

  return (
    <article className="group/panel flex min-w-0 flex-col">
      <div
        className={`relative aspect-[4/5] overflow-hidden border-[2px] border-transparent bg-surface-container transition-colors duration-150 ${isInteractive ? "cursor-pointer group-hover/panel:border-ink-black" : ""}`}
        onClick={isInteractive ? onPanelClick : undefined}
      >
        {displayState === "generating" ? (
          <div className="flex h-full flex-col items-center justify-center bg-ink-black/80">
            <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
              {regenMode === "queued" ? "QUEUED" : "GENERATING…"}
            </div>
            <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
              {regenMode === "queued" ? "WAITING FOR GENERATOR" : "GENERATING PANEL"}
            </div>
          </div>
        ) : displayState === "pending" ? (
          <div className="flex h-full flex-col items-center justify-center bg-ink-black/10">
            <div className="font-meta text-[0.62rem] tracking-[0.22em] text-ink-black/35">
              NOT YET GENERATED
            </div>
          </div>
        ) : displayState === "stale" ? (
          <div className="flex h-full flex-col items-center justify-center bg-hero-red/10 px-3">
            <div className="font-display text-[1.25rem] font-bold leading-none tracking-[-0.05em] text-hero-red">
              GENERATION STALE
            </div>
            <div className="mt-2 text-center text-[0.72rem] text-hero-red/80">
              Job tracking was interrupted. Re-run this panel.
            </div>
          </div>
        ) : displayState === "failed" ? (
          <div className="relative h-full bg-hero-red/10">
            {imageAvailable && (
              <LazyImage
                src={imageUrl}
                alt={`Panel ${panelNum}`}
                loading="lazy"
                width={400}
                height={500}
                containerClassName="absolute inset-0 h-full w-full"
                className="h-full w-full object-cover opacity-55 grayscale"
              />
            )}
            <div className="absolute inset-0 bg-hero-red/15" />
            <div className="relative z-10 flex h-full flex-col items-center justify-center px-3">
              <div className="flex h-12 w-12 items-center justify-center border-[2px] border-hero-red bg-bristol/80 text-[1.25rem] font-bold text-hero-red">
                △
              </div>
              <div className="mt-3 text-center font-display text-[1.1rem] font-bold leading-none tracking-[-0.05em] text-hero-red">
                {failureClassification === "provider_blocked" ? "PROVIDER BLOCKED" : "GENERATION FAILED"}
              </div>
              <div className="mt-2 max-w-[22ch] text-center text-[0.68rem] leading-5 text-hero-red/85">
                {failedCopyBody}
              </div>
            </div>
          </div>
        ) : (
          <>
            <LazyImage
              src={imageUrl}
              alt={`Panel ${panelNum}`}
              loading="lazy"
              width={400}
              height={500}
              containerClassName="h-full w-full"
              className="h-full w-full object-cover transition-transform duration-300 group-hover/panel:scale-[1.02]"
            />
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 bg-ink-black/62 opacity-0 transition-opacity duration-150 group-hover/panel:opacity-100">
              {onPanelClick && (
                <button
                  type="button"
                  className="pointer-events-auto border border-bristol bg-bristol px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-ink-black transition-colors hover:bg-pulp-paper"
                  onClick={(e) => { e.stopPropagation(); onPanelClick(); }}
                >
                  Preview
                </button>
              )}
              {imageAvailable && (
                <a
                  href={imageDownloadUrl}
                  download={`panel-${panelNum}.png`}
                  className="pointer-events-auto border border-bristol/45 bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol transition-colors hover:border-bristol hover:bg-bristol/10"
                  onClick={(e) => e.stopPropagation()}
                >
                  Download
                </a>
              )}
            </div>
          </>
        )}

        <div className="absolute left-2 top-2 flex h-6 min-w-6 items-center justify-center bg-ink-black/80 px-1.5 font-meta text-[0.56rem] font-bold tracking-[0.1em] text-bristol">
          {panelNum}
        </div>
      </div>

      <div className="border-[2px] border-t-0 border-ink-black/10 bg-bristol p-3">
        <div className="mb-1 font-meta text-[0.48rem] tracking-[0.18em] text-ink-black/40">
          SHOT {panelNum} · {sceneLabel}
        </div>
        <div className="truncate font-body text-[0.82rem] font-semibold leading-5 text-ink-black">
          {cardTitle}
        </div>
        {description && (
          <div className="mt-0.5 truncate text-[0.72rem] leading-5 text-ink-black/55">
            {description}
          </div>
        )}
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className={`inline-flex h-5 items-center px-2 font-meta text-[0.52rem] tracking-[0.1em] ${badge.className}`}>
            {badge.label}
          </span>
          {onPanelClick && isInteractive && (
            <button
              type="button"
              className="font-meta text-[0.58rem] tracking-[0.1em] text-ink-black/40 transition-colors hover:text-ink-black"
              onClick={onPanelClick}
            >
              VIEW →
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
