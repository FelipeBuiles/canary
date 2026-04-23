import { useState } from "react";
import type { ImageStatus } from "../types/api";
import { ImageModal } from "./ui/ImageModal";
import { LazyImage } from "./ui/LazyImage";
import { useI18n } from "../i18n";

type PanelState = "active" | "inking" | "failed" | "narrative" | "queued" | "regening" | "stale";

function resolvePanelState(
  status: ImageStatus["status"],
  regenMode: "queued" | "running" | null,
  hasNarrative?: boolean,
): PanelState {
  if (regenMode === "queued") return "queued";
  if (regenMode === "running") return "regening";
  if (status === "stale") return "stale";
  if (status === "failed") return "failed";
  if (status === "pending") return "inking";
  if (hasNarrative) return "narrative";
  return "active";
}

function statusLabel(state: PanelState, t: (text: string) => string) {
  if (state === "active" || state === "narrative") return "ACCEPTED";
  if (state === "inking") return t("PROCESSING");
  if (state === "queued") return t("QUEUED");
  if (state === "regening") return "REGENING";
  if (state === "stale") return "STALE";
  return t("ERROR");
}

interface PanelCardProps {
  sceneId: string;
  panelNumber: number;
  status: ImageStatus["status"];
  imageUrl: string;
  narrative?: string;
  errorMessage?: string;
  isRegening?: boolean;
  regenMode?: "queued" | "running" | null;
  regenError?: string | null;
  onRegenerate?: () => void;
  onPanelClick?: () => void;
}

export function PanelCard({
  panelNumber,
  status,
  imageUrl,
  narrative,
  errorMessage,
  isRegening = false,
  regenMode,
  regenError,
  onRegenerate,
  onPanelClick,
}: PanelCardProps) {
  const resolvedRegenMode = regenMode ?? (isRegening ? "running" : null);
  const state = resolvePanelState(status, resolvedRegenMode, !!narrative);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { t } = useI18n();

  const handleClick = () => {
    if (state === "active" || state === "narrative") {
      if (onPanelClick) {
        onPanelClick();
      } else {
        setIsModalOpen(true);
      }
    }
  };

  return (
    <>
      <article className="group/panel min-w-0">
        <div
          className="relative aspect-[4/5] overflow-hidden border-[2px] border-transparent bg-surface-container transition-colors duration-150 group-hover/panel:border-ink-black"
          onClick={handleClick}
        >
          {state === "queued" || state === "regening" ? (
            <div className="flex h-full flex-col items-center justify-center bg-ink-black/80">
              <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                {state === "queued" ? t("QUEUED") : t("REGENING…")}
              </div>
              <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                {state === "queued" ? t("WAITING FOR GENERATOR") : t("GENERATING NEW PANEL")}
              </div>
            </div>
          ) : state === "inking" ? (
            <div className="flex h-full flex-col items-center justify-center bg-ink-black/80">
              <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                INKING…
              </div>
              <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                APPLYING PRODUCTION LOGIC
              </div>
            </div>
          ) : state === "stale" ? (
            <div className="flex h-full flex-col items-center justify-center bg-hero-red/10 px-3">
              <div className="font-display text-[1.25rem] font-bold leading-none tracking-[-0.05em] text-hero-red">
                GENERATION STALE
              </div>
              <div className="mt-2 text-center text-[0.72rem] text-hero-red/80">
                Job tracking was interrupted. Re-run this panel.
              </div>
              {onRegenerate && (
                <button
                  type="button"
                  className="mt-3 border border-hero-red px-4 py-2 font-meta text-[0.62rem] tracking-[0.14em] text-hero-red transition-colors hover:bg-hero-red hover:text-bristol"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRegenerate();
                  }}
                >
                  {t("QUICK RE-DO")}
                </button>
              )}
            </div>
          ) : state === "failed" ? (
            <div className="flex h-full flex-col items-center justify-center bg-hero-red/10">
              <div className="flex h-14 w-14 items-center justify-center border-[2px] border-hero-red text-[1.4rem] font-bold text-hero-red">
                △
              </div>
              <div className="mt-4 font-display text-[1.25rem] font-bold leading-none tracking-[-0.05em] text-hero-red">
                GENERATION FAILED
              </div>
              {(regenError || errorMessage) && (
                <div className="mt-2 max-w-[20ch] text-center text-[0.72rem] text-hero-red/80">
                  {regenError ?? errorMessage}
                </div>
              )}
            </div>
          ) : (
            <>
              <LazyImage
                src={imageUrl}
                alt={`Panel ${panelNumber}`}
                loading="lazy"
                width={400}
                height={500}
                containerClassName="h-full w-full"
                className="h-full w-full object-cover transition-transform duration-300 group-hover/panel:scale-[1.02]"
              />
              {state === "narrative" && narrative && (
                <div className="absolute bottom-0 left-0 right-0 bg-ink-black/75 p-3">
                  <div className="text-[0.72rem] leading-5 text-bristol/90">
                    {narrative}
                  </div>
                </div>
              )}
            </>
          )}

          {state !== "failed" && state !== "stale" && state !== "queued" && state !== "regening" && state !== "inking" && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 bg-ink-black/62 opacity-0 transition-opacity duration-150 group-hover/panel:opacity-100">
              {onPanelClick && (
                <button
                  type="button"
                  className="pointer-events-auto border border-bristol bg-bristol px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-ink-black transition-colors hover:bg-pulp-paper"
                  onClick={(e) => {
                    e.stopPropagation();
                    onPanelClick();
                  }}
                >
                  View
                </button>
              )}
              {onRegenerate && (
                <button
                  type="button"
                  className="pointer-events-auto border border-bristol/45 bg-transparent px-5 py-2 font-meta text-[0.72rem] tracking-[0.12em] text-bristol transition-colors hover:border-bristol hover:bg-bristol/10"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRegenerate();
                  }}
                >
                  Regen
                </button>
              )}
            </div>
          )}

          <div className="absolute bottom-0 left-0 right-0 flex h-8 items-center justify-between bg-ink-black/82 px-3">
            <span className="font-body text-[0.76rem] font-semibold text-bristol/70">
              Panel {String(panelNumber).padStart(2, "0")}
            </span>
            <span className={`flex h-5 min-w-5 items-center justify-center px-1.5 font-meta text-[0.56rem] tracking-[0.1em] text-bristol ${
              state === "failed" || state === "stale"
                ? "bg-hero-red"
                : state === "inking" || state === "queued" || state === "regening"
                  ? "bg-narrator-gold text-ink-black"
                  : "bg-archive-sage"
            }`}>
              {state === "active" || state === "narrative" ? "✓" : statusLabel(state, t)}
            </span>
          </div>
        </div>
      </article>
      <ImageModal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        src={imageUrl} 
        alt={`Panel ${panelNumber}`} 
      />
    </>
  );
}
