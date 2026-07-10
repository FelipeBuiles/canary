import { useState } from "react";
import {
  usePanelSummaries,
  usePanelsForScene,
  useProjectStatus,
  usePromptSummaries,
  usePromptsForScene,
  useScreenplay,
  useScreenplays,
} from "../api/queries";
import { useRunAction } from "../hooks/useRunAction";
import { getShotPlanAction } from "../lib/shotPlan";
import { rerunStageForDrawer, type DrawerKind } from "../lib/stations";
import { cn } from "../lib/cn";
import { Button } from "./ui/Button";
import { RerunStageAction } from "./composites";

interface InspectDrawerProps {
  project: string;
  kind: DrawerKind | null;
  onClose: () => void;
}

const DRAWER_META: Record<DrawerKind, { kicker: string; title: string; placeholder: string }> = {
  script: {
    kicker: "AUTO · READ ONLY",
    title: "Script",
    placeholder: "Scenewright writes the script automatically after you approve the cast. Nothing to read yet.",
  },
  "shot-plan": {
    kicker: "AUTO · READ ONLY",
    title: "Shot plan",
    placeholder: "Scenewright plans shots automatically after you approve the cast. Nothing to inspect yet.",
  },
  prompts: {
    kicker: "AUTO · READ ONLY",
    title: "Prompts",
    placeholder: "Scenewright writes one image prompt per panel automatically. Open a panel in the Panels station to edit its prompt.",
  },
};

function words(raw: string | null | undefined): string {
  if (!raw) return "";
  return raw.replace(/_/g, " ").trim();
}

function sceneTitle(sceneId: string): string {
  return words(sceneId).replace(/^scene /i, "Scene ");
}

// ── Script ────────────────────────────────────────────────────────────────────

function ScriptScene({ project, sceneId, title, beatCount }: { project: string; sceneId: string; title: string; beatCount: number }) {
  const [open, setOpen] = useState(false);
  const { data: screenplay } = useScreenplay(open ? project : undefined, sceneId);
  return (
    <div className="border-[2px] border-ink-black/12 bg-bristol">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline gap-3 px-4 py-3 text-left transition-colors hover:bg-pulp-paper/60"
      >
        <span className="font-meta text-[0.52rem] tracking-[0.18em] text-hero-red">{sceneTitle(sceneId).toUpperCase()}</span>
        <span className="min-w-0 flex-1 truncate font-body text-[0.85rem] font-semibold text-ink-black">{title}</span>
        <span className="font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/40">
          {beatCount} BEATS {open ? "▴" : "▾"}
        </span>
      </button>
      {open && (
        <div className="border-t border-ink-black/10 px-4 py-3">
          {!screenplay ? (
            <p className="font-meta text-[0.55rem] tracking-[0.14em] text-ink-black/40">LOADING…</p>
          ) : (
            <ol className="space-y-2">
              {screenplay.beats.map((beat, i) => (
                <li key={i} className="font-mono text-[0.72rem] leading-5 text-ink-black/80">
                  <span className="mr-2 text-ink-black/35">{String(i + 1).padStart(2, "0")}</span>
                  {beat.content}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

function ScriptBody({ project }: { project: string }) {
  const { data: screenplays, isLoading } = useScreenplays(project);
  if (isLoading) return <DrawerLoading />;
  if (!screenplays?.length) return <DrawerPlaceholder kind="script" />;
  return (
    <div className="space-y-3">
      {screenplays.map((sp) => (
        <ScriptScene key={sp.scene_id} project={project} sceneId={sp.scene_id} title={sp.title} beatCount={sp.beat_count} />
      ))}
    </div>
  );
}

// ── Shot plan ─────────────────────────────────────────────────────────────────

function ShotPlanScene({ project, sceneId, panelCount }: { project: string; sceneId: string; panelCount: number }) {
  const [open, setOpen] = useState(true);
  const { data: panels } = usePanelsForScene(open ? project : undefined, sceneId);
  return (
    <div className="border-[2px] border-ink-black/12 bg-bristol">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline gap-3 px-4 py-3 text-left transition-colors hover:bg-pulp-paper/60"
      >
        <span className="font-meta text-[0.52rem] tracking-[0.18em] text-hero-red">{sceneTitle(sceneId).toUpperCase()}</span>
        <span className="min-w-0 flex-1" />
        <span className="font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/40">
          {panelCount} PANELS {open ? "▴" : "▾"}
        </span>
      </button>
      {open && panels && (
        <ul className="divide-y divide-ink-black/8 border-t border-ink-black/10">
          {panels.map((panel) => (
            <li key={panel.panel_number} className="flex items-baseline gap-3 px-4 py-2">
              <span className="font-meta text-[0.52rem] tracking-[0.12em] text-ink-black/40">
                P{String(panel.panel_number).padStart(2, "0")}
              </span>
              {/* Plain-word shot labels — never codes like "P01 medium ·H". */}
              <span className="font-body text-[0.8rem] font-semibold capitalize text-ink-black">
                {words(panel.shot_type)} · {words(panel.camera_angle)}
              </span>
              <span className="min-w-0 flex-1 truncate text-[0.72rem] text-ink-black/50">
                {words(panel.mood)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ShotPlanBody({ project }: { project: string }) {
  const { data: summaries, isLoading } = usePanelSummaries(project);
  const { data: status } = useProjectStatus(project);
  const { handleRun, isPending } = useRunAction();

  if (isLoading) return <DrawerLoading />;
  if (!summaries?.length) {
    const action = getShotPlanAction(status);
    if (action.kind !== "none") {
      return (
        <div className="flex min-h-[30vh] flex-col items-center justify-center gap-4 px-6 text-center">
          <span className="font-meta text-[0.6rem] tracking-[0.2em] text-hero-red">FAILED</span>
          <p className="max-w-[36ch] text-[0.85rem] leading-6 text-ink-black/60">
            Shot planning failed. Retry to generate the panel layout.
          </p>
          <Button
            size="sm"
            variant="primary"
            disabled={isPending || status?.is_running}
            onClick={() =>
              handleRun(project, action.backendStage, {
                rerun: action.kind === "rerun",
                actionLabel: action.label,
              })
            }
          >
            {isPending ? "Working…" : action.label}
          </Button>
        </div>
      );
    }
    return <DrawerPlaceholder kind="shot-plan" />;
  }
  return (
    <div className="space-y-3">
      {summaries.map((s) => (
        <ShotPlanScene key={s.scene_id} project={project} sceneId={s.scene_id} panelCount={s.panel_count} />
      ))}
    </div>
  );
}

// ── Prompts ───────────────────────────────────────────────────────────────────

function PromptScene({ project, sceneId, promptCount }: { project: string; sceneId: string; promptCount: number }) {
  const [open, setOpen] = useState(true);
  const { data: prompts } = usePromptsForScene(open ? project : undefined, sceneId);
  return (
    <div className="border-[2px] border-ink-black/12 bg-bristol">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-baseline gap-3 px-4 py-3 text-left transition-colors hover:bg-pulp-paper/60"
      >
        <span className="font-meta text-[0.52rem] tracking-[0.18em] text-hero-red">{sceneTitle(sceneId).toUpperCase()}</span>
        <span className="min-w-0 flex-1" />
        <span className="font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/40">
          {promptCount} PROMPTS {open ? "▴" : "▾"}
        </span>
      </button>
      {open && prompts && (
        <ul className="divide-y divide-ink-black/8 border-t border-ink-black/10">
          {prompts.map((prompt) => {
            const cast = (prompt.subjects ?? []).map((s) => s.name).filter(Boolean).join(", ");
            return (
              <li key={prompt.panel_number} className="px-4 py-2.5">
                <div className="flex items-baseline gap-3">
                  <span className="font-meta text-[0.52rem] tracking-[0.12em] text-ink-black/40">
                    P{String(prompt.panel_number).padStart(2, "0")}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-body text-[0.8rem] font-semibold text-ink-black">
                    {prompt.composition || words(prompt.setting?.split("\n")[0])}
                  </span>
                </div>
                <div className="mt-1 grid gap-x-4 gap-y-0.5 text-[0.7rem] leading-5 text-ink-black/60 sm:grid-cols-2">
                  {cast && <span className="truncate"><span className="text-ink-black/40">Cast:</span> {cast}</span>}
                  {prompt.setting && <span className="truncate"><span className="text-ink-black/40">Setting:</span> {prompt.setting.split("\n")[0]}</span>}
                  {prompt.lighting && <span className="truncate"><span className="text-ink-black/40">Light:</span> {prompt.lighting}</span>}
                  {prompt.mood && <span className="truncate"><span className="text-ink-black/40">Mood:</span> {prompt.mood}</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function PromptsBody({ project }: { project: string }) {
  const { data: summaries, isLoading } = usePromptSummaries(project);
  if (isLoading) return <DrawerLoading />;
  if (!summaries?.length) return <DrawerPlaceholder kind="prompts" />;
  return (
    <div className="space-y-3">
      {summaries.map((s) => (
        <PromptScene key={s.scene_id} project={project} sceneId={s.scene_id} promptCount={s.prompt_count} />
      ))}
    </div>
  );
}

// ── Shared chrome ─────────────────────────────────────────────────────────────

function DrawerLoading() {
  return <p className="font-meta text-[0.55rem] tracking-[0.18em] text-ink-black/40">LOADING…</p>;
}

function DrawerPlaceholder({ kind }: { kind: DrawerKind }) {
  return (
    <div className="flex min-h-[30vh] flex-col items-center justify-center gap-3 px-6 text-center">
      <span className="font-meta text-[0.6rem] tracking-[0.2em] text-ink-black/30">NOT WRITTEN YET</span>
      <p className="max-w-[36ch] text-[0.85rem] leading-6 text-ink-black/60">{DRAWER_META[kind].placeholder}</p>
    </div>
  );
}

/**
 * Footer action for the auto-step drawers: re-run this step (and everything
 * downstream) from the frontend. These stages run automatically and are
 * otherwise read-only, so this is how the four-station UI re-exposes
 * "re-run from a determinate stage" for the auto chain. Hidden until the step
 * has produced output; disabled while any stage is running. Reuses
 * RerunStageAction's guarded confirmation (downstream impact + credit estimate).
 */
function InspectDrawerRerun({ project, kind }: { project: string; kind: DrawerKind }) {
  const { data: status } = useProjectStatus(project);
  const stage = rerunStageForDrawer(kind);
  if (status?.stages[stage]?.status !== "complete") return null;
  return (
    <div className="flex min-h-16 items-center justify-between gap-3 border-t-[2px] border-ink-black bg-bristol px-4 py-2">
      <p className="max-w-[22ch] text-[0.7rem] leading-5 text-ink-black/55">
        Regenerate this step and everything after it.
      </p>
      <RerunStageAction
        project={project}
        stage={stage}
        label={DRAWER_META[kind].title}
        disabled={status?.is_running}
      />
    </div>
  );
}

/**
 * Read-only inspect drawer for auto pipeline steps (script, shot plan,
 * prompts). Opens over the content area; never blocks progression.
 */
export function InspectDrawer({ project, kind, onClose }: InspectDrawerProps) {
  if (!kind) return null;
  const meta = DRAWER_META[kind];

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={meta.title}>
      <div className="absolute inset-0 bg-ink-black/35" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-[460px] max-w-[94vw] flex-col border-l-[2px] border-ink-black bg-pulp-paper">
        <div className="flex h-shell-top shrink-0 items-center justify-between border-b-[2px] border-ink-black bg-bristol px-4">
          <div>
            <div className="font-meta text-[0.5rem] tracking-[0.2em] text-ink-black/45">{meta.kicker}</div>
            <div className="font-display text-[1.25rem] font-bold uppercase leading-tight tracking-[-0.03em]">
              {meta.title}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-11 w-11 items-center justify-center text-ink-black/50 transition-colors hover:text-hero-red"
          >
            ✕
          </button>
        </div>
        <div className={cn("min-h-0 flex-1 overflow-y-auto p-4")}>
          {kind === "script" && <ScriptBody project={project} />}
          {kind === "shot-plan" && <ShotPlanBody project={project} />}
          {kind === "prompts" && <PromptsBody project={project} />}
        </div>
        <InspectDrawerRerun project={project} kind={kind} />
      </aside>
    </div>
  );
}
