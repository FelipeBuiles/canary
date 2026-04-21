import { useParams, useSearchParams } from "react-router-dom";
import { usePromptSummaries, usePromptsForScene, useUpdatePrompt } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { PromptLineageCard } from "../../components/PromptLineageCard";
import { Button } from "../../components/ui/Button";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { useRunAction } from "../../hooks/useRunAction";
import type { ImagePrompt } from "../../types/api";

export function DirectRoom() {
  const { name } = useParams<{ name: string }>();
  const { handleRun, isPending } = useRunAction();
  const { data: summaries, isLoading } = usePromptSummaries(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: prompts, isLoading: loadingPrompts } = usePromptsForScene(name, activeScene);
  const updatePrompt = useUpdatePrompt();

  const handleSavePrompt = (prompt: ImagePrompt, patch: Partial<ImagePrompt>) => {
    if (!name || !activeScene) return;
    updatePrompt.mutate({
      project: name,
      sceneId: activeScene,
      data: { ...prompt, ...patch },
    });
  };

  return (
    <RoomShell
      isLoading={isLoading}
      loadingText="LOADING IMAGE PROMPTS…"
      isEmpty={!summaries?.length || !name}
      emptyTitle="IMAGE PROMPTS NOT AVAILABLE"
      emptyDescription="Complete the DIRECT stage first."
    >
      <ShowcaseHeader
        label="DIRECT / IMAGE PROMPTS"
        title="IMAGE PROMPTS"
        lead="Compiled prompts with character and location refs baked in — the last human-readable artifact before image generation."
        actions={(
          <Button
            size="sm"
            variant="outline"
            onClick={() => name && handleRun(name, "prompts", true)}
            disabled={isPending}
          >
            {isPending ? "RERUNNING…" : "RERUN DIRECT"}
          </Button>
        )}
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
            onSelect={(id) => setSearchParams({ scene: id }, { replace: true })}
          />
        )}

        <div>
          {loadingPrompts ? (
            <div className="flex min-h-[40vh] items-center justify-center">
              <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                LOADING…
              </p>
            </div>
          ) : prompts?.length ? (
            <div className="space-y-4">
              {prompts.map((prompt, index) => (
                <div key={`${prompt.scene_id}-${prompt.panel_number}`} className={index > 0 ? "border-t-2 border-ink-black pt-4 mt-4" : ""}>
                  <PromptLineageCard
                    prompt={prompt}
                    onSave={(patch) => handleSavePrompt(prompt, patch)}
                    mode="edit"
                    showAdvanced
                    project={name}
                  />
                </div>
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
