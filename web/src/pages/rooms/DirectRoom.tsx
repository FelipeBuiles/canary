import { useParams, useSearchParams } from "react-router-dom";
import { usePromptSummaries, usePromptsForScene, useUpdatePrompt } from "../../api/queries";
import { ShowcaseHeader } from "../../components/ShowcaseHeader";
import { EditableText } from "../../components/ui/EditableText";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
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
    <div className="bg-surface-container px-4 py-3">
      <div className="font-meta text-[0.58rem] tracking-[0.18em] text-ink-black/45">
        {label}
      </div>
      <div className="mt-2 text-[1rem] leading-6 text-ink-black/82">
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
  const characterTokens = (prompt.subjects ?? [])
    .map((subject) => subject.character_id)
    .filter((id): id is string => !!id);
  const characterSummary = characterTokens.length > 0
    ? characterTokens.map((id) => `[${id}]`).join(" · ")
    : "No character refs";

  function saveStructuredPatch(patch: Partial<ImagePrompt>) {
    const next = { ...prompt, ...patch };
    onSave({ ...patch, full_prompt: renderPanelPromptBody(next) });
  }

  return (
    <div>
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
        <div className="mb-3 font-meta text-[0.58rem] tracking-[0.18em] text-ink-black/45">
          ASSEMBLED PROMPT
        </div>
        <EditableText
          value={prompt.full_prompt}
          onSave={(full_prompt) => onSave({ full_prompt })}
          multiline
          className="block min-h-[300px] whitespace-pre-wrap bg-ink-black px-5 py-5 font-meta text-[0.78rem] leading-7 text-pulp-paper/80"
          inputClassName="min-h-[300px] bg-ink-black text-pulp-paper"
        />
      </div>
    </div>
  );
}

export function DirectRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePromptSummaries(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const selectedPanel = Number(searchParams.get("panel"));
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: prompts, isLoading: loadingPrompts } = usePromptsForScene(name, activeScene);
  const updatePrompt = useUpdatePrompt();

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

  return (
    <RoomShell
      isLoading={isLoading}
      loadingText="LOADING IMAGE PROMPTS…"
      isEmpty={!summaries?.length || !name}
      emptyTitle="IMAGE PROMPTS NOT AVAILABLE"
      emptyDescription="Complete DIRECT first."
    >
      <ShowcaseHeader
        label="DIRECT / IMAGE PROMPTS"
        title="IMAGE PROMPTS"
        lead="Compiled prompts with character and location refs baked in — the last human-readable artifact before image generation."
        actions={name ? <RerunStageAction project={name} stage="prompts" label="Direct" /> : null}
      />

      <section className="grid border-[2px] border-ink-black bg-bristol xl:grid-cols-[200px_1fr]">
        {summaries && (
          <div className="border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
            <SceneSidebar
              items={summaries.map((s) => ({
                id: s.scene_id,
                label: s.scene_id.replace("_", " ").toUpperCase(),
                count: `${s.prompt_count} prompts`,
              }))}
              activeId={activeScene ?? ""}
              onSelect={selectScene}
            />
          </div>
        )}

        <div className="min-w-0 p-5 md:p-8">
          {loadingPrompts ? (
            <LoadingBlock label="LOADING…" />
          ) : activePrompt && prompts?.length ? (
            <>
              <div className="mb-7 flex overflow-x-auto">
                {prompts.map((prompt) => {
                  const isActive = prompt.panel_number === activePrompt.panel_number;
                  return (
                    <button
                      key={`${prompt.scene_id}-${prompt.panel_number}`}
                      type="button"
                      onClick={() => selectPanel(prompt.panel_number)}
                      className={
                        isActive
                          ? "bg-ink-black px-6 py-3 font-meta text-[0.7rem] tracking-[0.12em] text-pulp-paper"
                          : "border-y border-r border-panel-line bg-pulp-paper px-6 py-3 font-meta text-[0.7rem] tracking-[0.12em] text-ink-black/62 hover:bg-surface-container"
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
            </>
          ) : (
            <StateBlock title="SELECT A SCENE" description="Select a scene to view image prompts." icon="draft" />
          )}
        </div>
      </section>
    </RoomShell>
  );
}
