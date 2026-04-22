import { useState } from "react";
import type { ImageStatus } from "../types/api";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import { ImageModal } from "./ui/ImageModal";
import { StatusPill } from "./ui/StatusPill";
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

function statusTone(state: PanelState): "sage" | "gold" | "red" {
  if (state === "active" || state === "narrative") return "sage";
  if (state === "inking" || state === "queued" || state === "regening") return "gold";
  return "red";
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
      <Card>
        <div
          className="relative aspect-[4/5] overflow-hidden border-b-[2px] border-ink-black bg-ink-black group cursor-pointer"
          onClick={handleClick}
        >
          {state === "queued" || state === "regening" ? (
            <div className="flex h-full flex-col items-center justify-center">
              <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
                {state === "queued" ? t("QUEUED") : t("REGENING…")}
              </div>
              <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
                {state === "queued" ? t("WAITING FOR GENERATOR") : t("GENERATING NEW PANEL")}
              </div>
            </div>
          ) : state === "inking" ? (
            <div className="flex h-full flex-col items-center justify-center">
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
                <Button
                  size="sm"
                  className="mt-3 border-hero-red"
                  onClick={(e) => {
                    e.stopPropagation();
                    onRegenerate();
                  }}
                >
                  {t("QUICK RE-DO")}
                </Button>
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
              <img
                src={imageUrl}
                alt={`Panel ${panelNumber}`}
                loading="lazy"
                width={400}
                height={500}
                className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
              />
              {state === "active" && onRegenerate && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/60 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity duration-150">
                  <Button
                    size="md"
                    className="border-bristol"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRegenerate();
                    }}
                  >
                    {t("QUICK RE-DO")}
                  </Button>
                </div>
              )}
              {state === "narrative" && narrative && (
                <div className="absolute bottom-0 left-0 right-0 bg-ink-black/75 p-3">
                  <div className="text-[0.72rem] leading-5 text-bristol/90">
                    {narrative}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-between p-2">
          <span className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
            PANEL {String(panelNumber).padStart(2, "0")}
          </span>
          <StatusPill tone={statusTone(state)}>
            {statusLabel(state, t)}
          </StatusPill>
        </div>
      </Card>
      <ImageModal 
        isOpen={isModalOpen} 
        onClose={() => setIsModalOpen(false)} 
        src={imageUrl} 
        alt={`Panel ${panelNumber}`} 
      />
    </>
  );
}
