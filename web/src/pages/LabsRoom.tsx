import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, Check, Copy, Download, Eye, EyeOff, Plus, RotateCcw, Trash2, X } from "lucide-react";
import {
  useCreateLabsRun,
  useDeleteLabsRun,
  useRetryLabsCells,
  useImageArmPreview,
  useImageCompareEstimate,
  useImageCompareOptions,
  useImageItems,
  useLabsProjects,
  useLabsRun,
  useLabsRuns,
  useStageModelEstimate,
  useStageModelOptions,
  useModernizeEstimate,
  useModernizeExcerpt,
  useModernizeOptions,
  useModernizeSource,
} from "../api/queries";
import {
  labsRunFileUrl,
  type ImageArm,
  type ImageCell,
  type ImagePrompt,
  type ImageQuality,
  type ImageTarget,
  type LabsFunding,
  type LabsProject,
  type LabsRunDetail,
  type LabsRunSummary,
  type StageModelCell,
  type StageModelArm,
  type StageResult,
  type StageModelOption,
  type ModernizeArm,
  type ModernizeCell,
  type ModernizeChange,
  type ModernizeControls,
  type ModernizeIntensity,
  type ModernizeScope,
  type ModernizeSensitive,
  type ModernizeSource,
} from "../api/labs";
import { SectionHeader } from "../components/composites";
import { Button } from "../components/ui/Button";
import { Select } from "../components/ui/Select";
import { Surface } from "../components/ui/Surface";
import { cn } from "../lib/cn";
import { InspectBadge } from "../components/ui/InspectButton";
import { useImageViewer } from "../hooks/useImageViewer";
import { wordDiff } from "../lib/wordDiff";
import { modernizedFilename, modernizedText } from "../lib/modernizedText";

/*
 * Labs is a local-development room for model experiments on the operator's own
 * projects. API calls cost provider USD paid by the operator; subscription calls
 * use the local Claude or Codex allowance. Neither ever touches account credits,
 * and estimates are always labelled apart from measured amounts.
 */

const PHASE_LABEL: Record<string, string> = {
  extract_brief: "Extract + Brief",
  adapt_plan: "Adapt + Plan",
  full: "End to end",
};
/** Approved source stages a phase reads instead of running. */
const PHASE_NEEDS: Record<string, string[]> = { adapt_plan: ["brief", "style", "cast"], full: ["style", "cast"] };
const KIND_LABEL: Record<LabsRunSummary["kind"], string> = {
  image_compare: "Image comparison",
  stage_models: "Stage models",
  modernize: "Modernize source",
};
const PROMPT_LABEL: Record<ImagePrompt, string> = {
  production: "Production prompt",
  restructured: "Restructured prompt",
  sheet_form: "Character sheet · form study",
  sheet_formation: "Character sheet · formation",
};
const DEFAULT_ARMS: ImageArm[] = [
  { target: "sunburst-openai", prompt: "production" },
  { target: "flare-openai", prompt: "production" },
];
const MAX_ITEMS = 12;
const READY = new Set(["complete", "awaiting_review"]);
const META = "font-meta text-xs tracking-[0.08em] text-ink-muted";

function usd(value: number | null | undefined, digits = 3): string {
  return value == null ? "—" : `$${value.toFixed(digits)}`;
}

/** Measured spend, or the allowance it came from for subscription work. */
function spend(value: number | null | undefined, funding: LabsFunding | string | undefined, digits = 3): string {
  return funding && funding !== "api" ? "subscription" : usd(value, digits);
}

/** Measured spend plus, for subscription work, what the same calls would cost at API rates. */
function costWithEquivalent(measured: number | null | undefined, equivalent: number | null | undefined,
  funding: LabsFunding | string | undefined, digits = 3): string {
  if (funding && funding !== "api") return equivalent == null ? "subscription" : `subscription (≈${usd(equivalent, digits)} at API rates)`;
  return usd(measured, digits);
}

function sizeLabel(size: string | null | undefined): string {
  return size ? size.replace("x", "×") : "—";
}

/** CSS aspect ratio for a "WIDTHxHEIGHT" size. */
function aspect(size: string | null | undefined): string {
  const [width, height] = (size ?? "").split("x").map(Number);
  return width && height ? `${width} / ${height}` : "2 / 3";
}

function seconds(value: number | null | undefined): string {
  if (value == null) return "—";
  return value >= 60 ? `${Math.floor(value / 60)}m ${Math.round(value % 60)}s` : `${value.toFixed(1)}s`;
}

/** Seconds at the provider when known; a cell's wall time otherwise. */
function routeSeconds(cell: ImageCell): number {
  return (cell.provider_latency_ms ?? cell.latency_ms ?? 0) / 1000;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function count(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString();
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

function targetName(targets: ImageTarget[] | undefined, id: string): string {
  const target = targets?.find((candidate) => candidate.id === id);
  return target ? `${target.label} · ${target.provider}` : id;
}

function armName(targets: ImageTarget[] | undefined, arm: ImageArm): string {
  return [targetName(targets, arm.target), arm.quality && `${arm.quality} quality`, PROMPT_LABEL[arm.prompt]]
    .filter(Boolean).join(" · ");
}

function armKey(arm: ImageArm): string {
  return `${arm.target}|${arm.prompt}|${arm.quality ?? ""}`;
}

const QUALITY_OPTIONS: { value: string; label: string }[] = [
  { value: "default", label: "Production quality" },
  { value: "low", label: "Low quality" },
  { value: "medium", label: "Medium quality" },
  { value: "high", label: "High quality" },
];

/** "gemini-4-carbon", or "gemini-4-carbon · plan: gemini-3.8-flash" for a mixed arm. */
function stageArmLabel(model: string, stageModels: Record<string, string> | undefined): string {
  const overrides = Object.entries(stageModels ?? {}).filter(([, chosen]) => chosen !== model);
  return [model, ...overrides.map(([stage, chosen]) => `${stage}: ${chosen}`)].join(" · ");
}

function StatusChip({ status }: { status: string }) {
  const tone = status === "ok" || status === "complete" ? "bg-ink-black text-bristol"
    : status === "running" ? "bg-narrator-gold text-ink-black"
      : status === "failed" || status === "interrupted" ? "bg-hero-red text-bristol"
        : "bg-pulp-paper text-ink-black";
  return (
    <span className={cn("inline-block px-1.5 py-0.5 font-meta text-[0.68rem] font-bold uppercase tracking-[0.1em]", tone)}>
      {status === "ok" ? "done" : status}
    </span>
  );
}

function FundingTag({ funding }: { funding: LabsFunding | string }) {
  return (
    <span className={cn(META, "ml-2 whitespace-nowrap")}>
      {funding === "api" ? "API · USD" : funding === "codex_subscription" ? "Codex subscription" : "Claude subscription"}
    </span>
  );
}

function Checkbox({ checked, onChange, disabled, children }: {
  checked: boolean; onChange: (next: boolean) => void; disabled?: boolean; children: ReactNode;
}) {
  return (
    <label className={cn("flex min-h-11 cursor-pointer items-start gap-3", disabled && "cursor-not-allowed opacity-45")}>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 shrink-0 accent-hero-red"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="min-w-0 flex-1">{children}</span>
    </label>
  );
}

function LoadError({ error, retrying, onRetry }: { error: unknown; retrying: boolean; onRetry: () => void }) {
  return (
    <div role="alert" className="space-y-2 border-l-[3px] border-hero-red pl-3">
      <p className="font-body text-sm">Labs could not be loaded: {String(error)}</p>
      <Button variant="outline" size="sm" disabled={retrying} onClick={onRetry}>
        {retrying ? "Retrying…" : "Retry Labs"}
      </Button>
    </div>
  );
}

function ProjectPicker({ projects, value, onChange }: {
  projects: LabsProject[]; value: string; onChange: (project: string) => void;
}) {
  return (
    <div>
      <div className={META}>Project</div>
      <Select
        className="mt-1 max-w-md"
        aria-label="Project"
        value={value}
        onValueChange={onChange}
        options={projects.map((project) => ({
          value: project.id,
          label: `${project.title}${project.words ? ` · ${project.words.toLocaleString()} words` : ""}`,
        }))}
      />
    </div>
  );
}

// ── Image comparison setup ───────────────────────────────────────────────────

function ArmEditor({ arms, targets, onChange }: {
  arms: ImageArm[]; targets: ImageTarget[]; onChange: (arms: ImageArm[]) => void;
}) {
  const update = (index: number, patch: Partial<ImageArm>) =>
    onChange(arms.map((arm, position) => (position === index ? { ...arm, ...patch } : arm)));
  return (
    <fieldset className="space-y-2">
      <legend className={META}>Arms: what each image is made with</legend>
      {arms.map((arm, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          <span className="w-12 font-meta text-xs font-bold">Arm {index + 1}</span>
          <Select
            className="min-w-0 flex-[1_1_16rem]"
            aria-label={`Arm ${index + 1} model and route`}
            value={arm.target}
            onValueChange={(target) => update(index, {
              target,
              quality: targets.find((candidate) => candidate.id === target)?.accepts_quality ? arm.quality : undefined,
            })}
            options={targets.map((target) => ({
              value: target.id,
              label: `${target.label} · ${target.provider}${target.available ? "" : " (not enabled)"}`,
              disabled: !target.available,
            }))}
          />
          <Select
            className="min-w-0 flex-[1_1_12rem]"
            aria-label={`Arm ${index + 1} prompt`}
            value={arm.prompt}
            onValueChange={(prompt) => update(index, { prompt: prompt as ImagePrompt })}
            options={(Object.keys(PROMPT_LABEL) as ImagePrompt[]).map((prompt) => ({ value: prompt, label: PROMPT_LABEL[prompt] }))}
          />
          {targets.find((candidate) => candidate.id === arm.target)?.accepts_quality && (
            <Select
              className="min-w-0 flex-[1_1_10rem]"
              aria-label={`Arm ${index + 1} quality`}
              value={arm.quality ?? "default"}
              onValueChange={(quality) => update(index, {
                quality: quality === "default" ? undefined : (quality as ImageQuality),
              })}
              options={QUALITY_OPTIONS}
            />
          )}
          {arms.length > 2 && (
            <button type="button" aria-label={`Remove arm ${index + 1}`} className="min-h-11 min-w-11 text-ink-muted hover:text-hero-red"
              onClick={() => onChange(arms.filter((_, position) => position !== index))}>
              <X className="mx-auto h-4 w-4" aria-hidden />
            </button>
          )}
        </div>
      ))}
      {arms.length < 4 && (
        <Button variant="outline" size="xs" onClick={() => onChange([...arms, { ...arms[arms.length - 1] }])}>
          <Plus className="mr-1 inline h-3.5 w-3.5" aria-hidden /> Add arm
        </Button>
      )}
      <p className={META}>
        Production prompt = what Canary sends today (pages are compiled now for each model). Restructured = the same
        request restated scene-first, with anchors, style and lettering kept word for word. Quality applies to GPT
        Image targets: Style/Cast items keep their recorded quality unless an arm sets one; pages accept a quality
        on OpenAI and Runware routes.
      </p>
    </fieldset>
  );
}

function ArmPreviewPanel({ project, item, arms, targets }: {
  project: string; item: string; arms: ImageArm[]; targets: ImageTarget[];
}) {
  const preview = useImageArmPreview({ project, item, arms });
  if (preview.isFetching) return <p className={META}>Compiling prompts…</p>;
  if (preview.error) return <p className="font-body text-sm text-hero-red">{String(preview.error)}</p>;
  return (
    <div className={cn("grid gap-3", arms.length > 2 ? "xl:grid-cols-2" : "md:grid-cols-2")}>
      {preview.data?.arms.map((arm, index) => (
        <div key={index} className="min-w-0">
          <div className="font-meta text-xs font-bold">Arm {index + 1} · {armName(targets, arms[index])}</div>
          {arm.error ? (
            <p className="mt-1 font-body text-sm text-hero-red">{arm.error}</p>
          ) : (
            <>
              <div className={META}>
                {arm.width}×{arm.height} · {arm.references} refs · {count(arm.chars)} chars ·{" "}
                {arm.estimated_cost_usd == null
                  ? `subscription${arm.api_equivalent_usd == null ? "" : ` (≈${usd(arm.api_equivalent_usd)} at API rates)`}`
                  : `≈${usd(arm.estimated_cost_usd)} est.`}
              </div>
              {!!arm.missing_verbatim?.length && (
                <p className="mt-1 flex gap-1.5 font-body text-sm text-hero-red">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                  Drops {arm.missing_verbatim.length} verbatim item(s): {arm.missing_verbatim.map((text) => `“${text.slice(0, 50)}”`).join(", ")}
                </p>
              )}
              <pre className="mt-1 max-h-96 overflow-auto whitespace-pre-wrap border-[1.5px] border-ink-black/15 bg-pulp-paper p-2.5 font-body text-xs leading-5">
                {arm.prompt}
              </pre>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function ImageCompareSetup({ projects, onStarted }: { projects: LabsProject[]; onStarted: (runId: string) => void }) {
  const options = useImageCompareOptions();
  const create = useCreateLabsRun();
  const [picked, setProject] = useState("");
  const project = picked || projects[0]?.id || "";
  const items = useImageItems(project);
  const [arms, setArms] = useState<ImageArm[]>(DEFAULT_ARMS);
  const [selected, setSelected] = useState<string[]>([]);
  const [kind, setKind] = useState<"all" | "asset" | "page">("all");
  const [previewing, setPreviewing] = useState<string | null>(null);
  const targets = options.data?.targets ?? [];
  const armsValid = new Set(arms.map(armKey)).size === arms.length;
  const estimate = useImageCompareEstimate(selected.length && armsValid ? { project, items: selected, arms } : null);
  const visible = (items.data?.items ?? []).filter((item) => kind === "all" || item.kind === kind);

  if (options.error) return <LoadError error={options.error} retrying={options.isFetching} onRetry={() => void options.refetch()} />;
  if (options.isLoading) return <p className={META}>Loading models…</p>;

  const toggle = (id: string, next: boolean) =>
    setSelected(next ? [...selected, id] : selected.filter((item) => item !== id));

  return (
    <div className="space-y-5">
      <p className="max-w-3xl font-body text-sm leading-6 text-ink-muted">
        Pick a project and any of its Style & Cast images or planned pages, then choose what each arm uses. Every arm
        of an item gets the same references in the same order; only the model, route and prompt change. Each image is
        one call to one route, with no fallback and no retry.
      </p>
      <ProjectPicker projects={projects} value={project} onChange={(next) => { setProject(next); setSelected([]); setPreviewing(null); }} />
      <ArmEditor arms={arms} targets={targets} onChange={setArms} />
      {!armsValid && <p className="font-body text-sm text-hero-red">Each arm must differ in model, route, prompt or quality.</p>}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className={META}>Items ({selected.length}/{MAX_ITEMS} selected)</span>
          <div className="flex gap-1" role="group" aria-label="Filter items">
            {(["all", "asset", "page"] as const).map((value) => (
              <Button key={value} size="xs" variant={kind === value ? "secondary" : "outline"} onClick={() => setKind(value)}>
                {value === "all" ? "All" : value === "asset" ? "Style & Cast" : "Pages"}
              </Button>
            ))}
          </div>
        </div>
        {items.isLoading && <p className={META}>Loading items…</p>}
        {items.error && <p className="font-body text-sm text-hero-red">{String(items.error)}</p>}
        <ul className="mt-2 max-h-[28rem] divide-y divide-ink-black/10 overflow-auto border-[1.5px] border-ink-black/15">
          {visible.map((item) => (
            <li key={item.id} className="flex items-center gap-3 px-3">
              <Checkbox
                checked={selected.includes(item.id)}
                disabled={!selected.includes(item.id) && selected.length >= MAX_ITEMS}
                onChange={(next) => toggle(item.id, next)}
              >
                <span className="font-body text-sm">{item.label}</span>
                {item.kind === "asset" && (
                  <span className={cn(META, "block")}>
                    recorded {relTime(item.recorded_at)} on {item.recorded_route} · {item.references} refs
                  </span>
                )}
              </Checkbox>
              {item.preview && (
                <img src={`/api/labs/projects/${encodeURIComponent(project)}/files/${item.preview}`} alt=""
                  className="h-10 w-10 shrink-0 border border-ink-black/15 object-cover" loading="lazy" />
              )}
              <button
                type="button"
                className="min-h-11 shrink-0 font-meta text-xs font-bold tracking-[0.08em] text-hero-red"
                aria-expanded={previewing === item.id}
                onClick={() => setPreviewing(previewing === item.id ? null : item.id)}
              >
                {previewing === item.id ? "Hide prompts" : "Prompts"}
              </button>
            </li>
          ))}
          {items.data && visible.length === 0 && <li className="p-3 font-body text-sm text-ink-muted">Nothing to compare here yet.</li>}
        </ul>
      </div>
      {previewing && armsValid && <ArmPreviewPanel project={project} item={previewing} arms={arms} targets={targets} />}
      <div className="space-y-2">
        {estimate.data?.problems.map((problem, index) => (
          <p key={index} className="flex gap-1.5 font-body text-sm text-hero-red">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {problem.item} · Arm {problem.arm + 1}: {problem.error}
          </p>
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            disabled={!selected.length || !armsValid || create.isPending}
            onClick={() => create.mutate(
              { kind: "image_compare", label: `${arms.map((arm) => armName(targets, arm)).join(" vs ")}`, project, items: selected, arms },
              { onSuccess: (run) => onStarted(run.run_id) },
            )}
          >
            Run {selected.length * arms.length} image{selected.length * arms.length === 1 ? "" : "s"}
          </Button>
          <span className={META}>
            {estimate.isFetching ? "Estimating…"
              : estimate.error ? String(estimate.error)
                : estimate.data ? `${estimate.data.calls.api} API (≈${usd(estimate.data.estimated_cost_usd, 2)} est.) · ${estimate.data.calls.subscription} subscription`
                  : "Choose at least one item"}
          </span>
          {create.error && <span className="font-body text-sm text-hero-red">{String(create.error)}</span>}
        </div>
      </div>
    </div>
  );
}

// ── Stage models setup ───────────────────────────────────────────────────────

function StageModelsSetup({ projects, onStarted }: { projects: LabsProject[]; onStarted: (runId: string) => void }) {
  const { data, isLoading, isFetching, error, refetch } = useStageModelOptions();
  const create = useCreateLabsRun();
  const [picked, setProject] = useState("");
  const project = picked || projects[0]?.id || "";
  const [phases, setPhases] = useState<string[]>(["extract_brief", "adapt_plan"]);
  const [arms, setArms] = useState<StageModelArm[] | null>(null);
  const chosenArms = arms ?? (data?.default_models ?? []).map<StageModelArm>((model, index) => ({
    id: `arm-${index + 1}`, model, reasoning_efforts: {},
  }));
  const source = projects.find((candidate) => candidate.id === project);
  const missing = (phase: string) => (PHASE_NEEDS[phase] ?? []).filter((stage) => !READY.has(source?.statuses[stage] ?? ""));
  const activePhases = phases.filter((phase) => !!source && !missing(phase).length);
  // A stage runs on one model per arm, whichever phases include it.
  const activeStages = [...new Set(activePhases.flatMap((phase) => data?.phases[phase] ?? []))];
  const stageModel = (arm: StageModelArm, stage: string) => arm.stage_models?.[stage] ?? arm.model;
  const effectiveArms = chosenArms.map((arm) => ({
    ...arm,
    stage_models: Object.fromEntries(activeStages.map((stage) => [stage, stageModel(arm, stage)])),
    reasoning_efforts: Object.fromEntries(activeStages.map((stage) => [
      stage, arm.reasoning_efforts[stage]
        ?? data?.models.find((candidate) => candidate.id === stageModel(arm, stage))?.default_reasoning ?? "medium",
    ])),
  }));
  const request = source && activePhases.length && chosenArms.length >= 2
    ? { project, part_id: source.part_id, phases: activePhases, arms: effectiveArms } : null;
  const estimate = useStageModelEstimate(request);
  const providers = useMemo(() => {
    const groups = new Map<string, NonNullable<typeof data>["models"]>();
    for (const model of data?.models ?? []) groups.set(model.provider, [...(groups.get(model.provider) ?? []), model]);
    return [...groups.entries()];
  }, [data]);

  if (error) return <LoadError error={error} retrying={isFetching} onRetry={() => void refetch()} />;
  if (isLoading || !data) return <p className={META}>Loading models…</p>;

  const toggle = (list: string[], value: string, next: boolean) =>
    next ? [...list, value] : list.filter((item) => item !== value);
  const addArm = (model: string, reasoning_efforts: Record<string, string> = {}, stage_models: Record<string, string> = {}) => {
    const next = Math.max(0, ...chosenArms.map((arm) => Number(arm.id.replace("arm-", "")))) + 1;
    setArms([...chosenArms, { id: `arm-${next}`, model, stage_models: { ...stage_models }, reasoning_efforts: { ...reasoning_efforts } }]);
  };
  const setStageModel = (armId: string, stage: string, model: string) => setArms(chosenArms.map((candidate) => {
    if (candidate.id !== armId) return candidate;
    // A new model's reasoning choices may differ, so the stage falls back to that model's default.
    const reasoning_efforts = { ...candidate.reasoning_efforts };
    delete reasoning_efforts[stage];
    return { ...candidate, stage_models: { ...candidate.stage_models, [stage]: model }, reasoning_efforts };
  }));
  const spendsUsd = (arm: StageModelArm) => activeStages.some((stage) =>
    data.models.find((model) => model.id === stageModel(arm, stage))?.funding === "api");
  const apiTotal = chosenArms.reduce((total, arm) =>
    total + (spendsUsd(arm) ? estimate.data?.estimated_cost_usd[arm.id] ?? 0 : 0), 0);
  const missingEstimate = chosenArms.some((arm) => spendsUsd(arm) && estimate.data?.estimated_cost_usd[arm.id] == null);

  return (
    <div className="space-y-5">
      <p className="max-w-3xl font-body text-sm leading-6 text-ink-muted">
        Runs the same stages on the same inputs once per comparison arm, each in its own copy of the project.
        Add a model more than once to compare reasoning levels or repeat a trial, or give a stage its own model to
        test a mix, such as one model&apos;s Adapt feeding another&apos;s Plan. Extract + Brief starts from the
        novel text; Adapt + Plan starts from the project&apos;s approved Brief, Style and Cast. End to end runs all four
        stages on the arm&apos;s own outputs, keeping the approved Style and Cast. Your project is only read.
      </p>
      <ProjectPicker projects={projects} value={project} onChange={setProject} />
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <fieldset>
          <legend className={META}>Stages</legend>
          {Object.entries(data.phases).map(([phase, stages]) => (
            <Checkbox key={phase} checked={activePhases.includes(phase)}
              disabled={create.isPending || !source || !!missing(phase).length}
              onChange={(next) => setPhases(toggle(phases, phase, next))}>
              <span className="font-body text-sm font-bold">{PHASE_LABEL[phase] ?? phase}</span>
              <span className={cn(META, "block")}>
                {missing(phase).length ? `Needs an approved ${PHASE_NEEDS[phase].map((stage) => stage[0].toUpperCase() + stage.slice(1)).join(", ")}`
                  : stages.join(" → ")}
              </span>
            </Checkbox>
          ))}
        </fieldset>
        <fieldset>
          <legend className={META}>Models (2–6 comparison arms)</legend>
          <div className="grid gap-x-5 sm:grid-cols-2">
            {providers.map(([provider, group]) => (
              <div key={provider} className="mt-2">
                <div className="font-meta text-xs font-bold">{provider}</div>
                {group.map((model) => {
                  const selected = chosenArms.some((arm) => arm.model === model.id);
                  return <Checkbox key={model.id} checked={selected}
                    disabled={create.isPending || !model.available || (!selected && chosenArms.length >= 6)}
                    onChange={(next) => next ? addArm(model.id) : setArms(chosenArms.filter((arm) => arm.model !== model.id))}>
                    <span className="font-body text-sm">{model.label}</span>
                    {!model.available && <span className={cn(META, "block")}>Not enabled in this server</span>}
                  </Checkbox>;
                })}
              </div>
            ))}
          </div>
        </fieldset>
      </div>
      <fieldset className="space-y-3">
        <legend className={META}>Comparison arms and reasoning</legend>
        <p className="font-body text-sm text-ink-muted">Each arm sets a model and reasoning per stage. Higher reasoning can increase latency and token usage; estimates use the source project's recorded tokens.</p>
        {effectiveArms.map((arm) => {
          const model = data.models.find((candidate) => candidate.id === arm.model);
          if (!model) return null;
          return <Surface key={arm.id} padding="sm" shadow="none" border="soft">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-meta text-xs font-bold">{stageArmLabel(model.label, Object.fromEntries(activeStages
                .filter((stage) => stageModel(arm, stage) !== arm.model)
                .map((stage) => [stage, data.models.find((candidate) => candidate.id === stageModel(arm, stage))?.label ?? stageModel(arm, stage)])))} · {arm.id}</p>
              <div className="flex gap-2">
                <Button variant="outline" size="xs" disabled={create.isPending || !model.available || chosenArms.length >= 6}
                  aria-label={`Duplicate ${model.label} ${arm.id}`}
                  onClick={() => addArm(arm.model, arm.reasoning_efforts, arm.stage_models)}>Duplicate arm</Button>
                <Button variant="outline" size="xs" disabled={create.isPending}
                  aria-label={`Remove ${model.label} ${arm.id}`}
                  onClick={() => setArms(chosenArms.filter((candidate) => candidate.id !== arm.id))}>Remove</Button>
              </div>
            </div>
            <p className={cn(META, "mt-1")}>
              {!spendsUsd(arm) ? "subscription allowance" : estimate.data?.estimated_cost_usd[arm.id] != null
                ? `≈${usd(estimate.data.estimated_cost_usd[arm.id], 2)} est.` : "Estimate unavailable"}
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {activeStages.map((stage) => {
                const stageOption = data.models.find((candidate) => candidate.id === stageModel(arm, stage)) ?? model;
                return <div key={stage} className="font-body text-xs">
                  {stage[0].toUpperCase() + stage.slice(1)}
                  <div className="mt-1 grid grid-cols-[minmax(0,2fr)_minmax(0,1fr)] gap-2">
                    <select aria-label={`${model.label} ${arm.id} ${stage} model`} className="w-full border-2 border-ink-black/20 bg-bristol p-2 font-body text-sm"
                      disabled={create.isPending} value={stageOption.id}
                      onChange={(event) => setStageModel(arm.id, stage, event.target.value)}>
                      {data.models.filter((candidate) => candidate.available || candidate.id === stageOption.id).map((candidate) =>
                        <option key={candidate.id} value={candidate.id}>{candidate.label}</option>)}
                    </select>
                    <select aria-label={`${model.label} ${arm.id} ${stage} reasoning`} className="w-full border-2 border-ink-black/20 bg-bristol p-2 font-body text-sm"
                      disabled={create.isPending} value={arm.reasoning_efforts[stage]}
                      onChange={(event) => setArms(chosenArms.map((candidate) => candidate.id === arm.id
                        ? { ...candidate, reasoning_efforts: { ...candidate.reasoning_efforts, [stage]: event.target.value } } : candidate))}>
                      {stageOption.reasoning_options.map((value) => <option key={value} value={value}>{value === "none" ? "Off" : value === "enabled" ? "On" : value[0].toUpperCase() + value.slice(1)}</option>)}
                    </select>
                  </div>
                </div>;
              })}
            </div>
          </Surface>;
        })}
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={!request || create.isPending}
          onClick={() => request && create.mutate(
            { kind: "stage_models", label: `${source?.title} · ${effectiveArms.map((arm) => stageArmLabel(arm.model, arm.stage_models)).join(" vs ")}`, ...request },
            { onSuccess: (run) => onStarted(run.run_id) },
          )}>Run comparison</Button>
        <span className={META}>
          {estimate.isFetching ? "Estimating…" : estimate.error ? String(estimate.error)
            : request ? missingEstimate ? "Estimate unavailable for some API arms; source usage may be missing"
              : `≈${usd(apiTotal, 2)} est. for API arms, priced from this project's recorded tokens`
              : "Choose stages and at least two comparison arms"}
        </span>
        {create.error && <span className="font-body text-sm text-hero-red">{String(create.error)}</span>}
      </div>
    </div>
  );
}

// ── Run views ────────────────────────────────────────────────────────────────

/** A stable per-item shuffle, so blind order survives polling. */
function blindOrder(id: string, size: number): number[] {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) | 0;
  const order = Array.from({ length: size }, (_, index) => index);
  for (let index = size - 1; index > 0; index--) {
    hash = (hash * 1103515245 + 12345) | 0;
    const swap = Math.abs(hash) % (index + 1);
    [order[index], order[swap]] = [order[swap], order[index]];
  }
  return order;
}

/**
 * One arm's image for an item. Every arm of an item is drawn in the same frame,
 * the size the request asked for, so returned sizes don't identify arms. Blind
 * review hides timing, cost, prompt length and file links, which also would.
 */
function ImageResult({ runId, cell, label, frame, blind, onRetry, retrying }: {
  runId: string;
  cell: ImageCell | undefined;
  label: string;
  frame: string | undefined;
  blind: boolean;
  onRetry: (cellId: string) => void;
  retrying: boolean;
}) {
  const inspector = useImageViewer();
  const image = cell?.image ? (
    <img src={labsRunFileUrl(runId, cell.image)} alt={label} className="h-full w-full object-contain" />
  ) : null;
  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <span className="font-meta text-xs font-bold tracking-[0.08em]">{label}</span>
        {cell && <StatusChip status={cell.status} />}
      </figcaption>
      <div className="overflow-hidden border-[2px] border-ink-black bg-pulp-paper" style={{ aspectRatio: aspect(frame) }}>
        {image ? (
          <button type="button" aria-label={`Zoom and inspect · ${label}`} title="Zoom and inspect" className="group relative block h-full w-full cursor-zoom-in"
            onClick={() => inspector.open({ src: labsRunFileUrl(runId, cell!.image!), alt: label, downloadable: !blind })}>
            {image}
            <InspectBadge />
          </button>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-center font-body text-sm text-ink-muted">
            <span>{cell?.status === "failed" ? cell.error : "Generating…"}</span>
            {cell?.status === "failed" && (
              <Button variant="outline" size="sm" disabled={retrying} onClick={() => onRetry(cell.cell_id)}>
                <RotateCcw className="mr-1.5 inline h-4 w-4" aria-hidden />
                Retry{cell.funding === "api" && cell.estimated_cost_usd != null ? ` (≈${usd(cell.estimated_cost_usd)})` : ""}
              </Button>
            )}
          </div>
        )}
      </div>
      {inspector.viewer}
      {cell?.status === "ok" && !blind && (
        <p className={cn(META, "mt-1")}>
          {seconds(routeSeconds(cell))}
          {cell.queue_ms != null && cell.queue_ms >= 1000 ? ` (+${seconds(cell.queue_ms / 1000)} queued)` : ""}
          {" · "}{costWithEquivalent(cell.cost_usd, cell.api_equivalent_usd, cell.funding)}
          {" · "}{sizeLabel(cell.output_size)}{cell.output_size && cell.output_size !== cell.requested_size ? ` (asked ${sizeLabel(cell.requested_size)})` : ""}
          {cell.prompt_file && (
            <> · <a className="font-bold text-hero-red" target="_blank" rel="noreferrer" href={labsRunFileUrl(runId, cell.prompt_file)}>
              {count(cell.prompt_chars)}-char prompt</a></>
          )}
          {cell.attempts?.length ? ` · succeeded on retry ${cell.attempts.length}` : ""}
        </p>
      )}
    </figure>
  );
}

/** Per-cell retries: other failed cells stay retryable while one reruns. */
function useCellRetry(runId: string, failedIds: string[]) {
  const retry = useRetryLabsCells(runId);
  const [submitted, setSubmitted] = useState<ReadonlySet<string>>(new Set());
  // A cell leaves "failed" once its retry starts; until then it stays marked as submitted.
  const pending = new Set(failedIds.filter((id) => submitted.has(id)));
  const retryable = failedIds.filter((id) => !pending.has(id));
  const start = (cells?: string[]) => retry.mutate(cells, {
    onSuccess: (result) => setSubmitted(new Set([...pending, ...result.cells])),
  });
  return {
    error: retry.error,
    retryable,
    canRetry: (cellId: string) => !retry.isPending && retryable.includes(cellId),
    retryCell: (cellId: string) => start([cellId]),
    retryAll: () => start(retryable),
    busy: retry.isPending,
  };
}

function ImageCompareRun({ run, targets }: { run: LabsRunDetail; targets: ImageTarget[] | undefined }) {
  const [blind, setBlind] = useState(true);
  const cells = run.cells as ImageCell[];
  const items = (run.spec.items as string[] | undefined) ?? [];
  const arms = (run.spec.arms as ImageArm[] | undefined) ?? [];
  const retry = useCellRetry(run.run_id, cells.filter((cell) => cell.status === "failed").map((cell) => cell.cell_id));
  const totals = arms.map((arm, index) => {
    const own = cells.filter((cell) => cell.arm === index);
    const done = own.filter((cell) => cell.status === "ok");
    const sum = (pick: (cell: ImageCell) => number | null | undefined) =>
      done.reduce((total, cell) => total + (pick(cell) ?? 0), 0);
    return {
      index,
      arm,
      done: done.length,
      total: items.length,
      failed: own.filter((cell) => cell.status === "failed").length,
      cost: costWithEquivalent(sum((cell) => cell.cost_usd), sum((cell) => cell.api_equivalent_usd), done[0]?.funding ?? targets?.find((t) => t.id === arm.target)?.funding),
      perImage: done.length ? sum((cell) => cell.funding === "api" ? cell.cost_usd : cell.api_equivalent_usd) / done.length : null,
      seconds: median(done.map(routeSeconds)),
    };
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => setBlind(!blind)}>
          {blind ? <Eye className="mr-1.5 inline h-4 w-4" aria-hidden /> : <EyeOff className="mr-1.5 inline h-4 w-4" aria-hidden />}
          {blind ? "Reveal arms" : "Blind review"}
        </Button>
        {retry.retryable.length > 0 && (
          <Button variant="outline" size="sm" disabled={retry.busy} onClick={retry.retryAll}>
            <RotateCcw className="mr-1.5 inline h-4 w-4" aria-hidden />
            Retry {retry.retryable.length} failed
          </Button>
        )}
        <span className={META}>
          {blind ? "Judge each item first; image order is shuffled and every image shares one frame." : "Arms revealed."}
        </span>
      </div>
      {retry.error && <p className="font-body text-sm text-hero-red">{String(retry.error)}</p>}
      {!blind && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse font-body text-sm">
            <thead>
              <tr className={cn(META, "text-left")}>
                <th className="py-1 pr-3 font-normal">Arm</th>
                <th className="py-1 pr-3 font-normal">Done</th>
                <th className="py-1 pr-3 font-normal">Median time</th>
                <th className="py-1 pr-3 font-normal">Per image (API rates)</th>
                <th className="py-1 font-normal">Total</th>
              </tr>
            </thead>
            <tbody>
              {totals.map((total) => (
                <tr key={total.index} className="border-t border-ink-black/10 align-top tabular-nums">
                  <td className="py-1 pr-3"><span className="font-bold">Arm {total.index + 1}</span> · {armName(targets, total.arm)}</td>
                  <td className="py-1 pr-3">{total.done}/{total.total}{total.failed ? ` · ${total.failed} failed` : ""}</td>
                  <td className="py-1 pr-3">{seconds(total.seconds)}</td>
                  <td className="py-1 pr-3">{total.perImage == null ? "—" : `≈${usd(total.perImage)}`}</td>
                  <td className="py-1">{total.cost}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!blind && (
        <p className={META}>
          Subscription arms are priced at API rates for comparison: the same token consumption Canary settles for
          Sunburst at the requested size, since GPT Image 2 has the same rate card. The Codex reasoning model's own
          tokens aren't reported and aren't included.
        </p>
      )}
      {items.map((item) => {
        const order = blind ? blindOrder(item, arms.length) : arms.map((_, index) => index);
        const own = cells.filter((cell) => cell.item === item);
        const frame = own.find((cell) => cell.requested_size)?.requested_size;
        return (
          <section key={item}>
            <h3 className="mb-2 font-display text-base font-bold">{item.replace(":", " ")}</h3>
            <div className={cn("grid gap-4", arms.length > 2 ? "sm:grid-cols-2 xl:grid-cols-4" : "sm:grid-cols-2")}>
              {order.map((index, position) => (
                <ImageResult
                  key={index}
                  runId={run.run_id}
                  cell={own.find((cell) => cell.arm === index)}
                  label={blind ? `Image ${position + 1}` : `Arm ${index + 1} · ${armName(targets, arms[index])}`}
                  frame={frame}
                  blind={blind}
                  retrying={!retry.canRetry(own.find((cell) => cell.arm === index)?.cell_id ?? "")}
                  onRetry={retry.retryCell}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

type Row = { label: string; value: (stage: StageResult | undefined) => string };
const VALIDATION_ROWS = new Set(["Validator attempts", "Invariant failures", "Editorial issues"]);

const STAGE_ROWS: Row[] = [
  { label: "Status", value: (stage) => stage?.status ?? "—" },
  { label: "Time", value: (stage) => seconds(stage?.seconds) },
  {
    label: "Spend (measured)",
    value: (stage) => stage
      ? spend(stage.cost_usd, stage.funding.find((funding) => funding !== "api") ?? "api") + (stage.unpriced_calls ? ` + ${stage.unpriced_calls} unpriced` : "")
      : "—",
  },
  { label: "At API rates", value: (stage) => (stage?.api_equivalent_usd == null ? "—" : `≈${usd(stage.api_equivalent_usd)}`) },
  { label: "Calls", value: (stage) => count(stage?.calls) },
  { label: "Input tokens", value: (stage) => stage ? `${count(stage.input_tokens)}${stage.cached_input_tokens ? ` (${count(stage.cached_input_tokens)} cached)` : ""}` : "—" },
  { label: "Output tokens", value: (stage) => count(stage?.output_tokens) },
  { label: "Validator attempts", value: (stage) => count(stage?.validation?.attempts) },
  { label: "Invariant failures", value: (stage) => count(stage?.validation?.invariant_failures) },
  { label: "Editorial issues", value: (stage) => stage?.validation ? `${stage.validation.editorial_issues} (${stage.validation.blocking_issues} blocking)` : "—" },
];

function StageTable({ run, stageName, cells }: { run: LabsRunDetail; stageName: string; cells: StageModelCell[] }) {
  const results = cells.map((cell) => cell.stages.find((stage) => stage.stage === stageName));
  const countKeys = [...new Set(results.flatMap((stage) => Object.keys(stage?.counts ?? {})))];
  const validated = results.some((stage) => stage?.validation);
  const rows: Row[] = [
    ...STAGE_ROWS.filter((row) => validated || !VALIDATION_ROWS.has(row.label)),
    ...countKeys.map((key) => ({ label: key.replaceAll("_", " "), value: (stage: StageResult | undefined) => count(stage?.counts?.[key]) })),
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-collapse font-body text-sm">
        <caption className="mb-1 text-left font-display text-sm font-bold capitalize">{stageName}</caption>
        <thead>
          <tr className="border-b-[2px] border-ink-black">
            <th className={cn(META, "py-1.5 pr-3 text-left font-normal")}>Metric</th>
            {cells.map((cell) => <th key={cell.cell_id} className="py-1.5 pr-3 text-left font-meta text-xs font-bold">{cell.stage_models?.[stageName] ?? cell.model}{cell.variant && ` · ${cell.variant}`}
              {cell.reasoning_efforts?.[stageName] && <span className="block font-normal text-ink-muted">{cell.reasoning_efforts[stageName]} reasoning</span>}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-ink-black/10">
              <td className={cn(META, "py-1.5 pr-3 capitalize")}>{row.label}</td>
              {cells.map((cell, index) => (
                <td key={cell.cell_id} className="py-1.5 pr-3 tabular-nums">{row.value(results[index])}</td>
              ))}
            </tr>
          ))}
          <tr>
            <td className={cn(META, "py-1.5 pr-3")}>Output</td>
            {cells.map((cell, index) => {
              const stage = results[index];
              return (
                <td key={cell.cell_id} className="py-1.5 pr-3">
                  {stage?.error ? <span className="text-hero-red">{stage.error}</span>
                    : stage?.artifact ? (
                      <a className="font-meta text-xs font-bold text-hero-red" target="_blank" rel="noreferrer"
                        href={labsRunFileUrl(run.run_id, `${cell.workspace}/${stage.artifact}`)}>
                        Open {stage.artifact.split("/").pop()}
                      </a>
                    ) : "—"}
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function StageModelsRun({ run }: { run: LabsRunDetail }) {
  const cells = run.cells as StageModelCell[];
  const phases = (run.spec.phases as string[] | undefined) ?? [];
  const estimate = run.spec.estimated_cost_usd as Record<string, number | null> | undefined;
  const retry = useCellRetry(run.run_id, cells.filter((cell) => cell.status === "failed").map((cell) => cell.cell_id));
  return (
    <div className="space-y-8">
      {(retry.retryable.length > 0 || !!retry.error) && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            {retry.retryable.length > 0 && <Button variant="outline" size="sm" disabled={retry.busy} onClick={retry.retryAll}>
              <RotateCcw className="mr-1.5 inline h-4 w-4" aria-hidden />
              Retry {retry.retryable.length} failed
            </Button>}
            <span className={META}>A retry reruns the arm's whole phase from the same source inputs.</span>
          </div>
          {retry.error && <p className="font-body text-sm text-hero-red">{String(retry.error)}</p>}
        </div>
      )}
      {phases.map((phase) => {
        const phaseCells = cells.filter((cell) => cell.phase === phase);
        const stages = [...new Set(phaseCells.flatMap((cell) => cell.stages.map((stage) => stage.stage)))];
        return (
          <section key={phase} className="space-y-4">
            <h3 className="font-display text-lg font-bold">{PHASE_LABEL[phase] ?? phase}</h3>
            <div className="grid gap-2 sm:grid-cols-2">
              {phaseCells.map((cell) => (
                <Surface key={cell.cell_id} padding="sm" shadow="none" border="soft">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-meta text-xs font-bold">{stageArmLabel(cell.model, cell.stage_models)}{cell.variant && ` · ${cell.variant}`}<FundingTag funding={cell.funding} /></span>
                    <StatusChip status={cell.status} />
                  </div>
                  <p className="mt-1 font-body text-sm tabular-nums">
                    {seconds(cell.seconds ?? cell.stages.reduce((sum, stage) => sum + stage.seconds, 0))} ·{" "}
                    {costWithEquivalent(cell.cost_usd ?? cell.stages.reduce((sum, stage) => sum + stage.cost_usd, 0), cell.api_equivalent_usd, cell.funding)}
                    {cell.funding === "api" ? " measured" : ""}
                    {cell.funding === "api" && (estimate?.[cell.variant ?? cell.model] ?? estimate?.[cell.model]) != null && (
                      <span className="text-ink-muted"> · ≈{usd(estimate?.[cell.variant ?? cell.model] ?? estimate?.[cell.model], 2)} est. for all phases</span>
                    )}
                  </p>
                  {cell.reasoning_efforts && <p className="mt-1 font-body text-xs text-ink-muted">Reasoning: {Object.entries(cell.reasoning_efforts).map(([stage, effort]) => `${stage}: ${effort === "none" ? "Off" : effort === "enabled" ? "On" : effort}`).join(" · ")}</p>}
                  {cell.error && <p className="mt-1 font-body text-sm text-hero-red">{cell.error}</p>}
                  {!!cell.attempts?.length && (
                    <p className="mt-1 font-body text-xs text-ink-muted tabular-nums">
                      {cell.status === "ok" ? `Succeeded on retry ${cell.attempts.length}` : `${cell.attempts.length} earlier attempt${cell.attempts.length > 1 ? "s" : ""}`}
                      {" · earlier spend "}
                      {costWithEquivalent(
                        cell.attempts.reduce((sum, attempt) => sum + (attempt.cost_usd ?? 0), 0),
                        cell.attempts.some((attempt) => attempt.api_equivalent_usd == null)
                          ? null : cell.attempts.reduce((sum, attempt) => sum + (attempt.api_equivalent_usd ?? 0), 0),
                        cell.funding,
                      )}
                    </p>
                  )}
                  {cell.status === "failed" && (
                    <Button className="mt-2" variant="outline" size="sm" disabled={!retry.canRetry(cell.cell_id)} onClick={() => retry.retryCell(cell.cell_id)}>
                      <RotateCcw className="mr-1.5 inline h-4 w-4" aria-hidden />
                      Retry
                    </Button>
                  )}
                </Surface>
              ))}
            </div>
            {stages.map((stage) => <StageTable key={stage} run={run} stageName={stage} cells={phaseCells} />)}
          </section>
        );
      })}
    </div>
  );
}

function RunView({ runId, onDeleted }: { runId: string; onDeleted: () => void }) {
  const { data: run, error } = useLabsRun(runId);
  const options = useImageCompareOptions();
  const remove = useDeleteLabsRun();
  if (error) return <p className="font-body text-sm text-hero-red">{String(error)}</p>;
  if (!run) return <p className={META}>Loading run…</p>;
  const running = run.cells.filter((cell) => cell.status === "running").length;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <StatusChip status={run.status} />
            <span className={META}>{KIND_LABEL[run.kind] ?? run.kind} · {relTime(run.created_at)}</span>
          </div>
          <h2 className="mt-1 font-display text-xl font-bold">{run.label}</h2>
          <p className={cn(META, "mt-1")}>
            {usd(run.total_cost_usd)} API spend measured so far{running ? ` · ${running} running` : ""}
          </p>
          {run.error && <p className="mt-1 font-body text-sm text-hero-red">{run.error}</p>}
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(run.status === "running" ? "Stop and delete this run? Calls already sent may still be billed." : "Delete this run and its files?")) {
              remove.mutate(run.run_id, { onSuccess: onDeleted });
            }
          }}
        >
          <Trash2 className="mr-1.5 inline h-4 w-4" aria-hidden />
          Delete
        </Button>
      </div>
      {run.kind === "image_compare"
        ? <ImageCompareRun run={run} targets={options.data?.targets} />
        : run.kind === "modernize" ? <ModernizeRun run={run} /> : <StageModelsRun run={run} />}
    </div>
  );
}

// ── Modernize source ─────────────────────────────────────────────────────────

const INTENSITY_LABEL: Record<ModernizeIntensity, [string, string]> = {
  light: ["Light", "Archaic words and forms only; sentences keep their shape."],
  moderate: ["Moderate", "Also rephrases stiff or obsolete constructions, keeping the author's rhythm."],
  contemporary: ["Contemporary", "Present-day English with short, restructured sentences; usually 10–20% shorter, every beat kept."],
};
const SCOPE_LABEL: Record<ModernizeScope, [string, string]> = {
  dialogue: ["Dialogue", "Only text inside quotation marks changes."],
  narration: ["Narration", "Only text outside quotation marks changes."],
  both: ["Both", "Dialogue and narration."],
};
const SENSITIVE_LABEL: Record<ModernizeSensitive, [string, string]> = {
  keep: ["Keep, flag", "Offensive language stays as written and is listed for review."],
  soften: ["Soften", "Slurs become neutral terms; the speaker's attitude still shows."],
  remove: ["Remove", "Prejudice is shown by action or implication instead of voiced."],
};
const CATEGORY_TONE: Record<ModernizeChange["category"], string> = {
  archaic: "bg-pulp-paper text-ink-black",
  offensive: "bg-hero-red text-bristol",
  clarity: "bg-ink-black text-bristol",
  idiom: "bg-narrator-gold text-ink-black",
  tightened: "bg-pulp-paper text-ink-muted",
  inferred: "bg-narrator-gold text-ink-black",
};
const DEFAULT_CONTROLS: ModernizeControls = {
  intensity: "moderate", scope: "both", sensitive: "soften", keep_setting: true, comic_ready: true, notes: "",
};

function Segmented<T extends string>({ label, value, options, labels, disabled, onChange }: {
  label: string; value: T; options: T[]; labels: Record<T, [string, string]>; disabled?: boolean; onChange: (next: T) => void;
}) {
  return (
    <fieldset>
      <legend className={META}>{label}</legend>
      <div className="mt-1 flex flex-wrap gap-1.5" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <Button key={option} size="xs" role="radio" aria-checked={value === option} disabled={disabled}
            variant={value === option ? "secondary" : "outline"} onClick={() => onChange(option)}>
            {labels[option][0]}
          </Button>
        ))}
      </div>
      <p className="mt-1 font-body text-xs text-ink-muted">{labels[value][1]}</p>
    </fieldset>
  );
}

function ModernizeSetup({ projects, onStarted }: { projects: LabsProject[]; onStarted: (runId: string) => void }) {
  const { data, isLoading, isFetching, error, refetch } = useModernizeOptions();
  const create = useCreateLabsRun();
  const [picked, setProject] = useState("");
  const project = picked || projects[0]?.id || "";
  const source = projects.find((candidate) => candidate.id === project);
  const [mode, setMode] = useState<"excerpt" | "paste">("excerpt");
  const [start, setStart] = useState(0);
  const [maxWords, setMaxWords] = useState(1200);
  const [pasted, setPasted] = useState("");
  const [controls, setControls] = useState<ModernizeControls>(DEFAULT_CONTROLS);
  const [arms, setArms] = useState<ModernizeArm[] | null>(null);
  const chosenArms = arms ?? (data?.models.filter((model) => model.available).slice(0, 1) ?? [])
    .map<ModernizeArm>((model) => ({ id: "arm-1", model: model.id }));
  const excerptQuery = mode === "excerpt" && source ? { part_id: source.part_id, start, max_words: maxWords } : null;
  const excerpt = useModernizeExcerpt(project, excerptQuery);
  const sourceBody: ModernizeSource | null = mode === "paste"
    ? (pasted.trim() ? { text: pasted } : null)
    : excerptQuery;
  const request = source && sourceBody && chosenArms.length
    ? { project, controls, arms: chosenArms, ...sourceBody } : null;
  const estimate = useModernizeEstimate(request);
  const providers = useMemo(() => {
    const groups = new Map<string, StageModelOption[]>();
    for (const model of data?.models ?? []) groups.set(model.provider, [...(groups.get(model.provider) ?? []), model]);
    return [...groups.entries()];
  }, [data]);

  if (error) return <LoadError error={error} retrying={isFetching} onRetry={() => void refetch()} />;
  if (isLoading || !data) return <p className={META}>Loading models…</p>;

  const busy = create.isPending;
  const modelOption = (id: string) => data.models.find((candidate) => candidate.id === id);
  const addArm = (model: string) => {
    const next = Math.max(0, ...chosenArms.map((arm) => Number(arm.id.replace("arm-", "")))) + 1;
    setArms([...chosenArms, { id: `arm-${next}`, model }]);
  };
  const apiTotal = Object.values(estimate.data?.estimated_cost_usd ?? {}).reduce<number>((total, value) => total + (value ?? 0), 0);
  const words = (text: string) => text.split(/\s+/).filter(Boolean).length;
  const pastedWords = words(pasted);

  return (
    <div className="space-y-5">
      <p className="max-w-3xl font-body text-sm leading-6 text-ink-muted">
        Rewrites a passage&apos;s archaic, obscure or offensive language for today&apos;s readers, once per model, and
        shows each version beside the original with a word diff and the changes worth a second look: offensive language, inferred details and cuts. Plot, names and each character&apos;s attitude
        are kept; only the wording changes. Your project is only read.
      </p>
      <ProjectPicker projects={projects} value={project} onChange={(next) => { setProject(next); setStart(0); }} />
      <fieldset className="space-y-3">
        <legend className={META}>Passage</legend>
        <div className="flex flex-wrap gap-1.5">
          <Button size="xs" variant={mode === "excerpt" ? "secondary" : "outline"} onClick={() => setMode("excerpt")}>From manuscript</Button>
          <Button size="xs" variant={mode === "paste" ? "secondary" : "outline"} onClick={() => setMode("paste")}>Paste text</Button>
        </div>
        {mode === "excerpt" ? (
          <div className="space-y-2">
            <div className="flex flex-wrap items-end gap-3">
              <label className="font-body text-xs">
                Start paragraph
                <input type="number" min={1} max={excerpt.data?.total_paragraphs ?? undefined} value={start + 1}
                  aria-label="Start paragraph" disabled={busy}
                  onChange={(event) => setStart(Math.max(0, Number(event.target.value || 1) - 1))}
                  className="mt-1 block w-28 border-2 border-ink-black/20 bg-bristol p-2 font-body text-sm" />
              </label>
              <label className="font-body text-xs">
                Up to words
                <input type="number" min={100} max={data.max_words} step={100} value={maxWords}
                  aria-label="Up to words" disabled={busy}
                  onChange={(event) => setMaxWords(Math.min(data.max_words, Math.max(1, Number(event.target.value || 1))))}
                  className="mt-1 block w-28 border-2 border-ink-black/20 bg-bristol p-2 font-body text-sm" />
              </label>
              <Button size="sm" variant="outline" disabled={busy || start === 0} onClick={() => setStart(Math.max(0, start - (excerpt.data ? excerpt.data.end - excerpt.data.start : 1)))}>Previous passage</Button>
              <Button size="sm" variant="outline" disabled={busy || !excerpt.data || excerpt.data.end >= excerpt.data.total_paragraphs}
                onClick={() => excerpt.data && setStart(excerpt.data.end)}>Next passage</Button>
            </div>
            {excerpt.error ? <p className="font-body text-sm text-hero-red">{String(excerpt.error)}</p> : excerpt.data && (
              <>
                <p className={META}>
                  Paragraphs {excerpt.data.start + 1}–{excerpt.data.end} of {count(excerpt.data.total_paragraphs)} ·{" "}
                  {count(excerpt.data.words)} words of {count(excerpt.data.total_words)}
                </p>
                <div className="max-h-72 space-y-2 overflow-y-auto border-2 border-ink-black/10 bg-bristol p-3 font-body text-sm leading-6">
                  {excerpt.data.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
                </div>
              </>
            )}
          </div>
        ) : (
          <div>
            <textarea aria-label="Passage text" rows={10} value={pasted} disabled={busy}
              onChange={(event) => setPasted(event.target.value)}
              placeholder="Paste a passage. Separate paragraphs with a blank line."
              className="block w-full border-2 border-ink-black/20 bg-bristol p-3 font-body text-sm leading-6" />
            <p className={cn(META, "mt-1", pastedWords > data.max_words && "text-hero-red")}>
              {count(pastedWords)} / {count(data.max_words)} words
            </p>
          </div>
        )}
      </fieldset>
      <div className="grid gap-5 md:grid-cols-3">
        <Segmented label="Intensity" value={controls.intensity} options={data.intensities} labels={INTENSITY_LABEL}
          disabled={busy} onChange={(intensity) => setControls({ ...controls, intensity })} />
        <Segmented label="Scope" value={controls.scope} options={data.scopes} labels={SCOPE_LABEL}
          disabled={busy} onChange={(scope) => setControls({ ...controls, scope })} />
        <Segmented label="Offensive language" value={controls.sensitive} options={data.sensitive} labels={SENSITIVE_LABEL}
          disabled={busy} onChange={(sensitive) => setControls({ ...controls, sensitive })} />
      </div>
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <div>
          <Checkbox checked={controls.comic_ready} disabled={busy}
            onChange={(comic_ready) => setControls({ ...controls, comic_ready })}>
            <span className="font-body text-sm font-bold">Comic-ready</span>
            <span className={cn(META, "block")}>Short, speakable dialogue that keeps tone cues for the artist; drawable narration; additions and cuts listed for review.</span>
          </Checkbox>
          <Checkbox checked={controls.keep_setting} disabled={busy}
            onChange={(keep_setting) => setControls({ ...controls, keep_setting })}>
            <span className="font-body text-sm font-bold">Keep the period setting</span>
            <span className={cn(META, "block")}>No modern technology, slang or references the original setting couldn&apos;t have.</span>
          </Checkbox>
        </div>
        <label className="font-body text-xs">
          <span className={META}>Direction (optional)</span>
          <textarea aria-label="Direction" rows={2} maxLength={1000} value={controls.notes} disabled={busy}
            onChange={(event) => setControls({ ...controls, notes: event.target.value })}
            placeholder="e.g. Keep Holmes formal; Watson can sound casual."
            className="mt-1 block w-full border-2 border-ink-black/20 bg-bristol p-2 font-body text-sm" />
        </label>
      </div>
      <fieldset>
        <legend className={META}>Models (1–{data.max_arms})</legend>
        <div className="grid gap-x-5 sm:grid-cols-2 lg:grid-cols-3">
          {providers.map(([provider, group]) => (
            <div key={provider} className="mt-2">
              <div className="font-meta text-xs font-bold">{provider}</div>
              {group.map((model) => {
                const selected = chosenArms.some((arm) => arm.model === model.id);
                return <Checkbox key={model.id} checked={selected}
                  disabled={busy || !model.available || (!selected && chosenArms.length >= data.max_arms)}
                  onChange={(next) => next ? addArm(model.id) : setArms(chosenArms.filter((arm) => arm.model !== model.id))}>
                  <span className="font-body text-sm">{model.label}</span>
                  {!model.available && <span className={cn(META, "block")}>Not enabled in this server</span>}
                </Checkbox>;
              })}
            </div>
          ))}
        </div>
      </fieldset>
      {chosenArms.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {chosenArms.map((arm) => {
            const model = modelOption(arm.model);
            if (!model) return null;
            const reasoning = arm.reasoning ?? model.default_reasoning;
            const estimated = estimate.data?.estimated_cost_usd[arm.id];
            const basis = estimate.data?.estimate_basis[arm.id];
            return <Surface key={arm.id} padding="sm" shadow="none" border="soft">
              <div className="flex items-center justify-between gap-2">
                <span className="font-meta text-xs font-bold">{model.label}<FundingTag funding={model.funding} /></span>
                <span className={META}>
                  {model.funding !== "api" ? "subscription" : estimated != null ? `≈${usd(estimated, 3)} est.` : "—"}
                  {basis?.basis === "history" && ` · from ${basis.runs} past run${basis.runs > 1 ? "s" : ""}`}
                </span>
              </div>
              <label className="mt-2 block font-body text-xs">
                Reasoning
                <select aria-label={`${model.label} reasoning`} value={reasoning} disabled={busy}
                  onChange={(event) => setArms(chosenArms.map((candidate) => candidate.id === arm.id ? { ...candidate, reasoning: event.target.value } : candidate))}
                  className="mt-1 block w-full border-2 border-ink-black/20 bg-bristol p-2 font-body text-sm">
                  {model.reasoning_options.map((value) => <option key={value} value={value}>{value === "none" ? "Off" : value === "enabled" ? "On" : value[0].toUpperCase() + value.slice(1)}</option>)}
                </select>
              </label>
            </Surface>;
          })}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={!request || busy || (mode === "paste" && pastedWords > data.max_words)}
          onClick={() => request && create.mutate(
            {
              kind: "modernize",
              label: `${source?.title} · ${INTENSITY_LABEL[controls.intensity][0]} · ${chosenArms.map((arm) => modelOption(arm.model)?.label ?? arm.model).join(" vs ")}`,
              ...request,
            },
            { onSuccess: (run) => onStarted(run.run_id) },
          )}>Modernize passage</Button>
        <span className={META}>
          {estimate.isFetching ? "Estimating…" : estimate.error ? String(estimate.error)
            : estimate.data ? `≈${usd(apiTotal, 3)} est. for API models · ${count(estimate.data.words)} words in ${estimate.data.paragraphs} paragraphs`
              : "Choose a passage and at least one model"}
        </span>
        {create.error && <span className="font-body text-sm text-hero-red">{String(create.error)}</span>}
      </div>
    </div>
  );
}

function DiffText({ before, after, showDiff }: { before: string; after: string; showDiff: boolean }) {
  if (!showDiff || before === after) return <>{after}</>;
  return <>{wordDiff(before, after).map((segment, index) => segment.kind === "same" ? <span key={index}>{segment.text}</span>
    : segment.kind === "added" ? <ins key={index} className="bg-narrator-gold/40 no-underline">{segment.text}</ins>
      : <del key={index} className="text-hero-red/80">{segment.text}</del>)}</>;
}

/** Copy or download one model's clean text, to start a new production from it. */
function ModernizedTextActions({ title, cell }: { title: string; cell: ModernizeCell }) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const text = modernizedText(cell.paragraphs ?? []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
    window.setTimeout(() => setCopied("idle"), 2000);
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: modernizedFilename(title, cell.model) });
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" aria-label={`Copy ${cell.model} text`} onClick={() => void copy()}>
        {copied === "copied" ? <Check className="mr-1.5 inline h-4 w-4" aria-hidden /> : <Copy className="mr-1.5 inline h-4 w-4" aria-hidden />}
        {copied === "copied" ? "Copied" : "Copy text"}
      </Button>
      <Button variant="outline" size="sm" aria-label={`Download ${cell.model} text`} onClick={download}>
        <Download className="mr-1.5 inline h-4 w-4" aria-hidden />
        .txt
      </Button>
      {copied === "failed" && <span className="font-body text-xs text-hero-red">Clipboard blocked; use .txt</span>}
    </div>
  );
}

function ModernizeRun({ run }: { run: LabsRunDetail }) {
  const source = useModernizeSource(run.run_id);
  const [showDiff, setShowDiff] = useState(true);
  const [changedOnly, setChangedOnly] = useState(false);
  const controls = run.spec.controls as ModernizeControls | undefined;
  const order = ((run.spec.arms as ModernizeArm[] | undefined) ?? []).map((arm) => arm.id);
  const cells = (run.cells as ModernizeCell[]).slice().sort((a, b) => order.indexOf(a.cell_id) - order.indexOf(b.cell_id));
  const retry = useCellRetry(run.run_id, cells.filter((cell) => cell.status === "failed").map((cell) => cell.cell_id));
  const original = source.data?.paragraphs ?? [];
  const done = cells.filter((cell) => cell.status === "ok" && cell.paragraphs);
  const projects = useLabsProjects();
  const projectTitle = projects.data?.projects.find((project) => project.id === run.spec.project)?.title
    ?? String(run.spec.project ?? "");
  const rows = original.map((text, index) => ({ index, text }))
    .filter((row) => !changedOnly || done.some((cell) => cell.paragraphs![row.index] !== row.text));

  return (
    <div className="space-y-6">
      {controls && (
        <p className={META}>
          {INTENSITY_LABEL[controls.intensity][0]} · {SCOPE_LABEL[controls.scope][0]} · Offensive language:{" "}
          {SENSITIVE_LABEL[controls.sensitive][0]} · {controls.keep_setting ? "Period setting kept" : "Modern idiom allowed"}
          {controls.comic_ready && " · Comic-ready"}
          {controls.notes && <span className="block normal-case tracking-normal">Direction: {controls.notes}</span>}
        </p>
      )}
      {retry.error && <p className="font-body text-sm text-hero-red">{String(retry.error)}</p>}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {cells.map((cell) => {
          const checks = cell.checks;
          const byCategory = (cell.changes ?? []).reduce<Record<string, number>>((totals, change) =>
            ({ ...totals, [change.category]: (totals[change.category] ?? 0) + 1 }), {});
          return <Surface key={cell.cell_id} padding="sm" shadow="none" border="soft">
            <div className="flex items-center justify-between gap-2">
              <span className="font-meta text-xs font-bold">{cell.model}<FundingTag funding={cell.funding} /></span>
              <StatusChip status={cell.status} />
            </div>
            <p className="mt-1 font-body text-sm tabular-nums">
              {seconds(cell.seconds)} · {costWithEquivalent(cell.cost_usd, cell.usage?.api_equivalent_usd, cell.funding)}
            </p>
            {checks && (
              <ul className="mt-1 space-y-0.5 font-body text-xs tabular-nums">
                <li>{checks.changed_paragraphs} of {original.length || "—"} paragraphs changed · {count(checks.words_before)} → {count(checks.words_after)} words</li>
                <li>{Object.entries(byCategory).map(([category, total]) => `${total} ${category}`).join(" · ") || "No notable changes listed"}</li>
                {checks.comic_before && checks.comic_after && <>
                  <li>Sentences {checks.comic_before.avg_sentence_words} → {checks.comic_after.avg_sentence_words} words on average</li>
                  <li>Longest speech {checks.comic_before.longest_speech_words} → {checks.comic_after.longest_speech_words} words · {checks.comic_before.long_speeches} → {checks.comic_after.long_speeches} over 25</li>
                </>}
                {checks.scope_violations.length > 0 && <li className="text-hero-red">Edited outside scope: ¶{checks.scope_violations.map((index) => index + 1).join(", ")}</li>}
                {checks.missing_paragraphs.length > 0 && <li className="text-hero-red">Dropped ¶{checks.missing_paragraphs.map((index) => index + 1).join(", ")} (original kept)</li>}
              </ul>
            )}
            {cell.status === "ok" && cell.paragraphs && <ModernizedTextActions title={projectTitle} cell={cell} />}
            {cell.error && <p className="mt-1 font-body text-sm text-hero-red">{cell.error}</p>}
            {cell.status === "failed" && (
              <Button className="mt-2" variant="outline" size="sm" disabled={!retry.canRetry(cell.cell_id)} onClick={() => retry.retryCell(cell.cell_id)}>
                <RotateCcw className="mr-1.5 inline h-4 w-4" aria-hidden />
                Retry
              </Button>
            )}
          </Surface>;
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => setShowDiff(!showDiff)}>{showDiff ? "Clean text" : "Show changes"}</Button>
        <Button variant="outline" size="sm" onClick={() => setChangedOnly(!changedOnly)}>{changedOnly ? "All paragraphs" : "Changed paragraphs only"}</Button>
        <span className={META}>{showDiff ? "Additions highlighted; removals struck through." : "Clean text, as a reader would see it."}</span>
      </div>
      {source.error && <p className="font-body text-sm text-hero-red">{String(source.error)}</p>}
      <div className="overflow-x-auto">
        <div className="grid gap-x-4 font-body text-sm leading-6"
          style={{ gridTemplateColumns: `2.5rem repeat(${1 + cells.length}, minmax(240px, 1fr))`, minWidth: `${(1 + cells.length) * 250}px` }}>
          <div />
          <div className={cn(META, "sticky top-0 pb-2")}>Original</div>
          {cells.map((cell) => <div key={cell.cell_id} className={cn(META, "pb-2")}>{cell.model}</div>)}
          {rows.map((row) => (
            <Fragment key={row.index}>
              <div className={cn(META, "border-t border-ink-black/10 py-2")}>¶{row.index + 1}</div>
              <p className="border-t border-ink-black/10 py-2 text-ink-muted">{row.text}</p>
              {cells.map((cell) => {
                const revised = cell.paragraphs?.[row.index];
                const flagged = cell.checks?.scope_violations.includes(row.index) || cell.checks?.missing_paragraphs.includes(row.index);
                return <p key={cell.cell_id} className={cn("border-t border-ink-black/10 py-2", flagged && "border-l-[3px] border-l-hero-red pl-2")}>
                  {revised == null ? <span className={META}>{cell.status === "running" ? "Running…" : "—"}</span>
                    : <DiffText before={row.text} after={revised} showDiff={showDiff} />}
                </p>;
              })}
            </Fragment>
          ))}
        </div>
      </div>
      {done.map((cell) => (
        <details key={cell.cell_id} className="border-t-2 border-ink-black/10 pt-3">
          <summary className="cursor-pointer font-meta text-xs font-bold">{cell.model} · {cell.changes?.length ?? 0} notable changes</summary>
          <ul className="mt-2 space-y-2">
            {(cell.changes ?? []).map((change, index) => (
              <li key={index} className="font-body text-sm">
                <span className={cn("mr-2 inline-block px-1.5 py-0.5 font-meta text-[0.68rem] font-bold uppercase tracking-[0.1em]", CATEGORY_TONE[change.category])}>{change.category}</span>
                {change.paragraph != null && <span className={cn(META, "mr-2")}>¶{change.paragraph + 1}</span>}
                <del className="text-hero-red/80">{change.original}</del>{" → "}
                {change.revised ? <ins className="bg-narrator-gold/40 no-underline">{change.revised}</ins> : <span className={META}>cut</span>}
                {change.note && <span className="block text-xs text-ink-muted">{change.note}</span>}
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}

// ── Room ─────────────────────────────────────────────────────────────────────

type View = LabsRunSummary["kind"];

export function LabsRoom() {
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") ?? undefined;
  const view = (params.get("new") as View | null) ?? (runId ? null : "image_compare");
  const runs = useLabsRuns();
  const projects = useLabsProjects();
  const open = (next: Record<string, string>) => setParams(next);

  return (
    <div className="mx-auto w-full min-w-0 max-w-[1400px] px-4 py-6 md:px-8">
      <SectionHeader
        kicker="Local development"
        title="Labs"
        description="Model experiments on your own projects. API calls cost operator USD; subscription calls use your Claude or Codex allowance. Never account credits."
      />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="min-w-0 space-y-5">
          <nav aria-label="New experiment" className="grid gap-2">
            {(["image_compare", "stage_models", "modernize"] as const).map((kind) => (
              <Button key={kind} variant={view === kind ? "primary" : "outline"} size="sm" onClick={() => open({ new: kind })}>
                New {KIND_LABEL[kind]}
              </Button>
            ))}
          </nav>
          <div>
            <div className={META}>Runs</div>
            <ul className="mt-2 space-y-1">
              {(runs.data?.runs ?? []).map((run) => (
                <li key={run.run_id}>
                  <button
                    type="button"
                    onClick={() => open({ run: run.run_id })}
                    className={cn(
                      "block min-h-11 w-full border-l-[3px] px-2.5 py-1.5 text-left hover:bg-pulp-paper",
                      run.run_id === runId ? "border-hero-red bg-pulp-paper" : "border-transparent",
                    )}
                  >
                    <span className="block truncate font-body text-sm font-bold">{run.label}</span>
                    <span className={cn(META, "flex items-center gap-2")}>
                      <StatusChip status={run.status} /> {relTime(run.created_at)} · {usd(run.total_cost_usd, 2)}
                    </span>
                  </button>
                </li>
              ))}
              {runs.data && runs.data.runs.length === 0 && <li className="font-body text-sm text-ink-muted">No runs yet.</li>}
            </ul>
          </div>
        </aside>
        <main className="min-w-0">
          {view && projects.error && (
            <LoadError error={projects.error} retrying={projects.isFetching} onRetry={() => void projects.refetch()} />
          )}
          {view && projects.isLoading && <p className={META}>Loading projects…</p>}
          {view && projects.data && projects.data.projects.length === 0 && (
            <p className="font-body text-sm text-ink-muted">No projects to experiment on yet.</p>
          )}
          {view === "image_compare" && !!projects.data?.projects.length && (
            <ImageCompareSetup projects={projects.data.projects} onStarted={(id) => open({ run: id })} />
          )}
          {view === "stage_models" && !!projects.data?.projects.length && (
            <StageModelsSetup projects={projects.data.projects} onStarted={(id) => open({ run: id })} />
          )}
          {view === "modernize" && !!projects.data?.projects.length && (
            <ModernizeSetup projects={projects.data.projects} onStarted={(id) => open({ run: id })} />
          )}
          {!view && runId && <RunView runId={runId} onDeleted={() => open({ new: "image_compare" })} />}
        </main>
      </div>
    </div>
  );
}
