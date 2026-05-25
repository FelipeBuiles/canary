import { useState, useRef } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  useApproveStage,
  usePromptSummaries,
  usePromptsForScene,
  useRunPipeline,
  useStageEstimate,
  useUpdatePrompt,
  useProjectStatus,
  useStoryBible,
  useStyles,
} from "../../api/queries";
import { Button } from "../../components/ui/Button";
import { CollapsibleSection } from "../../components/ui/CollapsibleSection";
import { EditableText } from "../../components/ui/EditableText";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import {
  ConfirmDrawer,
  RerunStageAction,
  RoomHeader,
  RoomShell,
  SceneSidebar,
  StagePlaceholder,
  WarningOverrideDrawer,
} from "../../components/composites";
import { useCharacterName } from "../../hooks/useCharacterName";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { renderPanelPromptBody } from "../../lib/prompting";
import { detectAllWarnings } from "../../lib/promptWarnings";
import { usePipelineStore } from "../../store/pipeline";
import type { ImagePrompt, PromptWarning } from "../../types/api";

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

      {/* Assembled prompt — collapsed by default */}
      <div className="mt-7">
        {prompt.distilled_prompt && (
          <CollapsibleSection
            title="DISTILLED PROMPT"
            storageKey="direct.distilledPrompt"
            defaultExpanded
          >
            <p className="whitespace-pre-wrap bg-bristol px-5 py-5 font-body text-[0.92rem] leading-7 text-ink-black">
              {prompt.distilled_prompt}
            </p>
          </CollapsibleSection>
        )}
        <CollapsibleSection
          title="ASSEMBLED PROMPT"
          storageKey="direct.assembledPrompt"
          defaultExpanded={false}
        >
          <div className="pt-2">
            <EditableText
              value={prompt.full_prompt}
              onSave={(full_prompt) => onSave({ full_prompt })}
              multiline
              className="block min-h-[200px] whitespace-pre-wrap bg-ink-black px-7 py-7 font-meta text-[11px] font-medium leading-6 text-bristol"
              inputClassName="min-h-[200px] bg-ink-black text-bristol font-mono text-xs"
            />
          </div>
        </CollapsibleSection>
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
  warningsByPanel,
}: {
  prompts: ImagePrompt[];
  activePanel: number;
  onSelect: (n: number) => void;
  warningsByPanel: Map<number, PromptWarning[]>;
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
          const panelWarnings = warningsByPanel.get(prompt.panel_number) ?? [];
          const hasWarnings = panelWarnings.length > 0;
          return (
            <button
              key={`${prompt.scene_id}-${prompt.panel_number}`}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onSelect(prompt.panel_number)}
              className={
                isActive
                  ? "relative shrink-0 bg-ink-black px-7 py-3 font-meta text-[0.82rem] font-bold tracking-[0.12em] text-pulp-paper"
                  : "relative shrink-0 border-y border-r border-panel-line bg-pulp-paper px-7 py-3 font-meta text-[0.82rem] font-bold tracking-[0.12em] text-ink-black/62 hover:bg-surface-container"
              }
            >
              Panel {String(prompt.panel_number).padStart(2, "0")}
              {hasWarnings && (
                <span
                  className="absolute right-1.5 top-1.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-[var(--color-warn-orange)] font-meta text-[0.5rem] font-bold text-white"
                  aria-label={`${panelWarnings.length} warning${panelWarnings.length !== 1 ? "s" : ""}`}
                >
                  {panelWarnings.length}
                </span>
              )}
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

// ── DirectApproveAction ───────────────────────────────────────────────────────

function DirectApproveAction({
  project,
  allWarnings,
}: {
  project: string;
  allWarnings: PromptWarning[];
}) {
  const { data: status } = useProjectStatus(project);
  const stageStatus = status?.stages?.direct?.status;
  const isAwaiting = stageStatus === "awaiting_review";

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [warningOpen, setWarningOpen] = useState(false);

  const { data: estimate } = useStageEstimate(project, "draw", confirmOpen || warningOpen);
  const approveStage = useApproveStage();
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((s) => s.connect);
  const clearEvents = usePipelineStore((s) => s.clearEvents);

  const busy =
    approveStage.isPending || runPipeline.isPending || (status?.is_running ?? false);

  const hasWarnings = allWarnings.length > 0;
  const estimateCredits = estimate?.estimate_credits ?? 0;

  const ctaLabel = hasWarnings
    ? `Review ${allWarnings.length} Warning${allWarnings.length !== 1 ? "s" : ""} Before Approving`
    : estimateCredits > 0
    ? `Approve Prompts & Run Generate Panels · Est. ${estimateCredits.toLocaleString()} credits`
    : "Approve Prompts & Run Generate Panels";

  function doApproveAndRun() {
    clearEvents();
    approveStage.mutate(
      { project, stage: "direct" },
      {
        onSuccess: () => {
          runPipeline.mutate(
            { project, stage: "draw" },
            {
              onSuccess: () => connect(project),
              onError: (err) =>
                maybeShowInsufficientCredits(err, {
                  actionLabel: "Run DRAW",
                  onRetry: doApproveAndRun,
                }),
            },
          );
        },
      },
    );
  }

  function handleClick() {
    if (hasWarnings) {
      setWarningOpen(true);
    } else {
      setConfirmOpen(true);
    }
  }

  if (!isAwaiting) return null;

  return (
    <>
      <Button
        size="sm"
        variant={hasWarnings ? "outline" : "primary"}
        disabled={busy}
        onClick={handleClick}
        style={hasWarnings ? { borderColor: "var(--color-warn-orange)", color: "var(--color-warn-orange)" } : undefined}
      >
        {busy ? "Working…" : ctaLabel}
      </Button>

      <ConfirmDrawer
        open={confirmOpen}
        title="Run Generate Panels?"
        body="Approving prompts is free. Generating panels will reserve credits for the draw stage. Unused reserved credits are released after the stage completes."
        cost={estimate}
        confirmLabel="Approve & Run Generate Panels"
        onConfirm={() => { setConfirmOpen(false); doApproveAndRun(); }}
        onClose={() => setConfirmOpen(false)}
        busy={busy}
      />

      <WarningOverrideDrawer
        open={warningOpen}
        warnings={allWarnings}
        cost={estimate}
        onConfirm={() => { setWarningOpen(false); doApproveAndRun(); }}
        onClose={() => setWarningOpen(false)}
        busy={busy}
      />
    </>
  );
}

// ── DirectRoom (main) ─────────────────────────────────────────────────────────

export function DirectRoom() {
  const { id } = useParams<{ id: string }>();
  const { data: summaries, isLoading } = usePromptSummaries(id);
  const { data: status } = useProjectStatus(id);
  const { data: bible } = useStoryBible(id);
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedScene = searchParams.get("scene");
  const selectedPanel = Number(searchParams.get("panel"));
  const activeScene = selectedScene ?? summaries?.[0]?.scene_id;
  const { data: prompts, isLoading: loadingPrompts } = usePromptsForScene(id, activeScene);
  const updatePrompt = useUpdatePrompt();
  const stageInfo = status?.stages?.direct;
  const stageStatus = stageInfo?.status ?? "pending";
  const resolveName = useCharacterName(id);
  const { isCompact, toggle } = useHeaderMode();
  const { data: stylesData } = useStyles(id);
  const activeStyle = stylesData?.active_index != null
    ? (stylesData.suggestions.find((s) => s.index === stylesData.active_index) ?? null)
    : null;
  const styleLabel = activeStyle?.label ?? undefined;

  const activePrompt =
    prompts?.find((prompt) => prompt.panel_number === selectedPanel) ??
    prompts?.[0] ??
    null;

  // Compute warnings for active scene's prompts
  const sceneWarnings = prompts ? detectAllWarnings(prompts) : [];
  const warningsByPanel = new Map<number, PromptWarning[]>();
  for (const w of sceneWarnings) {
    const list = warningsByPanel.get(w.panel_number) ?? [];
    list.push(w);
    warningsByPanel.set(w.panel_number, list);
  }

  const handleSavePrompt = (prompt: ImagePrompt, patch: Partial<ImagePrompt>) => {
    if (!id || !activeScene) return;
    updatePrompt.mutate({
      project: id,
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
    return (
      <RoomShell
        isLoading
        loadingText="LOADING IMAGE PROMPTS…"
        loadingStage="direct"
        loadingStageStatus={stageStatus}
        loadingStageItemsDone={stageInfo?.items_done}
        loadingStageItemsTotal={stageInfo?.items_total}
      />
    );
  }

  if (!summaries?.length || !id) {
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

  const rerunAction = <RerunStageAction project={id} stage="direct" label="Direct" />;
  const approveAction = id ? <DirectApproveAction project={id} allWarnings={sceneWarnings} /> : null;

  return (
    <RoomShell fullHeight>
      <div className="flex h-full min-h-0 flex-col gap-3 md:gap-8">
        <RoomHeader
          kicker="DIRECT"
          title="IMAGE PROMPTS"
          lead={
            <span>
              Compiled prompts with character and location refs baked in — the last human-readable artifact before image generation.
              {sceneWarnings.length > 0 && (
                <span
                  className="ml-3 font-meta text-[0.65rem] tracking-[0.08em]"
                  style={{ color: "var(--color-warn-orange)" }}
                >
                  ⚠ {sceneWarnings.length} prompt{sceneWarnings.length !== 1 ? "s" : ""} have warnings — review before approving
                </span>
              )}
            </span>
          }
          actions={
            <div className="flex items-center gap-2">
              {approveAction}
              {rerunAction}
            </div>
          }
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
                  warningsByPanel={warningsByPanel}
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
