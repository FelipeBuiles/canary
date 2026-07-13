import type { ReactNode } from "react";
import type { ImageGenerationMeta } from "../../types/api";
import { useShowDevContent } from "../../lib/devContent";
import { useI18n } from "../../i18n";
import { ImageModal } from "./ImageModal";

interface GenerationDetailsPanelProps {
  metadata?: ImageGenerationMeta | null;
  prompt?: string;
  parameters?: Record<string, unknown>;
  error?: ImageGenerationMeta["error"];
  classification?: string;
  recoverable?: boolean;
  userMessage?: string;
  recovery?: Record<string, unknown>;
  failedAt?: string;
  isFallback?: boolean;
  isLoading?: boolean;
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words border-[2px] border-ink-black/12 bg-bristol p-3 font-mono text-[0.68rem] leading-5 text-ink-black/75">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** User-first generation history with exact request/provenance gated to Dev Content. */
export function GenerationDetailsPanel({
  metadata,
  prompt,
  parameters,
  error,
  classification,
  recoverable,
  userMessage,
  recovery,
  failedAt,
  isFallback = false,
  isLoading = false,
}: GenerationDetailsPanelProps) {
  const { t } = useI18n();
  const [showDevContent] = useShowDevContent();
  const resolvedPrompt = metadata?.prompt ?? prompt ?? "";
  const resolvedParameters = metadata?.parameters ?? parameters ?? {};
  const resolvedError = metadata?.error ?? error;
  const resolvedClassification = metadata?.classification ?? classification;
  const resolvedRecoverable = metadata?.recoverable ?? recoverable;
  const resolvedUserMessage = metadata?.user_message ?? userMessage;
  const resolvedRecovery = metadata?.recovery ?? recovery;
  const resolvedFailedAt = metadata?.failed_at ?? failedAt;
  const provenance = metadata?.provenance;
  const hasExactHistory = !!provenance?.request_id;
  const dimensions = provenance?.effective_dimensions;

  if (isLoading) {
    return (
      <div className="space-y-3" aria-busy="true">
        <div className="h-4 w-32 animate-pulse bg-ink-black/10" />
        <div className="h-16 animate-pulse bg-ink-black/5" />
      </div>
    );
  }

  return (
    <section aria-label={t("ABOUT THIS IMAGE")}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-meta text-[0.54rem] tracking-[0.16em] text-ink-black/45">
          {t("ABOUT THIS IMAGE")}
        </div>
        {resolvedError && (
          <span className="bg-hero-red px-2 py-1 font-meta text-[0.48rem] tracking-[0.1em] text-bristol">
            {t("GENERATION FAILED")}
          </span>
        )}
      </div>

      {resolvedError && (
        <div className="mt-3 border-[2px] border-hero-red bg-hero-red/8 p-3">
          <strong className="font-meta text-[0.58rem] tracking-[0.12em] text-hero-red">
            {resolvedClassification === "provider_blocked" ? t("PROVIDER BLOCKED") : t("GENERATION FAILED")}
          </strong>
          <p className="mt-1 text-[0.78rem] leading-5 text-ink-black/75">
            {resolvedUserMessage ?? t("Describe a visual change and try again.")}
          </p>
          {resolvedRecoverable && (
            <p className="mt-1 font-meta text-[0.5rem] tracking-[0.12em] text-archive-sage">
              {t("THIS CAN BE RETRIED")}
            </p>
          )}
        </div>
      )}

      {!resolvedError && (
        <p className="mt-2 text-[0.78rem] leading-5 text-ink-black/60">
          {t("Created from your saved story details and visual direction.")}
        </p>
      )}

      {showDevContent && dimensions && (
        <dl className="mt-3 grid grid-cols-2 gap-2 text-[0.72rem]">
          <div className="bg-ink-black/5 px-3 py-2">
            <dt className="font-meta text-[0.48rem] tracking-[0.12em] text-ink-black/40">{t("OUTPUT")}</dt>
            <dd className="mt-0.5 font-semibold text-ink-black/75">{dimensions.width} × {dimensions.height}</dd>
          </div>
          {metadata?.kind && (
            <div className="min-w-0 bg-ink-black/5 px-3 py-2">
              <dt className="font-meta text-[0.48rem] tracking-[0.12em] text-ink-black/40">{t("ASSET TYPE")}</dt>
              <dd className="mt-0.5 truncate font-semibold text-ink-black/75">{metadata.kind.replaceAll("_", " ")}</dd>
            </div>
          )}
        </dl>
      )}

      {showDevContent ? (
        <div className="mt-5 space-y-4 border-t-[2px] border-ink-black/12 pt-4">
          <div>
            <div className="font-meta text-[0.52rem] tracking-[0.14em] text-ink-black/45">
              {t("EXACT REQUEST & PROVENANCE")}
            </div>
            <p className="mt-1 text-[0.7rem] leading-5 text-ink-black/50">
              {hasExactHistory
                ? t("Completed request data from the frozen generation lifecycle.")
                : t("No exact frozen request is available for this image.")}
            </p>
          </div>
          {resolvedPrompt && (
            <details>
              <summary className="cursor-pointer font-meta text-[0.52rem] tracking-[0.12em] text-ink-black/60">
                {t("SUBMITTED IMAGE REQUEST")}
              </summary>
              <p className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words border-[2px] border-ink-black/12 bg-bristol p-3 font-mono text-[0.68rem] leading-5 text-ink-black/75">
                {resolvedPrompt}
              </p>
            </details>
          )}
          <details>
            <summary className="cursor-pointer font-meta text-[0.52rem] tracking-[0.12em] text-ink-black/60">
              {t("REQUEST PARAMETERS")}
            </summary>
            <JsonBlock value={resolvedParameters} />
          </details>
          {provenance && (
            <details>
              <summary className="cursor-pointer font-meta text-[0.52rem] tracking-[0.12em] text-ink-black/60">
                {t("RESULT PROVENANCE")}
              </summary>
              <JsonBlock value={provenance} />
            </details>
          )}
          {resolvedError && (
            <details>
              <summary className="cursor-pointer font-meta text-[0.52rem] tracking-[0.12em] text-hero-red">
                {t("RAW FAILURE DETAILS")}{resolvedFailedAt ? ` · ${resolvedFailedAt}` : ""}
              </summary>
              <JsonBlock value={{ error: resolvedError, recovery: resolvedRecovery }} />
            </details>
          )}
        </div>
      ) : null}

      {showDevContent && isFallback && !metadata && (
        <p className="mt-2 text-[0.68rem] leading-5 text-ink-black/40">
          {t("Some details are reconstructed because this image predates generation history.")}
        </p>
      )}
    </section>
  );
}

interface GenerationDetailsModalProps extends GenerationDetailsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  imageUrl: string;
  imageAvailable?: boolean;
  overview?: ReactNode;
  actions?: ReactNode;
}

export function GenerationDetailsModal({
  isOpen,
  onClose,
  title,
  imageUrl,
  imageAvailable = true,
  overview,
  actions,
  ...details
}: GenerationDetailsModalProps) {
  const { t } = useI18n();
  return (
    <ImageModal
      isOpen={isOpen}
      onClose={onClose}
      src={imageAvailable ? imageUrl : ""}
      imageAvailable={imageAvailable}
      alt={title}
      title={title}
      sidebar={(
        <div className="space-y-6">
          {overview}
          <GenerationDetailsPanel {...details} />
        </div>
      )}
      actions={actions}
      emptyLabel={t("No image generated")}
    />
  );
}
