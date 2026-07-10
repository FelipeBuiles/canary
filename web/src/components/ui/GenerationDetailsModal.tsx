import { useEffect } from "react";
import { redactDevParameters, redactDevText, useShowDevContent } from "../../lib/devContent";
import { Icon } from "./Icon";
import { LazyImage } from "./LazyImage";

interface GenerationDetailsModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  imageUrl: string;
  imageAvailable?: boolean;
  prompt: string;
  parameters: Record<string, unknown>;
  error?: {
    type?: string;
    message?: string;
    chain?: Array<Record<string, unknown>>;
  };
  classification?: string;
  recoverable?: boolean;
  userMessage?: string;
  recovery?: Record<string, unknown>;
  failedAt?: string;
  isFallback?: boolean;
}

export function GenerationDetailsModal({
  isOpen,
  onClose,
  title,
  imageUrl,
  imageAvailable = true,
  prompt,
  parameters,
  error,
  classification,
  recoverable,
  userMessage,
  recovery,
  failedAt,
  isFallback = false,
}: GenerationDetailsModalProps) {
  const [showDevContent] = useShowDevContent();
  const visiblePrompt = showDevContent ? prompt : redactDevText(prompt);
  const visibleParameters = showDevContent ? parameters : redactDevParameters(parameters);

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
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink-black/80 p-4"
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
            {error && (
              <div className="font-meta text-[0.46rem] tracking-[0.16em] text-hero-red">
                GENERATION FAILED{failedAt ? ` · ${failedAt}` : ""}
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
        <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.8fr)]">
          <div className="min-h-0 border-r-[2px] border-ink-black p-4">
            <div className="flex h-full w-full items-center justify-center bg-ink-black">
              {imageAvailable ? (
                <LazyImage
                  src={imageUrl}
                  alt={title}
                  containerClassName="h-full w-full"
                  preserveAspectBox
                />
              ) : (
                <div className="px-6 text-center font-meta text-[0.7rem] font-bold uppercase tracking-[0.18em] text-bristol/55">
                  No panel image generated
                </div>
              )}
            </div>
          </div>
          <div className="min-h-0 space-y-4 overflow-y-auto p-4">
            {!showDevContent && (
              <div className="border-[2px] border-ink-black bg-chip-gold px-3 py-2 font-meta text-[0.48rem] tracking-[0.14em] text-ink-black/65">
                DEV CONTENT HIDDEN. ENABLE SHOW DEV CONTENT IN SETTINGS TO VIEW RAW PATHS, MODEL NAMES, SHA HASHES, AND FULL PARAMETERS.
              </div>
            )}
            {error && (
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-hero-red">MODEL ERROR</div>
                <div className="mt-2 border-[2px] border-hero-red bg-hero-red/8 p-3">
                  <div className="font-meta text-[0.62rem] tracking-[0.12em] text-ink-black">
                    {classification === "provider_blocked" ? "PROVIDER BLOCKED" : "GENERATION FAILED"}
                    {recoverable ? " · RECOVERABLE" : ""}
                  </div>
                  <p className="mt-2 text-sm leading-6 text-ink-black/75">
                    {userMessage ?? "Review the raw model response below, edit the prompt if needed, and regenerate this panel."}
                  </p>
                  {recovery && (
                    <pre className="mt-3 whitespace-pre-wrap border border-ink-black/20 bg-bristol p-2 font-mono text-[0.68rem] leading-relaxed text-ink-black/70">
                      {JSON.stringify(recovery, null, 2)}
                    </pre>
                  )}
                </div>
                <pre className="mt-2 whitespace-pre-wrap border-[2px] border-hero-red bg-bristol p-3 font-mono text-xs leading-relaxed text-ink-black">
                  {JSON.stringify(error, null, 2)}
                </pre>
              </div>
            )}
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50">FULL PROMPT</div>
              <pre className="mt-2 whitespace-pre-wrap border-[2px] border-ink-black bg-bristol p-3 font-mono text-xs leading-relaxed text-ink-black">
                {visiblePrompt}
              </pre>
            </div>
            <div>
              <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50">PARAMETERS</div>
              <pre className="mt-2 whitespace-pre-wrap border-[2px] border-ink-black bg-bristol p-3 font-mono text-xs leading-relaxed text-ink-black">
                {JSON.stringify(visibleParameters, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
