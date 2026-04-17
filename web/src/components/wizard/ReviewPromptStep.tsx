import { useMemo } from "react";
import { usePromptSummaries, usePromptsForScene } from "../../api/queries";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { SectionLabel } from "../SectionLabel";
import { Tag } from "../ui/Tag";
import { StyleCallout } from "./StyleCallout";
import { useI18n } from "../../i18n";

interface ReviewPromptStepProps {
  project: string;
  onApprove: () => void;
  isApproving: boolean;
}

function words(value: string): number {
  return value.trim().split(/\s+/).filter(Boolean).length;
}

export function ReviewPromptStep({ project, onApprove, isApproving }: ReviewPromptStepProps) {
  const { t } = useI18n();
  const { data: summaries, isLoading: loadingSummaries } = usePromptSummaries(project);
  const sampleScene = summaries?.[0]?.scene_id;
  const { data: prompts, isLoading: loadingPrompts } = usePromptsForScene(project, sampleScene);
  const samples = useMemo(() => (prompts ?? []).slice(0, 3), [prompts]);
  const totalPrompts = summaries?.reduce((sum, scene) => sum + scene.prompt_count, 0) ?? 0;
  const loading = loadingSummaries || loadingPrompts;

  return (
    <div className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="sage">{t("REVIEW CHECKPOINT")}</SectionLabel>
        <h1 className="mt-4 display-headline">{t("PROMPT SAMPLE")}</h1>
        <p className="mt-4 lead-pulp max-w-[56ch]">
          Informational pass before drawing. These compact prompts combine the active style,
          character refs, panel direction, and composition cues that will drive image generation.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Tag>{totalPrompts} prompts</Tag>
          {summaries?.length ? <Tag>{summaries.length} scenes</Tag> : null}
          {sampleScene ? <Tag>sample: {sampleScene}</Tag> : null}
        </div>
      </Card>

      <StyleCallout project={project} />

      {loading ? (
        <Card className="flex min-h-[22vh] items-center justify-center p-5">
          <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
            {t("LOADING PROMPT SAMPLE...")}
          </p>
        </Card>
      ) : samples.length ? (
        <section className="grid gap-4 lg:grid-cols-3">
          {samples.map((prompt) => (
            <Card key={`${prompt.scene_id}-${prompt.panel_number}`} className="p-4">
              <div className="flex items-start justify-between border-b-[2px] border-ink-black pb-3">
                <div>
                  <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
                    {prompt.scene_id.toUpperCase()}
                  </div>
                  <div className="font-display text-[1rem] font-bold tracking-[-0.04em]">
                    Panel {String(prompt.panel_number).padStart(2, "0")}
                  </div>
                </div>
                <div className="flex flex-wrap justify-end gap-1">
                  <Tag>{prompt.width}x{prompt.height}</Tag>
                  <Tag>{words(prompt.full_prompt)} words</Tag>
                </div>
              </div>
              <p className="mt-3 line-clamp-[10] text-[0.78rem] leading-6 text-ink-black/75">
                {prompt.full_prompt}
              </p>
              {prompt.reference_image_paths.length > 0 && (
                <div className="mt-3 border-t border-panel-line pt-3">
                  <div className="mb-2 font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
                    REFS
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {prompt.reference_image_paths.slice(0, 4).map((path) => (
                      <Tag key={path}>{path.split("/").slice(-2).join("/")}</Tag>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          ))}
        </section>
      ) : (
        <Card className="p-8 text-center">
          <div className="font-display text-[1rem] font-bold text-ink-black/50">
            NO PROMPTS FOUND
          </div>
          <div className="mt-2 font-meta text-[0.48rem] tracking-[0.16em] text-ink-black/40">
            RUN THE DIRECT STAGE AGAIN TO BUILD IMAGE PROMPTS
          </div>
        </Card>
      )}

      <div className="flex items-center gap-4">
        <Button size="lg" onClick={onApprove} disabled={isApproving || !samples.length}>
          {isApproving ? t("APPROVING…") : t("APPROVE & DRAW")}
        </Button>
        <span className="text-[0.72rem] text-ink-black/40">
          Edits are available later in the Direct room; this checkpoint is review-only for now.
        </span>
      </div>
    </div>
  );
}
