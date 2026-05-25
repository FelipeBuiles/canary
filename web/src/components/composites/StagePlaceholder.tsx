import { STAGE_ORDER, type StageName, type StageStatus } from "../../types/api";
import { Icon } from "../ui/Icon";

// ── Stage metadata ────────────────────────────────────────────────────────────

interface StageMeta {
  label: string;
  title: string;
  description: string;
  inputs: string[];
  outputs: string[];
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const STAGE_META: Record<StageName, StageMeta> = {
  extract: {
    label: "EXTRACT",
    title: "Story Bible",
    description: "Parses the source text into a structured bible — characters, locations, scenes, arcs, and props.",
    inputs: ["Source text"],
    outputs: ["Characters", "Locations", "Scenes", "Arcs"],
    icon: () => <span className="font-display text-lg font-black">01</span>,
  },
  style: {
    label: "LOOK & FEEL",
    title: "Visual Style",
    description: "Creates visual direction options and sample artwork so the comic has a consistent look before casting.",
    inputs: ["Story bible"],
    outputs: ["Style options", "Sample art"],
    icon: () => <span className="font-display text-lg font-black">02</span>,
  },
  cast: {
    label: "CAST",
    title: "Visual Casting",
    description: "Generates reference images for each character and location extracted from the story bible.",
    inputs: ["Story bible"],
    outputs: ["Character refs", "Location plates"],
    icon: () => <span className="font-display text-lg font-black">03</span>,
  },
  adapt: {
    label: "ADAPT",
    title: "Screenplay",
    description: "Transforms prose scenes into screenplay beats — action, dialogue, sfx, and stage direction.",
    inputs: ["Story bible", "Scenes"],
    outputs: ["Screenplay beats"],
    icon: () => <span className="font-display text-lg font-black">04</span>,
  },
  plan: {
    label: "PLAN",
    title: "Layout Plan",
    description: "Groups beats into panels and pages, deciding panel count, importance, and page rhythm.",
    inputs: ["Screenplay"],
    outputs: ["Planned panels", "Planned pages"],
    icon: () => <span className="font-display text-lg font-black">05</span>,
  },
  storyboard: {
    label: "STORYBOARD",
    title: "Panel Breakdown",
    description: "Details each planned panel — shot type, camera angle, character poses, expressions, and mood.",
    inputs: ["Screenplay", "Layout plan"],
    outputs: ["Panel breakdowns"],
    icon: () => <span className="font-display text-lg font-black">06</span>,
  },
  direct: {
    label: "DIRECT",
    title: "Image Prompts",
    description: "Assembles fully-baked image prompts with style, composition, character refs, and continuity notes.",
    inputs: ["Panel breakdowns", "Character refs"],
    outputs: ["Image prompts"],
    icon: () => <span className="font-display text-lg font-black">07</span>,
  },
  draw: {
    label: "DRAW",
    title: "Panel Gallery",
    description: "Sends each prompt to the image model and collects generated panel artwork.",
    inputs: ["Image prompts", "Style"],
    outputs: ["Panel images"],
    icon: () => <span className="font-display text-lg font-black">08</span>,
  },
  compose: {
    label: "COMPOSE",
    title: "Comic Pages",
    description: "Assembles panels, bubbles, sfx, and lettering onto final comic page layouts.",
    inputs: ["Panel images", "Layout plan"],
    outputs: ["Comic pages"],
    icon: () => <span className="font-display text-lg font-black">09</span>,
  },
};

// ── Pending state ─────────────────────────────────────────────────────────────

interface StagePendingProps {
  stage: StageName;
}

export function StagePending({ stage }: StagePendingProps) {
  const meta = STAGE_META[stage];
  const StageIcon = meta.icon;

  return (
    <div className="flex min-h-[50vh] items-center justify-center px-6">
      <div className="w-full max-w-md">
        {/* Stage number badge */}
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center border-[2px] border-ink-black/12 bg-pulp-paper text-ink-black/25">
          <StageIcon />
        </div>

        {/* Title block */}
        <div className="mb-2 text-center font-meta text-[0.68rem] font-bold tracking-[0.28em] text-ink-black/30">
          {meta.label}
        </div>
        <div className="text-center font-display text-[1.6rem] font-black uppercase tracking-[-0.04em] text-ink-black/22">
          {meta.title}
        </div>

        {/* Description */}
        <p className="mx-auto mt-4 max-w-xs text-center text-[0.88rem] leading-7 text-ink-black/38">
          {meta.description}
        </p>

        {/* Input → Output flow */}
        <div className="mt-8 flex items-start justify-center gap-3">
          <div className="text-right">
            {meta.inputs.map((input) => (
              <div key={input} className="font-meta text-[0.62rem] font-bold tracking-[0.18em] text-ink-black/28">
                {input.toUpperCase()}
              </div>
            ))}
          </div>
          <div className="mt-1 flex flex-col items-center gap-1">
            <div className="h-px w-8 bg-ink-black/12" />
            <Icon name="arrow-right" size={12} className="text-ink-black/18" />
          </div>
          <div>
            {meta.outputs.map((output) => (
              <div key={output} className="font-meta text-[0.62rem] font-bold tracking-[0.18em] text-ink-black/28">
                {output.toUpperCase()}
              </div>
            ))}
          </div>
        </div>

        {/* Status pill */}
        <div className="mt-8 flex justify-center">
          <div className="border border-ink-black/8 bg-surface-container px-4 py-1.5 font-meta text-[0.58rem] font-bold tracking-[0.22em] text-ink-black/28">
            WAITING FOR PIPELINE
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Running state ─────────────────────────────────────────────────────────────

interface StageRunningProps {
  stage: StageName;
  itemsDone?: number;
  itemsTotal?: number;
}

export function StageRunning({ stage, itemsDone = 0, itemsTotal = 0 }: StageRunningProps) {
  const meta = STAGE_META[stage];
  const StageIcon = meta.icon;
  const hasProgress = itemsTotal > 0;
  const pct = hasProgress ? Math.round((itemsDone / itemsTotal) * 100) : 0;

  return (
    <div className="flex min-h-[50vh] items-center justify-center px-6">
      <div className="w-full max-w-sm">
        {/* Animated stage badge */}
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center border-[2px] border-ink-black bg-pulp-paper shadow-ink-sm">
          <div className="animate-pulse">
            <StageIcon />
          </div>
        </div>

        {/* Title */}
        <div className="mb-1 text-center font-meta text-[0.68rem] font-bold tracking-[0.28em] text-narrator-gold">
          RUNNING
        </div>
        <div className="text-center font-display text-[1.6rem] font-black uppercase tracking-[-0.04em] text-ink-black">
          {meta.title}
        </div>

        {/* Description */}
        <p className="mx-auto mt-3 max-w-xs text-center text-[0.88rem] leading-7 text-ink-black/50">
          {meta.description}
        </p>

        {/* Progress bar */}
        <div className="mt-8">
          <div className="mb-2 flex items-center justify-between font-meta text-[0.6rem] font-bold tracking-[0.18em] text-ink-black/45">
            <span>{hasProgress ? `${itemsDone} / ${itemsTotal}` : "STARTING…"}</span>
            {hasProgress && <span>{pct}%</span>}
          </div>
          <div className="h-2.5 w-full overflow-hidden border-[2px] border-ink-black bg-pulp-paper">
            <div
              className="h-full bg-narrator-gold transition-all duration-500 ease-out"
              style={{ width: hasProgress ? `${Math.max(4, pct)}%` : "0%" }}
            />
          </div>
        </div>

        {/* Output hints */}
        <div className="mt-6 flex justify-center gap-2">
          {meta.outputs.map((output) => (
            <div
              key={output}
              className="border border-ink-black/10 bg-surface-container px-3 py-1 font-meta text-[0.56rem] font-bold tracking-[0.18em] text-ink-black/35"
            >
              {output.toUpperCase()}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Combined switcher ─────────────────────────────────────────────────────────

interface StagePlaceholderProps {
  stage: StageName;
  status: StageStatus;
  itemsDone?: number;
  itemsTotal?: number;
}

export function StagePlaceholder({ stage, status, itemsDone, itemsTotal }: StagePlaceholderProps) {
  if (status === "running") {
    return <StageRunning stage={stage} itemsDone={itemsDone} itemsTotal={itemsTotal} />;
  }
  if (status === "pending") {
    return <StagePending stage={stage} />;
  }
  // Stage completed/failed but no data — shouldn't normally happen,
  // show a minimal state while the data loads or indicate the issue.
  const meta = STAGE_META[stage];
  return (
    <div className="flex min-h-[40vh] items-center justify-center px-6">
      <div className="w-full max-w-sm text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center border-[2px] border-ink-black/12 bg-surface-container text-ink-black/25">
          <span className="font-display text-lg font-black">
            {String(STAGE_ORDER.indexOf(stage) + 1).padStart(2, "0")}
          </span>
        </div>
        <div className="font-display text-[1.5rem] font-bold tracking-[-0.05em] text-ink-black/30">
          {meta.title.toUpperCase()} NOT AVAILABLE
        </div>
        <p className="mt-2 text-[0.82rem] leading-6 text-ink-black/50">
          {status === "failed"
            ? "This stage failed. Try re-running it from the sidebar."
            : "Data for this stage could not be loaded."}
        </p>
      </div>
    </div>
  );
}
