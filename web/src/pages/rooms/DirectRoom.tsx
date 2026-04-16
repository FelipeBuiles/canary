import { useState } from "react";
import { useParams } from "react-router-dom";
import { usePromptSummaries, usePromptsForScene } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { Card } from "../../components/ui/Card";
import { Tag } from "../../components/ui/Tag";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";

export function DirectRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePromptSummaries(name);
  const [selectedScene, setSelectedScene] = useState<string | null>(null);
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: prompts, isLoading: loadingPrompts } = usePromptsForScene(name, activeScene);

  return (
    <RoomShell
      isLoading={isLoading}
      loadingText="LOADING IMAGE PROMPTS..."
      isEmpty={!summaries?.length || !name}
      emptyTitle="IMAGE PROMPTS NOT AVAILABLE"
      emptyDescription="Complete the DIRECT stage first."
    >
      <ShowcaseHeader
        label="DIRECT / IMAGE PROMPTS"
        title="IMAGE PROMPTS"
        lead="Compiled prompts with character and location refs baked in — the last human-readable artifact before image generation."
      />

      <section className="grid gap-5 xl:grid-cols-[220px_1fr]">
        {summaries && (
          <SceneSidebar
            items={summaries.map((s) => ({
              id: s.scene_id,
              label: s.scene_id.replace("_", " ").toUpperCase(),
              count: `${s.prompt_count} prompts`,
            }))}
            activeId={activeScene ?? ""}
            onSelect={setSelectedScene}
          />
        )}

        <div>
          {loadingPrompts ? (
            <div className="flex min-h-[40vh] items-center justify-center">
              <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                LOADING...
              </p>
            </div>
          ) : prompts?.length ? (
            <div className="space-y-4">
              {prompts.map((prompt) => (
                <Card key={`${prompt.scene_id}-${prompt.panel_number}`} className="p-4">
                  <div className="flex items-start justify-between border-b-[2px] border-ink-black pb-3">
                    <div>
                      <div className="font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
                        PANEL {String(prompt.panel_number).padStart(2, "0")}
                      </div>
                      <div className="font-display text-[1rem] font-bold tracking-[-0.04em]">
                        {prompt.scene_id} — Panel {prompt.panel_number}
                      </div>
                    </div>
                    <div className="flex gap-1.5">
                      <Tag>{prompt.width}×{prompt.height}</Tag>
                      <Tag>steps: {prompt.steps}</Tag>
                    </div>
                  </div>
                  <div className="mt-3 whitespace-pre-wrap text-[0.82rem] leading-7 text-ink-black/80">
                    {prompt.full_prompt}
                  </div>
                  {prompt.reference_image_paths.length > 0 && (
                    <div className="mt-3 border-t border-panel-line pt-3">
                      <div className="mb-2 font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/45">
                        REFERENCE IMAGES
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {prompt.reference_image_paths.map((path: string, i: number) => (
                          <Tag key={i}>{path.split("/").pop()}</Tag>
                        ))}
                      </div>
                    </div>
                  )}
                </Card>
              ))}
            </div>
          ) : (
            <div className="flex min-h-[40vh] items-center justify-center text-[0.82rem] text-ink-black/50">
              Select a scene to view image prompts.
            </div>
          )}
        </div>
      </section>
    </RoomShell>
  );
}
