import { useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, Eye, EyeOff, Plus, RotateCcw, Trash2, X } from "lucide-react";
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
} from "../api/queries";
import {
  labsRunFileUrl,
  type ImageArm,
  type ImageCell,
  type ImagePrompt,
  type ImageTarget,
  type LabsFunding,
  type LabsProject,
  type LabsRunDetail,
  type LabsRunSummary,
  type StageModelCell,
  type LabsReasoning,
  type StageResult,
} from "../api/labs";
import { SectionHeader } from "../components/composites";
import { Button } from "../components/ui/Button";
import { Select } from "../components/ui/Select";
import { Surface } from "../components/ui/Surface";
import { cn } from "../lib/cn";

/*
 * Labs is a local-development room for model experiments on the operator's own
 * projects. API calls cost provider USD paid by the operator; subscription calls
 * use the local Claude or Codex allowance. Neither ever touches account credits,
 * and estimates are always labelled apart from measured amounts.
 */

const PHASE_LABEL: Record<string, string> = {
  extract_brief: "Extract + Brief",
  adapt_plan: "Adapt + Plan",
};
const KIND_LABEL: Record<LabsRunSummary["kind"], string> = {
  image_compare: "Image comparison",
  stage_models: "Stage models",
};
const PROMPT_LABEL: Record<ImagePrompt, string> = {
  production: "Production prompt",
  restructured: "Restructured prompt",
};
const DEFAULT_ARMS: ImageArm[] = [
  { target: "sunburst-openai", prompt: "production" },
  { target: "sunburst-openai", prompt: "restructured" },
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
  return `${targetName(targets, arm.target)} · ${PROMPT_LABEL[arm.prompt]}`;
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
            className="min-w-[16rem] flex-1"
            aria-label={`Arm ${index + 1} model and route`}
            value={arm.target}
            onValueChange={(target) => update(index, { target })}
            options={targets.map((target) => ({
              value: target.id,
              label: `${target.label} · ${target.provider}${target.available ? "" : " (not enabled)"}`,
              disabled: !target.available,
            }))}
          />
          <Select
            className="min-w-[12rem]"
            aria-label={`Arm ${index + 1} prompt`}
            value={arm.prompt}
            onValueChange={(prompt) => update(index, { prompt: prompt as ImagePrompt })}
            options={(Object.keys(PROMPT_LABEL) as ImagePrompt[]).map((prompt) => ({ value: prompt, label: PROMPT_LABEL[prompt] }))}
          />
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
        request restated scene-first, with anchors, style and lettering kept word for word.
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
  const armsValid = new Set(arms.map((arm) => `${arm.target}|${arm.prompt}`)).size === arms.length;
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
      {!armsValid && <p className="font-body text-sm text-hero-red">Each arm must differ in model, route or prompt.</p>}
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
                <img src={`/api/projects/${encodeURIComponent(project)}/files/${item.preview}`} alt=""
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
  const [models, setModels] = useState<string[] | null>(null);
  const [reasoningDraft, setReasoning] = useState<LabsReasoning>({});
  const chosenModels = models ?? data?.default_models ?? [];
  const source = projects.find((candidate) => candidate.id === project);
  const adaptReady = !!source && ["brief", "style", "cast"].every((stage) => READY.has(source.statuses[stage] ?? ""));
  const activePhases = phases.filter((phase) => phase !== "adapt_plan" || adaptReady);
  const activeStages = activePhases.flatMap((phase) => data?.phases[phase] ?? []);
  const reasoning = Object.fromEntries(chosenModels.map((id) => {
    const model = data?.models.find((candidate) => candidate.id === id);
    return [id, Object.fromEntries(activeStages.map((stage) => [stage, reasoningDraft[id]?.[stage] ?? model?.default_reasoning ?? "medium"]))];
  }));
  const request = source && activePhases.length && chosenModels.length >= 2
    ? { project, phases: activePhases, models: chosenModels, reasoning_efforts: reasoning } : null;
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
  const funding = (id: string) => data.models.find((model) => model.id === id)?.funding ?? "api";
  const apiTotal = Object.entries(estimate.data?.estimated_cost_usd ?? {})
    .filter(([model, value]) => funding(model) === "api" && value != null)
    .reduce((total, [, value]) => total + (value ?? 0), 0);

  return (
    <div className="space-y-5">
      <p className="max-w-3xl font-body text-sm leading-6 text-ink-muted">
        Runs the same stages on the same inputs once per model, each in its own copy of the project, exactly as the
        pipeline runs them. Extract + Brief starts from the novel text; Adapt + Plan starts from the project&apos;s
        approved Brief, Style and Cast. Your project is only read.
      </p>
      <ProjectPicker projects={projects} value={project} onChange={setProject} />
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <fieldset>
          <legend className={META}>Stages</legend>
          {Object.entries(data.phases).map(([phase, stages]) => (
            <Checkbox
              key={phase}
              checked={activePhases.includes(phase)}
              disabled={phase === "adapt_plan" && !adaptReady}
              onChange={(next) => setPhases(toggle(phases, phase, next))}
            >
              <span className="font-body text-sm font-bold">{PHASE_LABEL[phase] ?? phase}</span>
              <span className={cn(META, "block")}>
                {phase === "adapt_plan" && !adaptReady ? "Needs an approved Brief, Style and Cast" : stages.join(" → ")}
              </span>
            </Checkbox>
          ))}
        </fieldset>
        <fieldset>
          <legend className={META}>Models (2–6)</legend>
          <div className="grid gap-x-5 sm:grid-cols-2">
            {providers.map(([provider, group]) => (
              <div key={provider} className="mt-2">
                <div className="font-meta text-xs font-bold">{provider}</div>
                {group.map((model) => (
                  <Checkbox
                    key={model.id}
                    checked={chosenModels.includes(model.id)}
                    disabled={!model.available || (!chosenModels.includes(model.id) && chosenModels.length >= 6)}
                    onChange={(next) => setModels(toggle(chosenModels, model.id, next))}
                  >
                    <span className="font-body text-sm">{model.label}</span>
                    {!model.available && <span className={cn(META, "block")}>Not enabled in this server</span>}
                    {model.available && estimate.data?.estimated_cost_usd[model.id] !== undefined && (
                      <span className={cn(META, "block")}>
                        {model.funding === "api" ? `≈${usd(estimate.data.estimated_cost_usd[model.id], 2)} est.` : "subscription allowance"}
                      </span>
                    )}
                  </Checkbox>
                ))}
              </div>
            ))}
          </div>
        </fieldset>
      </div>
      <fieldset className="space-y-3">
        <legend className={META}>Reasoning per model and stage</legend>
        <p className="font-body text-sm text-ink-muted">These choices apply to this comparison. Higher reasoning can increase latency and token usage; estimates use the source project's recorded tokens.</p>
        {chosenModels.map((id) => {
          const model = data.models.find((candidate) => candidate.id === id);
          if (!model) return null;
          return <Surface key={id} padding="sm" shadow="none" border="soft">
            <p className="font-meta text-xs font-bold">{model.label}</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {activeStages.map((stage) => <label key={stage} className="font-body text-xs">
                {stage[0].toUpperCase() + stage.slice(1)}
                <select aria-label={`${model.label} ${stage} reasoning`} className="mt-1 w-full border-2 border-ink-black/20 bg-bristol p-2 font-body text-sm"
                  disabled={create.isPending} value={reasoning[id][stage]}
                  onChange={(event) => setReasoning((current) => ({ ...current, [id]: { ...current[id], [stage]: event.target.value } }))}>
                  {model.reasoning_options.map((value) => <option key={value} value={value}>{value === "none" ? "Off" : value === "enabled" ? "On" : value[0].toUpperCase() + value.slice(1)}</option>)}
                </select>
              </label>)}
            </div>
          </Surface>;
        })}
      </fieldset>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={!request || create.isPending}
          onClick={() => request && create.mutate(
            { kind: "stage_models", label: `${source?.title} · ${chosenModels.join(" vs ")}`, ...request },
            { onSuccess: (run) => onStarted(run.run_id) },
          )}
        >
          Run comparison
        </Button>
        <span className={META}>
          {estimate.isFetching ? "Estimating…"
            : estimate.error ? String(estimate.error)
              : request ? `≈${usd(apiTotal, 2)} est. for API models, priced from this project's recorded tokens`
                : "Choose stages and at least two models"}
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
        {image && !blind ? (
          <a href={labsRunFileUrl(runId, cell!.image!)} target="_blank" rel="noreferrer" className="block h-full w-full">{image}</a>
        ) : image ?? (
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
      {cell?.status === "ok" && !blind && (
        <p className={cn(META, "mt-1")}>
          {seconds((cell.latency_ms ?? 0) / 1000)} · {costWithEquivalent(cell.cost_usd, cell.api_equivalent_usd, cell.funding)}
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

function ImageCompareRun({ run, targets }: { run: LabsRunDetail; targets: ImageTarget[] | undefined }) {
  const [blind, setBlind] = useState(true);
  const retry = useRetryLabsCells(run.run_id);
  const cells = run.cells as ImageCell[];
  const items = (run.spec.items as string[] | undefined) ?? [];
  const arms = (run.spec.arms as ImageArm[] | undefined) ?? [];
  const failed = cells.filter((cell) => cell.status === "failed");
  const canRetry = run.status !== "running" && !retry.isPending;
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
      seconds: done.length ? sum((cell) => cell.latency_ms) / done.length / 1000 : null,
    };
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => setBlind(!blind)}>
          {blind ? <Eye className="mr-1.5 inline h-4 w-4" aria-hidden /> : <EyeOff className="mr-1.5 inline h-4 w-4" aria-hidden />}
          {blind ? "Reveal arms" : "Blind review"}
        </Button>
        {failed.length > 0 && (
          <Button variant="outline" size="sm" disabled={!canRetry} onClick={() => retry.mutate(undefined)}>
            <RotateCcw className="mr-1.5 inline h-4 w-4" aria-hidden />
            Retry {failed.length} failed
          </Button>
        )}
        <span className={META}>
          {blind ? "Judge each item first; image order is shuffled and every image shares one frame." : "Arms revealed."}
        </span>
      </div>
      {retry.error && <p className="font-body text-sm text-hero-red">{String(retry.error)}</p>}
      {!blind && (
        <table className="w-full border-collapse font-body text-sm">
          <thead>
            <tr className={cn(META, "text-left")}>
              <th className="py-1 pr-3 font-normal">Arm</th>
              <th className="py-1 pr-3 font-normal">Done</th>
              <th className="py-1 pr-3 font-normal">Avg time</th>
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
                  retrying={!canRetry}
                  onRetry={(cellId) => retry.mutate([cellId])}
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
            {cells.map((cell) => <th key={cell.cell_id} className="py-1.5 pr-3 text-left font-meta text-xs font-bold">{cell.model}</th>)}
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
  return (
    <div className="space-y-8">
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
                    <span className="font-meta text-xs font-bold">{cell.model}<FundingTag funding={cell.funding} /></span>
                    <StatusChip status={cell.status} />
                  </div>
                  <p className="mt-1 font-body text-sm tabular-nums">
                    {seconds(cell.seconds ?? cell.stages.reduce((sum, stage) => sum + stage.seconds, 0))} ·{" "}
                    {costWithEquivalent(cell.cost_usd ?? cell.stages.reduce((sum, stage) => sum + stage.cost_usd, 0), cell.api_equivalent_usd, cell.funding)}
                    {cell.funding === "api" ? " measured" : ""}
                    {cell.funding === "api" && estimate?.[cell.model] != null && (
                      <span className="text-ink-muted"> · ≈{usd(estimate[cell.model], 2)} est. for all phases</span>
                    )}
                  </p>
                  {cell.reasoning_efforts && <p className="mt-1 font-body text-xs text-ink-muted">Reasoning: {Object.entries(cell.reasoning_efforts).map(([stage, effort]) => `${stage}: ${effort === "none" ? "Off" : effort === "enabled" ? "On" : effort}`).join(" · ")}</p>}
                  {cell.error && <p className="mt-1 font-body text-sm text-hero-red">{cell.error}</p>}
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
        : <StageModelsRun run={run} />}
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
    <div className="mx-auto max-w-[1400px] px-4 py-6 md:px-8">
      <SectionHeader
        kicker="Local development"
        title="Labs"
        description="Model experiments on your own projects. API calls cost operator USD; subscription calls use your Claude or Codex allowance. Never account credits."
      />
      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-5">
          <nav aria-label="New experiment" className="grid gap-2">
            {(["image_compare", "stage_models"] as const).map((kind) => (
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
          {!view && runId && <RunView runId={runId} onDeleted={() => open({ new: "image_compare" })} />}
        </main>
      </div>
    </div>
  );
}
