import { useState } from "react";
import type { ImageStatus } from "../types/api";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";

type PanelState = "active" | "inking" | "failed" | "narrative" | "regening";

function resolvePanelState(
  status: ImageStatus["status"],
  isRegening: boolean,
  hasNarrative?: boolean,
): PanelState {
  if (isRegening) return "regening";
  if (status === "failed") return "failed";
  if (status === "pending") return "inking";
  if (hasNarrative) return "narrative";
  return "active";
}

function statusTone(state: PanelState) {
  if (state === "active" || state === "narrative") return "bg-archive-sage text-ink-black";
  if (state === "inking" || state === "regening") return "bg-narrator-gold text-ink-black";
  return "bg-hero-red text-bristol";
}

function statusLabel(state: PanelState) {
  if (state === "active" || state === "narrative") return "ACCEPTED";
  if (state === "inking") return "PROCESSING";
  if (state === "regening") return "REGENING";
  return "ERROR";
}

interface PanelCardProps {
  sceneId: string;
  panelNumber: number;
  status: ImageStatus["status"];
  imageUrl: string;
  narrative?: string;
  errorMessage?: string;
  isRegening?: boolean;
  regenError?: string | null;
  onRegenerate?: () => void;
}

export function PanelCard({
  panelNumber,
  status,
  imageUrl,
  narrative,
  errorMessage,
  isRegening = false,
  regenError,
  onRegenerate,
}: PanelCardProps) {
  const [hovered, setHovered] = useState(false);
  const state = resolvePanelState(status, isRegening, !!narrative);

  return (
    <Card
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="relative aspect-[4/5] overflow-hidden border-b-[2px] border-ink-black bg-ink-black">
        {state === "regening" ? (
          <div className="flex h-full flex-col items-center justify-center">
            <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
              REGENING...
            </div>
            <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
              GENERATING NEW PANEL
            </div>
          </div>
        ) : state === "inking" ? (
          <div className="flex h-full flex-col items-center justify-center">
            <div className="font-display text-[1.45rem] font-bold leading-none tracking-[-0.05em] text-narrator-gold animate-pulse">
              INKING...
            </div>
            <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/55">
              APPLYING PRODUCTION LOGIC
            </div>
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
              className="h-full w-full object-cover"
            />
            {state === "active" && hovered && onRegenerate && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-ink-black/60">
                <Button
                  size="md"
                  className="border-bristol"
                  onClick={onRegenerate}
                >
                  REGENERATE
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
        <span
          className={`border border-ink-black px-2 py-1 font-meta text-[0.44rem] tracking-[0.14em] ${statusTone(state)}`}
        >
          {statusLabel(state)}
        </span>
      </div>
    </Card>
  );
}
