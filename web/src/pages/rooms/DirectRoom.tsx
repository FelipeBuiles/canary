import { useParams, useSearchParams } from "react-router-dom";
import { usePromptSummaries, usePromptsForScene, useUpdatePrompt, useProjectStatus } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { EditableText } from "../../components/ui/EditableText";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { renderPanelPromptBody } from "../../lib/prompting";
import type { ImagePrompt } from "../../types/api";

function SummaryTile({
  label,
  value,
  onSave,
}: {
  label: string;
  value: string;
  onSave?: (value: string) => void;
}) {
  return (
    <div className="bg-surface-container px-5 py-5">
      <div className="font-meta text-[0.72rem] font-bold tracking-[0.2em] text-ink-black/45">
        {label}
      </div>
      <div className="mt-2 text-[1.08rem] font-semibold leading-7 text-ink-black/84">
        {onSave ? (
          <EditableText value={value || "—"} onSave={onSave} multiline />
        ) : (
          value || "—"
        )}
      </div>
    </div>
  );
}

function DirectPromptDetail({
  prompt,
  onSave,
}: {
  prompt: ImagePrompt;
  onSave: (patch: Partial<ImagePrompt>) => void;
}) {
  const characterSummary = (prompt.subjects ?? [])
    .filter((s) => s.character_id)
    .map((s) => s.name ? `${s.name} (${s.character_id})` : s.character_id!)
    .join(" · ") || "No character refs";

  function saveStructuredPatch(patch: Partial<ImagePrompt>) {
    const next = { ...prompt, ...patch };
    onSave({ ...patch, full_prompt: renderPanelPromptBody(next) });
  }

  return (
    <div className="min-w-0">
      <div className="grid gap-5 md:grid-cols-2">
        <SummaryTile
          label="STYLE"
          value={prompt.style ?? ""}
          onSave={(style) => saveStructuredPatch({ style })}
        />
        <SummaryTile
          label="SHOT"
          value={prompt.composition ?? ""}
          onSave={(composition) => saveStructuredPatch({ composition })}
        />
        <SummaryTile label="CHARACTERS" value={characterSummary} />
        <SummaryTile
          label="SETTING"
          value={prompt.setting ?? ""}
          onSave={(setting) => saveStructuredPatch({ setting })}
        />
      </div>

      <div className="mt-7">
        <div className="mb-3 font-meta text-[0.72rem] font-bold tracking-[0.2em] text-ink-black/45">
          ASSEMBLED PROMPT
        </div>
        <EditableText
          value={prompt.full_prompt}
          onSave={(full_prompt) => onSave({ full_prompt })}
          multiline
          className="block min-h-[300px] whitespace-pre-wrap bg-ink-black px-7 py-7 font-body text-[1rem] font-semibold leading-8 text-pulp-paper/82"
          inputClassName="min-h-[300px] bg-ink-black text-pulp-paper"
        />
      </div>
    </div>
  );
}

export function DirectRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePromptSummaries(name);
  const { data: status } = useProjectStatus(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const selectedPanel = Number(searchParams.get("panel"));
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: prompts, isLoading: loadingPrompts } = usePromptsForScene(name, activeScene);
  const updatePrompt = useUpdatePrompt();
  const stageInfo = status?.stages?.direct;
  const stageStatus = stageInfo?.status ?? "pending";

  const activePrompt =
    prompts?.find((prompt) => prompt.panel_number === selectedPanel) ??
    prompts?.[0] ??
    null;

  const handleSavePrompt = (prompt: ImagePrompt, patch: Partial<ImagePrompt>) => {
    if (!name || !activeScene) return;
    updatePrompt.mutate({
      project: name,
      sceneId: activeScene,
      data: { ...prompt, ...patch },
    });
  };

  const selectScene = (sceneId: string) => {
    setSearchParams({ scene: sceneId }, { replace: true });
  };

  const selectPanel = (panelNumber: number) => {
    if (!activeScene) return;
    setSearchParams(
      { scene: activeScene, panel: String(panelNumber) },
      { replace: true },
    );
  };

  if (isLoading || (!summaries?.length && stageStatus !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING IMAGE PROMPTS…" />;
  }

  if (!summaries?.length || !name) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="direct"
          status={stageStatus}
          itemsDone={stageInfo?.items_done}
          itemsTotal={stageInfo?.items_total}
        />
      </RoomShell>
    );
  }

  return (
    <RoomShell>
      <div className="flex h-[calc(100vh-3rem)] min-h-0 flex-col gap-10 md:h-[calc(100vh-5rem)]">
        <ShowcaseHeader
          label="DIRECT / IMAGE PROMPTS"
          title="IMAGE PROMPTS"
          lead="Compiled prompts with character and location refs baked in — the last human-readable artifact before image generation."
          actions={name ? <RerunStageAction project={name} stage="direct" label="Direct" /> : null}
        />

        <section className="grid min-h-0 flex-1 grid-rows-[minmax(132px,30%)_minmax(0,1fr)] overflow-hidden border-[2px] border-ink-black bg-bristol xl:grid-cols-[300px_minmax(0,1fr)] xl:grid-rows-none">
          {summaries && (
            <div className="min-h-0 border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
              <SceneSidebar
                items={summaries.map((s) => ({
                  id: s.scene_id,
                  label: s.scene_id.replace(/_/g, " ").toUpperCase(),
                  count: `${s.prompt_count} prompts`,
                }))}
                activeId={activeScene ?? ""}
                onSelect={selectScene}
              />
            </div>
          )}

          <div className="min-h-0 min-w-0 overflow-hidden">
            {loadingPrompts ? (
              <div className="p-6"><LoadingBlock label="LOADING…" /></div>
            ) : activePrompt && prompts?.length ? (
              <div className="h-full min-h-0 overflow-y-auto px-6 py-8 md:px-8">
                <div className="mb-7 flex max-w-full overflow-x-auto" role="tablist" aria-label="Prompt panels">
                  {prompts.map((prompt) => {
                    const isActive = prompt.panel_number === activePrompt.panel_number;
                    return (
                      <button
                        key={`${prompt.scene_id}-${prompt.panel_number}`}
                        type="button"
                        onClick={() => selectPanel(prompt.panel_number)}
                        className={
                          isActive
                            ? "shrink-0 bg-ink-black px-7 py-3 font-meta text-[0.82rem] font-bold tracking-[0.12em] text-pulp-paper"
                            : "shrink-0 border-y border-r border-panel-line bg-pulp-paper px-7 py-3 font-meta text-[0.82rem] font-bold tracking-[0.12em] text-ink-black/62 hover:bg-surface-container"
                        }
                      >
                        Panel {String(prompt.panel_number).padStart(2, "0")}
                      </button>
                    );
                  })}
                </div>
                <DirectPromptDetail
                  prompt={activePrompt}
                  onSave={(patch) => handleSavePrompt(activePrompt, patch)}
                />
              </div>
            ) : (
              <div className="p-6">
                <StateBlock title="SELECT A SCENE" description="Select a scene to view image prompts." icon="draft" />
              </div>
            )}
          </div>
        </section>
      </div>
    </RoomShell>
  );
}
