import type { ImageStatus } from "../types/api";
import { FlowingDotsPlaceholder } from "./ui/FlowingDotsPlaceholder";
import { LazyImage } from "./ui/LazyImage";
import { EntityCard } from "./composites";
import { getPanelDisplayState, type PanelDisplayState } from "../lib/panelState";

// Review-by-exception: only non-default states get a badge. A plain
// generated panel is the default good state and carries no status chrome.
const STATE_BADGE: Partial<Record<PanelDisplayState, { label: string; className: string }>> = {
  generating: { label: "DRAWING…", className: "bg-narrator-gold text-ink-black animate-pulse" },
  queued: { label: "QUEUED", className: "bg-narrator-gold/30 text-ink-black" },
  pending: { label: "PENDING", className: "bg-ink-black/15 text-ink-black/80" },
  failed: { label: "FAILED", className: "bg-hero-red text-bristol" },
};

interface PanelCardProps {
  sceneId: string;
  panelNumber: number;
  status: ImageStatus["status"];
  imageUrl: string;
  imageAvailable?: boolean;
  failureClassification?: string | null;
  errorMessage?: string;
  flagged?: boolean;
  onToggleFlag?: () => void;
  versionCount?: number;
  regenMode?: "queued" | "running" | null;
  regenError?: string | null;
  /** True when the backend reports this exact panel is currently mid-generation. */
  inFlight?: boolean;
  /** True when this panel is part of an active run's target set but not yet started. */
  queuedInRun?: boolean;
  isRetryFailedRunning?: boolean;
  /** Epoch ms when this panel last finished — triggers a 600ms flash when it changes. */
  finishFlashAt?: number | null;
  /** Status of the most recent finish — drives the flash color. */
  finishFlashStatus?: "ok" | "failed" | null;
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
  flagged = false,
  onToggleFlag,
  versionCount,
  regenMode = null,
  regenError,
  inFlight = false,
  queuedInRun = false,
  isRetryFailedRunning = false,
  finishFlashAt = null,
  finishFlashStatus = null,
  title,
  description,
  onPanelClick,
}: PanelCardProps) {
  const displayState = getPanelDisplayState(
    { status, flagged, version_count: versionCount },
    { inFlight, queuedInRun, regenMode, isRetryFailedRunning },
  );
  const badge = STATE_BADGE[displayState];
  const isFlagged = displayState === "flagged";
  const panelNum = String(panelNumber).padStart(2, "0");
  const sceneLabel = sceneId.replace(/_/g, " ").toUpperCase();
  const cardTitle = title ?? `${sceneLabel} · PANEL ${panelNum}`;
  const imageDownloadUrl = imageUrl;

  const isInteractive = displayState !== "pending"
    && displayState !== "queued"
    && displayState !== "generating";
  const canFlag = !!onToggleFlag
    && (displayState === "generated" || displayState === "regenerated" || displayState === "flagged");

  const failedCopyBody =
    regenError ||
    errorMessage ||
    (failureClassification === "provider_blocked"
      ? "Edit the prompt and re-run before composing."
      : "Open the panel to describe a fix, or re-roll with the same prompt.");

  const media = (
    <div
      className={`group/panel-media relative shrink-0 aspect-[4/5] bg-surface-container ${
        displayState === "queued" ? "outline outline-2 outline-dashed outline-narrator-gold/70 -outline-offset-2" : ""
      } ${isInteractive ? "cursor-pointer" : ""}`}
      onClick={isInteractive ? onPanelClick : undefined}
    >
      <style>{`
        @keyframes panel-finish-flash {
          0%   { box-shadow: 0 0 0 0 var(--flash-color); opacity: 1; }
          100% { box-shadow: 0 0 0 8px transparent;       opacity: 0; }
        }
      `}</style>
      {finishFlashAt != null && (
        <span
          key={finishFlashAt}
          aria-hidden
          className="pointer-events-none absolute inset-0 z-20"
          style={{
            ["--flash-color" as string]: finishFlashStatus === "failed"
              ? "rgba(220, 47, 39, 0.55)"
              : "rgba(141, 162, 105, 0.55)",
            animation: "panel-finish-flash 600ms ease-out forwards",
            boxShadow: "inset 0 0 0 4px var(--flash-color)",
          }}
        />
      )}
      {displayState === "generating" ? (
        <FlowingDotsPlaceholder
          aspect="4 / 5"
          className="h-full"
          aria-label="Panel generation in progress"
        />
      ) : displayState === "queued" ? (
        <div className="flex h-full flex-col items-center justify-center bg-ink-black/8">
          <div className="font-display text-[1.1rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold">
            QUEUED
          </div>
          <div className="mt-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">
            IN THIS RUN
          </div>
        </div>
      ) : displayState === "pending" ? (
        <div className="flex h-full flex-col items-center justify-center bg-ink-black/10">
          <div className="font-meta text-[0.62rem] tracking-[0.22em] text-ink-black/35">
            NOT YET GENERATED
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
            containerClassName="absolute inset-0 h-full w-full"
            className="h-full w-full object-cover transition-transform duration-300 group-hover/panel-media:scale-[1.02]"
          />
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 bg-ink-black/62 opacity-0 transition-opacity duration-150 group-hover/panel-media:opacity-100">
            {onPanelClick && (
              <button
                type="button"
                className="pointer-events-auto inline-flex min-h-11 items-center border border-bristol bg-bristol px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-ink-black transition-colors hover:bg-pulp-paper"
                onClick={(e) => { e.stopPropagation(); onPanelClick(); }}
              >
                Preview
              </button>
            )}
            {imageAvailable && (
              <a
                href={imageDownloadUrl}
                download={`panel-${panelNum}.png`}
                className="pointer-events-auto inline-flex min-h-11 items-center border border-bristol/45 bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol transition-colors hover:border-bristol hover:bg-bristol/10"
                onClick={(e) => e.stopPropagation()}
              >
                Download
              </a>
            )}
          </div>
        </>
      )}

      {isFlagged && (
        <div className="absolute right-0 top-0 z-10 bg-hero-red px-2.5 py-1 font-meta text-[0.52rem] font-bold tracking-[0.14em] text-bristol">
          ⚑ RE-WORK
        </div>
      )}

      <div className="absolute left-2 top-2 flex h-6 min-w-6 items-center justify-center bg-ink-black/80 px-1.5 font-meta text-[0.56rem] font-bold tracking-[0.1em] text-bristol">
        {panelNum}
      </div>
    </div>
  );

  return (
    <EntityCard
      className={`h-full ${isFlagged ? "!border-hero-red" : ""}`}
      interactive={isInteractive}
      padding="cozy"
      media={media}
    >
      <div className={`mb-1 truncate font-meta text-[0.48rem] tracking-[0.18em] ${isFlagged ? "text-hero-red" : "text-ink-black/40"}`}>
        SHOT {panelNum} · {sceneLabel}
      </div>
      <div className="truncate font-body text-[0.82rem] font-semibold leading-5 text-ink-black">
        {cardTitle}
      </div>
      <div className="mt-0.5 truncate text-[0.72rem] leading-5 text-ink-black/55">
        {description || <span className="opacity-0 select-none">-</span>}
      </div>
      <div className="mt-auto pt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {canFlag && (
            <button
              type="button"
              aria-pressed={isFlagged}
              aria-label={isFlagged ? "Unflag panel" : "Flag panel for re-work"}
              title={isFlagged ? "Unflag" : "Flag for re-work"}
              className={`inline-flex h-11 w-11 items-center justify-center font-meta text-[0.78rem] tracking-[0.08em] transition-colors ${
                isFlagged
                  ? "bg-hero-red text-bristol hover:bg-hero-red/85"
                  : "text-ink-black/30 hover:text-hero-red"
              }`}
              onClick={(e) => { e.stopPropagation(); onToggleFlag?.(); }}
            >
              ⚑
            </button>
          )}
          {badge && (
            <span className={`inline-flex h-5 items-center px-2 font-meta text-[0.52rem] tracking-[0.1em] ${badge.className}`}>
              {badge.label}
            </span>
          )}
        </div>
        {onPanelClick && isInteractive && (
          <button
            type="button"
            className="inline-flex min-h-11 items-center px-2 font-meta text-[0.58rem] tracking-[0.1em] text-ink-black/40 transition-colors hover:text-ink-black"
            onClick={onPanelClick}
          >
            VIEW →
          </button>
        )}
      </div>
    </EntityCard>
  );
}
