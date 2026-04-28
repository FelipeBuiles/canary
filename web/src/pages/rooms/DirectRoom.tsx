import { useRef } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  usePromptSummaries,
  usePromptsForScene,
  useUpdatePrompt,
  useProjectStatus,
  useStoryBible,
  useStyles,
} from "../../api/queries";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { CollapsibleSection } from "../../components/ui/CollapsibleSection";
import { EditableText } from "../../components/ui/EditableText";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { RerunStageAction } from "../../components/ui/RerunStageAction";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { useCharacterName } from "../../hooks/useCharacterName";
import { useHeaderMode } from "../../hooks/useHeaderMode";
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
  resolveName,
  styleLabel,
}: {
  prompt: ImagePrompt;
  onSave: (patch: Partial<ImagePrompt>) => void;
  resolveName: (id: string) => string;
  styleLabel?: string;
}) {
  function saveStructuredPatch(patch: Partial<ImagePrompt>) {
    const next = { ...prompt, ...patch };
    onSave({ ...patch, full_prompt: renderPanelPromptBody(next) });
  }

  const hasSubjects = (prompt.subjects ?? []).length > 0;

  const techFields: { label: string; value: string | number | null | undefined }[] = [
    { label: "Crop policy", value: prompt.crop_policy },
    { label: "Generation mode", value: prompt.generation_mode },
    { label: "Shape intent", value: prompt.shape_intent },
    { label: "Transition in", value: prompt.transition_in },
    { label: "Transition out", value: prompt.transition_out },
    { label: "Width", value: prompt.width },
    { label: "Height", value: prompt.height },
    { label: "Steps", value: prompt.steps },
  ].filter((f) => f.value != null && f.value !== "");

  return (
    <div className="min-w-0">
      {/* Scene style collapsible strip */}
      {prompt.style && (
        <CollapsibleSection
          title={styleLabel ? `SCENE STYLE — ${styleLabel}` : "SCENE STYLE"}
          preview={!styleLabel ? prompt.style : undefined}
          storageKey="direct.sceneStyle"
          defaultExpanded={false}
          className="mb-5 border-[2px] border-ink-black/8 bg-pulp-paper"
        >
          <div className="px-5 pb-5 pt-2 font-body text-[0.82rem] leading-6 text-ink-black/70">
            {prompt.style}
          </div>
        </CollapsibleSection>
      )}

      {/* 2×2 Summary grid: Shot / Characters / Setting / Lighting+Mood */}
      <div className="grid gap-5 md:grid-cols-2">
        <SummaryTile
          label="SHOT"
          value={prompt.composition ?? ""}
          onSave={(composition) => saveStructuredPatch({ composition })}
        />

        {/* Characters tile */}
        <div className="bg-surface-container px-5 py-5">
          <div className="font-meta text-[0.72rem] font-bold tracking-[0.2em] text-ink-black/45">
            CHARACTERS
          </div>
          {hasSubjects ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(prompt.subjects ?? []).map((s, i) => (
                <span key={i} className="flex items-center gap-1.5">
                  <span className="bg-ink-black/8 px-2.5 py-1 font-meta text-[0.68rem] font-bold leading-none tracking-[0.08em] text-ink-black">
                    {s.name || resolveName(s.character_id ?? "")}
                  </span>
                  {prompt.reference_image_paths.some((p) =>
                    p.includes(s.character_id ?? "__none__"),
                  ) && (
                    <span className="font-meta text-[0.58rem] tracking-[0.06em] text-archive-sage">
                      ref attached
                    </span>
                  )}
                </span>
              ))}
            </div>
          ) : (
            <div className="mt-2 text-[0.9rem] font-semibold text-ink-black/45">
              No characters in this panel
            </div>
          )}
        </div>

        <SummaryTile
          label="SETTING"
          value={prompt.setting ?? ""}
          onSave={(setting) => saveStructuredPatch({ setting })}
        />

        {/* Lighting + Mood combined tile */}
        <div className="bg-surface-container px-5 py-5">
          <div className="font-meta text-[0.72rem] font-bold tracking-[0.2em] text-ink-black/45">
            LIGHTING / MOOD
          </div>
          <div className="mt-2 text-[1.08rem] font-semibold leading-7 text-ink-black/84">
            <EditableText
              value={[prompt.lighting, prompt.mood].filter(Boolean).join(" · ") || "—"}
              onSave={(v) => {
                const [lighting, mood] = v.split("·").map((s) => s.trim());
                saveStructuredPatch({ lighting, mood });
              }}
              multiline
            />
          </div>
        </div>
      </div>

      {/* Assembled prompt */}
      <div className="mt-7">
        <div className="mb-3 flex items-center justify-between">
          <div className="font-meta text-[0.72rem] font-bold tracking-[0.2em] text-ink-black/45">
            ASSEMBLED PROMPT
          </div>
        </div>
        <EditableText
          value={prompt.full_prompt}
          onSave={(full_prompt) => onSave({ full_prompt })}
          multiline
          className="block min-h-[200px] whitespace-pre-wrap bg-ink-black px-7 py-7 font-meta text-[11px] font-medium leading-6 text-bristol"
          inputClassName="min-h-[200px] bg-ink-black text-bristol font-mono text-xs"
        />
      </div>

      {/* Technical parameters collapsible */}
      {techFields.length > 0 && (
        <div className="mt-4">
          <CollapsibleSection
            title="Technical Parameters"
            storageKey="direct.techParams"
            defaultExpanded={false}
          >
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 py-2 md:grid-cols-4">
              {techFields.map((f) => (
                <div key={f.label}>
                  <div className="font-meta text-[0.55rem] uppercase tracking-[0.14em] text-ink-black/40">
                    {f.label}
                  </div>
                  <div className="mt-0.5 font-body text-[0.78rem] font-medium text-ink-black/70">
                    {String(f.value)}
                  </div>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        </div>
      )}
    </div>
  );
}

function PanelTabStrip({
  prompts,
  activePanel,
  onSelect,
}: {
  prompts: ImagePrompt[];
  activePanel: number;
  onSelect: (n: number) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollBy = (delta: number) => {
    scrollRef.current?.scrollBy({ left: delta, behavior: "smooth" });
  };

  return (
    <div className="mb-7 flex items-center gap-0">
      {/* Prev arrow */}
      <button
        type="button"
        onClick={() => scrollBy(-200)}
        aria-label="Scroll tabs left"
        className="shrink-0 border-y border-l border-panel-line bg-pulp-paper px-2 py-3 text-ink-black/45 hover:bg-surface-container"
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M7 1L3 5L7 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>

      {/* Scrollable tab list */}
      <div
        ref={scrollRef}
        className="flex min-w-0 flex-1 overflow-x-auto"
        role="tablist"
        aria-label="Prompt panels"
        style={{ scrollbarWidth: "none" }}
      >
        {prompts.map((prompt) => {
          const isActive = prompt.panel_number === activePanel;
          return (
            <button
              key={`${prompt.scene_id}-${prompt.panel_number}`}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onSelect(prompt.panel_number)}
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

      {/* Next arrow */}
      <button
        type="button"
        onClick={() => scrollBy(200)}
        aria-label="Scroll tabs right"
        className="shrink-0 border-y border-r border-panel-line bg-pulp-paper px-2 py-3 text-ink-black/45 hover:bg-surface-container"
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M3 1L7 5L3 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>

      {/* Count chip */}
      <span className="ml-3 shrink-0 border border-ink-black/15 px-3 py-2 font-meta text-[0.68rem] font-bold tracking-[0.08em] text-ink-black/50">
        {prompts.findIndex((p) => p.panel_number === activePanel) + 1} / {prompts.length}
      </span>
    </div>
  );
}

export function DirectRoom() {
  const { name } = useParams<{ name: string }>();
  const { data: summaries, isLoading } = usePromptSummaries(name);
  const { data: status } = useProjectStatus(name);
  const { data: bible } = useStoryBible(name);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const selectedPanel = Number(searchParams.get("panel"));
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: prompts, isLoading: loadingPrompts } = usePromptsForScene(name, activeScene);
  const updatePrompt = useUpdatePrompt();
  const stageInfo = status?.stages?.direct;
  const stageStatus = stageInfo?.status ?? "pending";
  const resolveName = useCharacterName(name);
  const { isCompact, toggle } = useHeaderMode();
  const { data: stylesData } = useStyles(name);
  const activeStyle = stylesData?.active_index != null
    ? (stylesData.suggestions.find((s) => s.index === stylesData.active_index) ?? null)
    : null;
  const styleLabel = activeStyle?.label ?? undefined;

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
    setSearchParams({ scene: activeScene, panel: String(panelNumber) }, { replace: true });
  };

  const sceneTitleMap: Record<string, string> = {};
  if (bible) {
    for (const s of bible.scenes) {
      sceneTitleMap[s.id] = s.title;
    }
  }

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

  const rerunAction = <RerunStageAction project={name} stage="direct" label="Direct" />;

  return (
    <RoomShell>
      <div className="flex h-[calc(100vh-3rem)] min-h-0 flex-col gap-3 md:h-[calc(100vh-5rem)] md:gap-8">
        <RoomHeader
          kicker="DIRECT"
          title="IMAGE PROMPTS"
          lead="Compiled prompts with character and location refs baked in — the last human-readable artifact before image generation."
          actions={rerunAction}
          compact={isCompact}
          onToggle={toggle}
        />

        <section className="grid min-h-0 flex-1 grid-rows-[minmax(132px,30%)_minmax(0,1fr)] overflow-hidden border-[2px] border-ink-black bg-bristol xl:grid-cols-[200px_minmax(0,1fr)] xl:grid-rows-none">
          {summaries && (
            <div className="min-h-0 border-b-[2px] border-ink-black xl:border-b-0 xl:border-r-[2px]">
              <SceneSidebar
                items={summaries.map((s) => ({
                  id: s.scene_id,
                  label: s.scene_id.replace(/_/g, " ").toUpperCase(),
                  sceneTitle: sceneTitleMap[s.scene_id] ?? null,
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
                <PanelTabStrip
                  prompts={prompts}
                  activePanel={activePrompt.panel_number}
                  onSelect={selectPanel}
                />
                <DirectPromptDetail
                  prompt={activePrompt}
                  onSave={(patch) => handleSavePrompt(activePrompt, patch)}
                  resolveName={resolveName}
                  styleLabel={styleLabel}
                />
              </div>
            ) : (
              <div className="p-6">
                <StateBlock
                  title="SELECT A SCENE"
                  description="Select a scene to view image prompts."
                  icon="draft"
                />
              </div>
            )}
          </div>
        </section>
      </div>
    </RoomShell>
  );
}
