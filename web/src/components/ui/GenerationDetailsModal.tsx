import { useEffect } from "react";
import { Icon } from "./Icon";

interface GenerationDetailsModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  imageUrl: string;
  prompt: string;
  parameters: Record<string, unknown>;
  isFallback?: boolean;
}

export function GenerationDetailsModal({
  isOpen,
  onClose,
  title,
  imageUrl,
  prompt,
  parameters,
  isFallback = false,
}: GenerationDetailsModalProps) {
  useEffect(() => {
    if (isOpen) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink-black/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[90vh] w-[95vw] max-w-[1400px] flex-col border-[4px] border-ink-black bg-bristol"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b-[2px] border-ink-black p-4">
          <div>
            <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">GENERATION DETAILS</div>
            <div className="font-display text-[1.15rem] font-bold tracking-[-0.04em]">{title}</div>
            {isFallback && (
              <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/55">
                FALLBACK DETAILS (IMAGE PREDATES METADATA)
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 text-ink-black/50 transition-colors hover:text-hero-red"
          >
            <Icon name="x" size={20} />
          </button>
        </div>
        <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[1fr_1fr]">
          <div className="min-h-0 border-r-[2px] border-ink-black p-4">
            <div className="flex h-full w-full items-center justify-center bg-ink-black">
              <img src={imageUrl} alt={title} className="w-full max-h-full object-contain" />
            </div>
          </div>
          <div className="min-h-0 space-y-4 overflow-y-auto p-4">
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50">FULL PROMPT</div>
              <pre className="mt-2 whitespace-pre-wrap border-[2px] border-ink-black bg-bristol p-3 font-mono text-xs leading-relaxed text-ink-black">
                {prompt}
              </pre>
            </div>
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50">PARAMETERS</div>
              <pre className="mt-2 whitespace-pre-wrap border-[2px] border-ink-black bg-bristol p-3 font-mono text-xs leading-relaxed text-ink-black">
                {JSON.stringify(parameters, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
