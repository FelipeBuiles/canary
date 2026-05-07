import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  useLayoutPlan,
  usePanelsForScene,
  usePanelSummaries,
  useProjectStatus,
  useRunPipeline,
  useStageEstimate,
  useStoryBible,
  useUpdatePanel,
} from "../../api/queries";
import { Button } from "../../components/ui/Button";
import { FieldLabel, SelectField, TextAreaField, TextField } from "../../components/ui/Field";
import { Icon } from "../../components/ui/Icon";
import { RoomHeader } from "../../components/ui/RoomHeader";
import { RoomShell } from "../../components/ui/RoomShell";
import { SceneSidebar } from "../../components/ui/SceneSidebar";
import { ShotDiagram } from "../../components/ui/ShotDiagram";
import { StagePlaceholder } from "../../components/ui/StagePlaceholder";
import { LoadingBlock, StateBlock } from "../../components/ui/StateBlock";
import { cn } from "../../lib/cn";
import { getShotPlanAction, getShotPlanSubStatus } from "../../lib/shotPlan";
import { useCharacterName } from "../../hooks/useCharacterName";
import { useHeaderMode } from "../../hooks/useHeaderMode";
import { usePipelineStore } from "../../store/pipeline";
import type {
  DialogueLine,
  LayoutPlan,
  PanelBreakdown,
  PlannedPanel,
  PlannedPage,
  Scene,
} from "../../types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type ShotPlanView = "outline" | "board" | "layout";
const VALID_VIEWS = new Set<ShotPlanView>(["outline", "board", "layout"]);

// ── Helpers ───────────────────────────────────────────────────────────────────

function shotLabel(value: string) {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
    .join(" ");
}

function normalizeLabel(value: string | null | undefined) {
  return value ? value.replace(/[-_]/g, " ") : "—";
}

const IMPORTANCE_BADGE: Record<string, string> = {
  accent: "border border-narrator-gold/50 bg-narrator-gold/15 text-ink-black",
  splash: "border border-hero-red/30 bg-hero-red/10 text-hero-red",
  silent: "border border-archive-sage/40 bg-archive-sage/15 text-ink-black",
};
function importanceCls(imp: string) {
  return (
    IMPORTANCE_BADGE[imp.toLowerCase()] ??
    "border border-ink-black/15 bg-ink-black/6 text-ink-black/55"
  );
}

const SHOT_TYPE_OPTIONS = [
  "extreme-wide",
  "wide",
  "medium",
  "close-up",
  "extreme-close-up",
  "two-shot",
  "over-shoulder",
  "insert",
];
// ── ShotPlanActionButton ──────────────────────────────────────────────────────

function ShotPlanActionButton({ project }: { project: string }) {
  const { data: status } = useProjectStatus(project);
  const action = getShotPlanAction(status);
  const estimateStage = action.kind === "none" ? undefined : action.estimateStage;
  const { data: estimate } = useStageEstimate(project, estimateStage);
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);

  const busy = runPipeline.isPending || status?.is_running;
  const estimateCredits = estimate?.estimate_credits;
  const label =
    estimateCredits && estimateCredits > 0
      ? `${action.label} · Est. ${estimateCredits.toLocaleString()} credits`
      : action.label;

  function run(stage: "plan" | "storyboard", rerun = false) {
    clearEvents();
    runPipeline.mutate({ project, stage, rerun }, { onSuccess: () => connect(project) });
  }

  function handleClick() {
    if (action.kind === "none") return;
    if (action.kind === "run") { run(action.backendStage); return; }
    if (action.kind === "rerun") { run(action.backendStage, true); return; }
  }

  return (
    <Button
      size="sm"
      variant={action.kind === "none" ? "outline" : "primary"}
      disabled={action.kind === "none" || busy}
      onClick={handleClick}
    >
      {busy ? "Working…" : label}
    </Button>
  );
}

// ── TabButton ─────────────────────────────────────────────────────────────────

function TabButton({
  view,
  activeView,
  onSelect,
  children,
}: {
  view: ShotPlanView;
  activeView: ShotPlanView;
  onSelect: (v: ShotPlanView) => void;
  children: string;
}) {
  const active = view === activeView;
  return (
    <button
      type="button"
      onClick={() => onSelect(view)}
      className={cn(
        "border-b-[3px] px-3 pb-2 pt-1 font-meta text-[0.68rem] font-bold tracking-[0.18em] uppercase transition-colors",
        active
          ? "border-hero-red text-hero-red"
          : "border-transparent text-ink-black/45 hover:text-ink-black/70",
      )}
    >
      {children}
    </button>
  );
}

// ── OutlineTab ────────────────────────────────────────────────────────────────

function OutlineTab({
  plan,
  scenes,
  boardCounts,
  resolveName,
}: {
  plan: LayoutPlan;
  scenes: Scene[];
  boardCounts: Record<string, number>;
  resolveName: (id: string) => string;
}) {
  const panelsByScene = useMemo(() => {
    const g: Record<string, PlannedPanel[]> = {};
    for (const p of plan.planned_panels) {
      (g[p.scene_id] ??= []).push(p);
    }
    return g;
  }, [plan.planned_panels]);

  const narrationByScene = useMemo(() => {
    const g: Record<string, number> = {};
    for (const d of plan.narration_decisions) {
      if (d.decision === "rendered") g[d.scene_id] = (g[d.scene_id] ?? 0) + 1;
    }
    return g;
  }, [plan.narration_decisions]);

  const sceneMap = new Map(scenes.map((s) => [s.id, s]));
  const sceneIds = [...new Set(plan.planned_panels.map((p) => p.scene_id))];

  return (
    <div className="h-full overflow-y-auto p-5 md:p-7">
      <div className="space-y-3">
        {sceneIds.map((sceneId, idx) => {
          const scene = sceneMap.get(sceneId);
          const panels = panelsByScene[sceneId] ?? [];
          const narrationCount = narrationByScene[sceneId] ?? 0;
          const hasBoardData = (boardCounts[sceneId] ?? 0) > 0;
          const accentCount = panels.filter((p) => p.importance !== "standard").length;

          // Shot type frequency
          const shotFreq: Record<string, number> = {};
          for (const p of panels) {
            const k = p.shot_type ?? "unknown";
            shotFreq[k] = (shotFreq[k] ?? 0) + 1;
          }
          const topShots = Object.entries(shotFreq)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5);

          return (
            <article
              key={sceneId}
              className="border-[2px] border-ink-black/10 bg-pulp-paper hover:border-ink-black/20 transition-colors"
            >
              {/* Scene header */}
              <div className="flex items-start justify-between gap-4 border-b border-ink-black/8 px-5 py-4">
                <div className="flex items-start gap-4">
                  <span className="mt-0.5 shrink-0 border-[2px] border-ink-black/15 px-2 py-1 font-meta text-[0.6rem] font-bold tracking-[0.14em] text-ink-black/40">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <div className="font-meta text-[0.58rem] font-bold tracking-[0.18em] text-hero-red">
                      {sceneId.replace(/_/g, " ").toUpperCase()}
                    </div>
                    <h2 className="mt-0.5 font-display text-[1.4rem] font-black uppercase leading-none tracking-[-0.04em] text-ink-black">
                      {scene?.title ?? "Untitled Scene"}
                    </h2>
                  </div>
                </div>
                <span
                  className={cn(
                    "shrink-0 px-2 py-1 font-meta text-[0.58rem] font-bold tracking-[0.1em]",
                    hasBoardData
                      ? "border border-archive-sage/40 bg-archive-sage/15 text-ink-black"
                      : "border border-ink-black/15 bg-ink-black/6 text-ink-black/40",
                  )}
                >
                  {hasBoardData ? "BOARD READY" : "BOARD PENDING"}
                </span>
              </div>

              {/* Location + cast */}
              <div className="grid grid-cols-2 gap-0 divide-x divide-ink-black/8 border-b border-ink-black/8">
                <div className="px-5 py-3">
                  <div className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.16em] text-ink-black/35">
                    Location
                  </div>
                  <p className="mt-1 font-body text-[0.82rem] font-medium text-ink-black/75">
                    {scene?.location_id
                      ? scene.location_id.replace(/_/g, " ")
                      : <span className="text-ink-black/35 italic">Not assigned</span>}
                  </p>
                </div>
                <div className="px-5 py-3">
                  <div className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.16em] text-ink-black/35">
                    Cast
                  </div>
                  <p className="mt-1 font-body text-[0.82rem] font-medium text-ink-black/75">
                    {scene?.character_ids.length
                      ? scene.character_ids.map(resolveName).join(", ")
                      : <span className="text-ink-black/35 italic">No listed characters</span>}
                  </p>
                </div>
              </div>

              {/* Stats + shot breakdown */}
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3">
                <StatChip label="Panels" value={String(panels.length)} />
                <StatChip label="Captions" value={String(narrationCount)} />
                {accentCount > 0 && (
                  <StatChip label="Emphasis" value={String(accentCount)} accent />
                )}
                {topShots.length > 0 && (
                  <div className="flex items-center gap-1.5">
                    {topShots.map(([type, count]) => (
                      <span
                        key={type}
                        className="flex items-center gap-1 border border-ink-black/12 bg-bristol px-1.5 py-0.5 font-meta text-[0.58rem] tracking-[0.08em] text-ink-black/55"
                      >
                        <ShotDiagram shot={type} size={14} className="[&>span]:hidden" />
                        {count}×
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function StatChip({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span
        className={cn(
          "font-display text-[1.1rem] font-black leading-none tracking-[-0.03em]",
          accent ? "text-narrator-gold" : "text-ink-black",
        )}
      >
        {value}
      </span>
      <span className="font-meta text-[0.6rem] tracking-[0.1em] text-ink-black/40">{label}</span>
    </span>
  );
}

// ── Board: PanelCard ──────────────────────────────────────────────────────────

function PanelCard({
  panel,
  planned,
  isSelected,
  onSelect,
  resolveName,
}: {
  panel: PanelBreakdown;
  planned: PlannedPanel | undefined;
  isSelected: boolean;
  onSelect: () => void;
  resolveName: (id: string) => string;
}) {
  const importance = planned?.importance ?? "standard";

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group w-full border-[2px] bg-pulp-paper p-4 text-left transition-all duration-150",
        isSelected
          ? "border-hero-red ring-1 ring-hero-red/20"
          : "border-ink-black/10 hover:border-ink-black/25",
      )}
    >
      {/* Row 1: panel ID + shot + importance */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <ShotDiagram shot={panel.shot_type} size={22} className="shrink-0 [&>span]:hidden" />
          <div>
            <span className="font-meta text-[0.62rem] font-bold tracking-[0.16em] text-ink-black/40">
              P{String(panel.panel_number).padStart(2, "0")}
            </span>
            <div className="font-meta text-[0.72rem] font-bold tracking-[0.08em] text-ink-black leading-tight">
              {shotLabel(panel.shot_type)}
              {panel.camera_angle && (
                <span className="ml-1.5 font-normal text-ink-black/40">
                  · {panel.camera_angle}
                </span>
              )}
            </div>
          </div>
        </div>
        {importance !== "standard" && (
          <span
            className={cn(
              "shrink-0 px-1.5 py-0.5 font-meta text-[0.55rem] font-bold uppercase tracking-[0.1em]",
              importanceCls(importance),
            )}
          >
            {importance}
          </span>
        )}
      </div>

      {/* Background description */}
      <p className="mt-2.5 line-clamp-3 font-body text-[0.82rem] leading-[1.45] text-ink-black/65">
        {panel.background_description}
      </p>

      {/* Characters */}
      {panel.characters_present.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {panel.characters_present.map((cid) => (
            <span
              key={cid}
              className="bg-ink-black/6 px-2 py-0.5 font-meta text-[0.6rem] tracking-[0.06em] text-ink-black/65"
            >
              {resolveName(cid)}
            </span>
          ))}
        </div>
      )}

      {/* First dialogue line */}
      {panel.dialogue.length > 0 && (
        <div className="mt-2.5 flex items-start gap-2">
          <span className="mt-0.5 h-full w-[2px] shrink-0 self-stretch bg-hero-red/35" />
          <p className="min-w-0 line-clamp-2 font-body text-[0.78rem] italic leading-[1.4] text-ink-black/60">
            &ldquo;{panel.dialogue[0].text}&rdquo;
            {panel.dialogue.length > 1 && (
              <span className="not-italic text-ink-black/35"> +{panel.dialogue.length - 1}</span>
            )}
          </p>
        </div>
      )}

      {/* Lighting + mood footer */}
      {(panel.lighting || panel.mood) && (
        <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1 border-t border-ink-black/6 pt-2.5">
          {panel.lighting && (
            <span className="font-meta text-[0.6rem] tracking-[0.05em] text-ink-black/40">
              <span className="mr-1 text-ink-black/25">LT</span>
              {panel.lighting}
            </span>
          )}
          {panel.mood && (
            <span className="font-meta text-[0.6rem] tracking-[0.05em] text-ink-black/40">
              <span className="mr-1 text-ink-black/25">MD</span>
              {panel.mood}
            </span>
          )}
        </div>
      )}
    </button>
  );
}

// ── Board: PanelDetailPanel ───────────────────────────────────────────────────

function PanelDetailPanel({
  panel,
  project,
  resolveName,
  onClose,
}: {
  panel: PanelBreakdown;
  project: string;
  resolveName: (id: string) => string;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<Partial<PanelBreakdown>>({});
  const updatePanel = useUpdatePanel();

  // Reset draft whenever the selected panel changes
  useEffect(() => {
    setDraft({});
  }, [panel.scene_id, panel.panel_number]);

  const merged = { ...panel, ...draft };
  const isDirty = Object.keys(draft).length > 0;

  function set<K extends keyof PanelBreakdown>(key: K, value: PanelBreakdown[K]) {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  function save() {
    updatePanel.mutate(
      { project, sceneId: panel.scene_id, data: { ...panel, ...draft } },
      { onSuccess: () => setDraft({}) },
    );
  }

  return (
    <aside className="flex h-full min-h-0 flex-col border-l-[2px] border-ink-black bg-pulp-paper">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b-[2px] border-ink-black px-4 py-3">
        <div>
          <div className="font-meta text-[0.58rem] tracking-[0.18em] text-ink-black/40">
            PANEL DETAILS
          </div>
          <div className="font-meta text-[0.9rem] font-bold tracking-[0.06em] text-ink-black">
            P_{String(panel.panel_number).padStart(3, "0")}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center text-ink-black/40 transition-colors hover:text-ink-black"
          aria-label="Close panel details"
        >
          <Icon name="x" size={14} />
        </button>
      </div>

      {/* Scrollable form */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="space-y-4">
          <div>
            <FieldLabel htmlFor="dp-shot">Shot Type</FieldLabel>
            <SelectField
              id="dp-shot"
              value={merged.shot_type}
              onChange={(e) => set("shot_type", e.target.value)}
            >
              {SHOT_TYPE_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {shotLabel(o)}
                </option>
              ))}
              {/* Keep the raw value if it doesn't match a known option */}
              {!SHOT_TYPE_OPTIONS.includes(merged.shot_type) && (
                <option value={merged.shot_type}>{shotLabel(merged.shot_type)}</option>
              )}
            </SelectField>
          </div>

          <div>
            <FieldLabel htmlFor="dp-angle">Camera Angle</FieldLabel>
            <TextField
              id="dp-angle"
              value={merged.camera_angle}
              placeholder="e.g. eye level, slightly high"
              onChange={(e) => set("camera_angle", e.target.value)}
            />
          </div>

          <div>
            <FieldLabel htmlFor="dp-bg">Background</FieldLabel>
            <TextAreaField
              id="dp-bg"
              value={merged.background_description}
              onChange={(e) => set("background_description", e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel htmlFor="dp-lt">Lighting</FieldLabel>
              <TextField
                id="dp-lt"
                value={merged.lighting}
                onChange={(e) => set("lighting", e.target.value)}
              />
            </div>
            <div>
              <FieldLabel htmlFor="dp-md">Mood</FieldLabel>
              <TextField
                id="dp-md"
                value={merged.mood}
                onChange={(e) => set("mood", e.target.value)}
              />
            </div>
          </div>

          {/* Characters — display only */}
          {panel.characters_present.length > 0 && (
            <div>
              <FieldLabel>Characters</FieldLabel>
              <div className="flex flex-wrap gap-1.5 pt-1">
                {panel.characters_present.map((cid) => (
                  <span
                    key={cid}
                    className="border border-ink-black/15 bg-bristol px-2 py-1 font-meta text-[0.65rem] tracking-[0.06em] text-ink-black/75"
                  >
                    {resolveName(cid)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Dialogue — display only */}
          {panel.dialogue.length > 0 && (
            <div>
              <FieldLabel>Dialogue</FieldLabel>
              <div className="space-y-2 pt-1">
                {panel.dialogue.map((d, i) => (
                  <DialogueBlock
                    key={`${d.character_id ?? "narration"}-${i}`}
                    line={d}
                    resolveName={resolveName}
                  />
                ))}
              </div>
            </div>
          )}

          {/* SFX */}
          {panel.sfx.length > 0 && (
            <div>
              <FieldLabel>SFX</FieldLabel>
              <p className="mt-1 font-body text-[0.82rem] font-bold text-ink-black/70">
                {panel.sfx.map((s) => s.text).join(" · ")}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Save / discard */}
      <div
        className={cn(
          "shrink-0 border-t-[2px] border-ink-black px-4 py-3 transition-all",
          isDirty ? "bg-pulp-paper" : "bg-bristol/60",
        )}
      >
        {isDirty ? (
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={save} disabled={updatePanel.isPending}>
              {updatePanel.isPending ? "Saving…" : "Save Panel"}
            </Button>
            <button
              type="button"
              onClick={() => setDraft({})}
              className="font-meta text-[0.65rem] tracking-[0.1em] text-ink-black/50 transition-colors hover:text-ink-black"
            >
              Discard
            </button>
          </div>
        ) : (
          <p className="font-meta text-[0.62rem] tracking-[0.06em] text-ink-black/35">
            Click any field above to edit
          </p>
        )}
      </div>
    </aside>
  );
}

function DialogueBlock({
  line,
  resolveName,
}: {
  line: DialogueLine;
  resolveName: (id: string) => string;
}) {
  return (
    <div className="border-l-[2px] border-hero-red/35 bg-bristol/50 py-2 pl-3 pr-2">
      {line.character_id && (
        <div className="mb-1 font-meta text-[0.58rem] font-bold uppercase tracking-[0.16em] text-hero-red/70">
          {resolveName(line.character_id)}
        </div>
      )}
      <p className="font-body text-[0.8rem] italic leading-[1.4] text-ink-black/72">
        &ldquo;{line.text}&rdquo;
      </p>
    </div>
  );
}

// ── BoardTab ──────────────────────────────────────────────────────────────────

function BoardTab({
  project,
  plan,
  sceneTitleMap,
  resolveName,
}: {
  project: string;
  plan: LayoutPlan | undefined;
  sceneTitleMap: Record<string, string>;
  resolveName: (id: string) => string;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: summaries, isLoading } = usePanelSummaries(project);
  const selectedSceneParam = searchParams.get("scene");
  const activeScene = selectedSceneParam ?? summaries?.[0]?.scene_id;
  const { data: panels, isLoading: loadingPanels } = usePanelsForScene(project, activeScene);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  // Cross-reference layout plan for importance / shape
  const plannedMap = useMemo(() => {
    const m = new Map<string, PlannedPanel>();
    for (const p of plan?.planned_panels ?? []) {
      m.set(`${p.scene_id}-${p.panel_number}`, p);
    }
    return m;
  }, [plan?.planned_panels]);

  const selectedPanel = useMemo(
    () => panels?.find((p) => `${p.scene_id}-${p.panel_number}` === selectedKey) ?? null,
    [panels, selectedKey],
  );

  // Clear selection when scene changes
  useEffect(() => {
    setSelectedKey(null);
  }, [activeScene]);

  if (isLoading) {
    return <div className="p-6"><LoadingBlock label="LOADING BOARD…" /></div>;
  }

  if (!summaries?.length) {
    return (
      <div className="p-6">
        <StateBlock
          title="BOARD PENDING"
          description="Build the board after the layout review is approved."
          icon="draft"
        />
      </div>
    );
  }

  return (
    <section
      className={cn(
        "grid h-full min-h-0 overflow-hidden transition-[grid-template-columns] duration-200",
        selectedPanel
          ? "grid-cols-[220px_minmax(0,1fr)_296px] xl:grid-cols-[240px_minmax(0,1fr)_316px]"
          : "grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)]",
      )}
    >
      {/* Scene sidebar */}
      <div className="min-h-0 border-r-[2px] border-ink-black">
        <SceneSidebar
          items={summaries.map((s) => ({
            id: s.scene_id,
            label: s.scene_id.replace(/_/g, " ").toUpperCase(),
            sceneTitle: sceneTitleMap[s.scene_id] ?? null,
            count: `${s.panel_count} panels`,
          }))}
          activeId={activeScene ?? ""}
          onSelect={(scene) => {
            const next = new URLSearchParams(searchParams);
            next.set("scene", scene);
            next.set("view", "board");
            setSearchParams(next, { replace: true });
          }}
        />
      </div>

      {/* Panel grid */}
      <div className="min-h-0 min-w-0 overflow-hidden border-r-[2px] border-ink-black/10">
        {loadingPanels ? (
          <div className="p-6"><LoadingBlock label="LOADING…" /></div>
        ) : panels?.length ? (
          <div className="h-full min-h-0 overflow-y-auto p-4 md:p-5">
            {/* Scene label */}
            {activeScene && (
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <div className="font-meta text-[0.6rem] font-bold tracking-[0.18em] text-hero-red">
                    {activeScene.replace(/_/g, " ").toUpperCase()}
                  </div>
                  {sceneTitleMap[activeScene] && (
                    <div className="mt-0.5 font-display text-[1.1rem] font-black uppercase tracking-[-0.03em] text-ink-black">
                      {sceneTitleMap[activeScene]}
                    </div>
                  )}
                </div>
                <span className="font-meta text-[0.6rem] tracking-[0.1em] text-ink-black/35">
                  {panels.length} panels
                </span>
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
              {panels.map((panel) => {
                const key = `${panel.scene_id}-${panel.panel_number}`;
                return (
                  <PanelCard
                    key={key}
                    panel={panel}
                    planned={plannedMap.get(key)}
                    isSelected={selectedKey === key}
                    onSelect={() => setSelectedKey(selectedKey === key ? null : key)}
                    resolveName={resolveName}
                  />
                );
              })}
            </div>
          </div>
        ) : (
          <div className="p-6">
            <StateBlock
              title="SELECT A SCENE"
              description="Select a scene to view panel breakdowns."
              icon="draft"
            />
          </div>
        )}
      </div>

      {/* Detail panel */}
      {selectedPanel && (
        <PanelDetailPanel
          panel={selectedPanel}
          project={project}
          resolveName={resolveName}
          onClose={() => setSelectedKey(null)}
        />
      )}
    </section>
  );
}

// ── LayoutTab ─────────────────────────────────────────────────────────────────

function LayoutTab({ plan }: { plan: LayoutPlan }) {
  const panelMap = new Map(plan.planned_panels.map((p) => [p.panel_id, p]));

  return (
    <div className="h-full overflow-y-auto p-5 md:p-7">
      {/* Page columns — horizontal scroll on small screens */}
      <div className="flex gap-4 overflow-x-auto pb-4">
        {plan.planned_pages.map((page: PlannedPage) => {
          const panels = page.panel_ids.map((id) => panelMap.get(id)).filter(Boolean) as PlannedPanel[];

          return (
            <article
              key={page.page_id}
              className="w-[180px] shrink-0 border-[2px] border-ink-black bg-pulp-paper"
            >
              {/* Page header */}
              <div className="border-b-[2px] border-ink-black px-3 py-2.5">
                <div className="font-meta text-[0.58rem] font-bold tracking-[0.18em] text-hero-red">
                  PAGE {String(page.page_number).padStart(2, "0")}
                </div>
                <div className="mt-0.5 font-body text-[0.78rem] font-semibold capitalize text-ink-black">
                  {normalizeLabel(page.page_rhythm_role)}
                </div>
                <div className="mt-0.5 font-meta text-[0.58rem] tracking-[0.08em] text-ink-black/40">
                  {panels.length} panels
                </div>
              </div>

              {/* Panel blocks */}
              <div className="divide-y divide-ink-black/8 p-2">
                {panels.map((panel, i) => {
                  const imp = panel.importance ?? "standard";
                  return (
                    <div
                      key={panel.panel_id}
                      className={cn(
                        "flex items-start gap-2 px-2 py-1.5 transition-colors",
                        importanceCls(imp),
                        i === 0 ? "" : "mt-0",
                      )}
                    >
                      <ShotDiagram
                        shot={panel.shot_type ?? ""}
                        size={16}
                        className="mt-0.5 shrink-0 [&>span]:hidden"
                      />
                      <div className="min-w-0">
                        <div className="font-meta text-[0.58rem] font-bold leading-none tracking-[0.12em] text-ink-black/70">
                          P{String(panel.panel_number).padStart(2, "0")}
                        </div>
                        <div className="mt-0.5 truncate font-meta text-[0.56rem] tracking-[0.04em] text-ink-black/45">
                          {shotLabel(panel.shot_type ?? "—")}
                          {imp !== "standard" && (
                            <span className="ml-1 font-bold text-hero-red/60">·{imp[0].toUpperCase()}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </article>
          );
        })}
      </div>

      {/* Flat panel list below for detail */}
      <div className="mt-7">
        <div className="mb-3 font-meta text-[0.62rem] font-bold tracking-[0.2em] text-ink-black/35">
          ALL PANELS
        </div>
        <div className="overflow-hidden border-[2px] border-ink-black/10">
          {plan.planned_pages.flatMap((page) =>
            page.panel_ids.map((panelId, panelIdx) => {
              const panel = panelMap.get(panelId);
              if (!panel) return null;
              return (
                <div
                  key={panelId}
                  className="grid items-center gap-3 border-b border-ink-black/8 bg-pulp-paper px-4 py-2.5 last:border-b-0 md:grid-cols-[56px_64px_1fr_100px_100px_80px]"
                >
                  <span className="font-meta text-[0.6rem] font-bold tracking-[0.14em] text-ink-black/40">
                    Pg {String(page.page_number).padStart(2, "0")} · {panelIdx + 1}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <ShotDiagram
                      shot={panel.shot_type ?? ""}
                      size={18}
                      className="shrink-0 [&>span]:hidden"
                    />
                    <span className="font-meta text-[0.62rem] font-bold tracking-[0.08em] text-ink-black">
                      P{String(panel.panel_number).padStart(2, "0")}
                    </span>
                  </div>
                  <p className="line-clamp-1 font-body text-[0.8rem] text-ink-black/65">
                    {panel.background_description}
                  </p>
                  <span className="font-meta text-[0.6rem] tracking-[0.06em] text-ink-black/45 hidden md:block">
                    {normalizeLabel(panel.importance)}
                  </span>
                  <span className="font-meta text-[0.6rem] tracking-[0.06em] text-ink-black/45 hidden md:block">
                    {normalizeLabel(panel.shape_intent)}
                  </span>
                  <span className="font-meta text-[0.6rem] tracking-[0.06em] text-ink-black/45 hidden md:block">
                    {panel.scene_id.replace(/_/g, " ")}
                  </span>
                </div>
              );
            }),
          )}
        </div>
      </div>
    </div>
  );
}

// ── ShotPlanRoom (main) ───────────────────────────────────────────────────────

export function ShotPlanRoom() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: plan, isLoading: loadingPlan } = useLayoutPlan(id);
  const { data: summaries } = usePanelSummaries(id);
  const { data: status } = useProjectStatus(id);
  const { data: bible } = useStoryBible(id);
  const resolveName = useCharacterName(id);
  const { isCompact, toggle } = useHeaderMode();

  const subStatus = getShotPlanSubStatus(status);
  const defaultView: ShotPlanView = summaries?.length ? "board" : "outline";
  const requestedView = searchParams.get("view") as ShotPlanView | null;
  const activeView =
    requestedView && VALID_VIEWS.has(requestedView) ? requestedView : defaultView;

  const sceneTitleMap = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of bible?.scenes ?? []) m[s.id] = s.title;
    return m;
  }, [bible?.scenes]);

  const boardCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const s of summaries ?? []) c[s.scene_id] = s.panel_count;
    return c;
  }, [summaries]);

  function setView(view: ShotPlanView) {
    const next = new URLSearchParams(searchParams);
    next.set("view", view);
    setSearchParams(next, { replace: true });
  }

  if (loadingPlan || (!plan && subStatus.status !== "pending")) {
    return <RoomShell isLoading loadingText="LOADING SHOT PLAN…" />;
  }

  if (!plan || !id) {
    return (
      <RoomShell>
        <StagePlaceholder
          stage="plan"
          status={subStatus.status}
          itemsDone={subStatus.itemsDone || undefined}
          itemsTotal={subStatus.itemsTotal || undefined}
        />
      </RoomShell>
    );
  }

  return (
    <RoomShell fullHeight>
      <div className="flex h-full min-h-0 flex-col gap-3 md:gap-8">
        <RoomHeader
          kicker="SHOT PLAN"
          title="SHOT PLAN"
          lead={
            <span>
              Panels, layout, shots, dialogue, lighting, and intent before prompt generation.
              <span className="ml-2 font-meta text-[0.68rem] tracking-[0.12em] text-ink-black/45">
                {subStatus.detail}
              </span>
            </span>
          }
          actions={<ShotPlanActionButton project={id} />}
          compact={isCompact}
          onToggle={toggle}
        />

        {plan.warnings.length > 0 && (
          <div className="shrink-0 border-b-[2px] border-narrator-gold/50 bg-narrator-gold/15 px-5 py-3">
            {plan.warnings.map((warning, i) => (
              <p key={i} className="font-meta text-[0.65rem] tracking-[0.06em] text-ink-black/80">
                {warning}
              </p>
            ))}
          </div>
        )}

        <section className="flex min-h-0 flex-1 flex-col overflow-hidden border-[2px] border-ink-black bg-bristol">
          <div className="flex shrink-0 items-end gap-2 border-b-[2px] border-ink-black bg-pulp-paper px-4 pt-3">
            <TabButton view="outline" activeView={activeView} onSelect={setView}>
              Outline
            </TabButton>
            <TabButton view="board" activeView={activeView} onSelect={setView}>
              Board
            </TabButton>
            <TabButton view="layout" activeView={activeView} onSelect={setView}>
              Layout
            </TabButton>
          </div>

          <div className="min-h-0 flex-1 overflow-hidden">
            {activeView === "outline" && (
              <OutlineTab
                plan={plan}
                scenes={bible?.scenes ?? []}
                boardCounts={boardCounts}
                resolveName={resolveName}
              />
            )}
            {activeView === "board" && (
              <BoardTab
                project={id}
                plan={plan}
                sceneTitleMap={sceneTitleMap}
                resolveName={resolveName}
              />
            )}
            {activeView === "layout" && <LayoutTab plan={plan} />}
          </div>
        </section>
      </div>
    </RoomShell>
  );
}
