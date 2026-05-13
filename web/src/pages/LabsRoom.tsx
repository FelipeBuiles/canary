import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  useCreateLabsRun,
  useImportLabsScene,
  useLabsFixture,
  useLabsImportableProjects,
  useLabsModels,
  useLabsProjectScenes,
  useLabsRun,
  useLabsRuns,
} from "../api/queries";
import type {
  LabsCell,
  LabsFixtureScene,
  LabsModel,
  LabsPanel,
  LabsReferenceSource,
  LabsRunCreatePayload,
  LabsTier,
} from "../api/labs";
import { Button } from "../components/ui/Button";
import { Surface } from "../components/ui/Surface";
import { cn } from "../lib/cn";

const TIER_LABEL: Record<LabsTier, string> = {
  fast: "FAST",
  balanced: "BALANCED",
  premium: "PREMIUM",
};

const TIER_ORDER: LabsTier[] = ["fast", "balanced", "premium"];

const PROVIDER_LABEL: Record<LabsModel["provider"], string> = {
  fal: "fal.ai",
  together: "together.ai",
  litellm: "Production gateway",
};

function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return iso;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

function formatCost(c: number | null | undefined): string {
  if (c == null) return "—";
  if (c === 0) return "$0";
  if (c < 0.01) return `<$0.01`;
  return `$${c.toFixed(c < 1 ? 3 : 2)}`;
}

function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

interface ModelPickerProps {
  models: LabsModel[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  disabled?: boolean;
}

function ModelPicker({ models, selected, onToggle, disabled }: ModelPickerProps) {
  const grouped = useMemo(() => {
    const g: Record<LabsTier, LabsModel[]> = { fast: [], balanced: [], premium: [] };
    for (const m of models) g[m.tier]?.push(m);
    return g;
  }, [models]);

  return (
    <div className="space-y-4">
      {TIER_ORDER.map((tier) => {
        const list = grouped[tier];
        if (!list.length) return null;
        return (
          <div key={tier}>
            <div className="mb-2 font-meta text-[0.56rem] tracking-[0.22em] text-ink-black/50">
              {TIER_LABEL[tier]}
            </div>
            <div className="grid grid-cols-1 gap-2">
              {list.map((m) => {
                const checked = selected.has(m.id);
                return (
                  <label
                    key={m.id}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 border-[2px] px-3 py-3 transition-colors",
                      checked
                        ? "border-ink-black bg-bristol"
                        : "border-ink-black/15 bg-pulp-paper hover:border-ink-black/40",
                      disabled && "cursor-not-allowed opacity-60",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => onToggle(m.id)}
                      className="mt-0.5 h-4 w-4 accent-hero-red"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-display text-[0.92rem] font-bold leading-tight">
                          {m.label}
                        </span>
                        <span className="shrink-0 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/40">
                          {PROVIDER_LABEL[m.provider]}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-meta text-[0.6rem] tracking-[0.04em] text-ink-black/55">
                        {m.approx_cost != null && (
                          <span>~{formatCost(m.approx_cost)}/image</span>
                        )}
                        {m.multi_ref ? (
                          <span>multi-ref · up to {m.max_refs}</span>
                        ) : m.style_refs ? (
                          <span>style-ref only</span>
                        ) : (
                          <span>text-to-image</span>
                        )}
                      </div>
                      {m.notes && (
                        <p className="mt-1.5 font-body text-[0.76rem] leading-snug text-ink-black/55">
                          {m.notes}
                        </p>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface ScenePanelEditorProps {
  panels: LabsPanel[];
  onChange: (panels: LabsPanel[]) => void;
  disabled?: boolean;
}

function ScenePanelEditor({ panels, onChange, disabled }: ScenePanelEditorProps) {
  function setPanel(idx: number, next: Partial<LabsPanel>) {
    onChange(panels.map((p) => (p.idx === idx ? { ...p, ...next } : p)));
  }
  return (
    <div className="space-y-3">
      {panels.map((p) => (
        <div key={p.idx} className="border-l-[3px] border-ink-black/10 pl-3">
          <div className="flex items-baseline justify-between gap-2">
            <input
              value={p.label}
              disabled={disabled}
              onChange={(e) => setPanel(p.idx, { label: e.target.value })}
              className="min-w-0 flex-1 bg-transparent font-meta text-[0.66rem] font-bold uppercase tracking-[0.14em] text-ink-black/72 outline-none focus:text-ink-black"
              placeholder={`Panel ${p.idx}`}
            />
            <span className="shrink-0 font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/35">
              {p.width}×{p.height}
            </span>
          </div>
          <textarea
            value={p.prompt}
            disabled={disabled}
            onChange={(e) => setPanel(p.idx, { prompt: e.target.value })}
            rows={3}
            className="mt-1 w-full resize-y border-[1.5px] border-ink-black/15 bg-pulp-paper px-2.5 py-2 font-body text-[0.84rem] leading-snug text-ink-black focus:border-ink-black focus:outline-none"
            placeholder="Prompt for this panel"
          />
        </div>
      ))}
    </div>
  );
}

interface ReferencePreviewProps {
  urls: { url: string; label: string }[];
}

function ReferencePreview({ urls }: ReferencePreviewProps) {
  if (!urls.length) {
    return (
      <div className="font-meta text-[0.66rem] tracking-[0.14em] text-ink-black/40">
        No reference images attached
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {urls.map((r) => (
        <div key={r.url} className="flex w-[120px] flex-col items-center gap-1">
          <img
            src={r.url}
            alt={r.label}
            className="h-[100px] w-[100px] border-[2px] border-ink-black/15 bg-pulp-paper object-cover"
          />
          <span className="line-clamp-2 text-center font-meta text-[0.5rem] tracking-[0.06em] text-ink-black/55">
            {r.label}
          </span>
        </div>
      ))}
    </div>
  );
}

interface ResultsGridProps {
  panels: { idx: number; label: string; prompt: string; cells: Record<string, LabsCell> }[];
  models: LabsModel[];
  modelIds: string[];
}

interface LightboxTarget {
  panelIdx: number;
  modelId: string;
}

const CELL_SIZE_PX = 240;
const PANEL_COL_PX = 240;

function ResultsGrid({ panels, models, modelIds }: ResultsGridProps) {
  const modelMap = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const [lightbox, setLightbox] = useState<LightboxTarget | null>(null);
  const modelSummaries = useMemo(() => {
    const summaries = new Map<string, { cost: number; costCount: number; latencyMs: number; latencyCount: number }>();
    for (const mid of modelIds) {
      summaries.set(mid, { cost: 0, costCount: 0, latencyMs: 0, latencyCount: 0 });
    }
    for (const panel of panels) {
      for (const mid of modelIds) {
        const cell = panel.cells[mid];
        if (!cell || cell.status !== "ok") continue;
        const summary = summaries.get(mid);
        if (!summary) continue;
        if (typeof cell.cost_usd === "number") {
          summary.cost += cell.cost_usd;
          summary.costCount += 1;
        }
        if (typeof cell.latency_ms === "number") {
          summary.latencyMs += cell.latency_ms;
          summary.latencyCount += 1;
        }
      }
    }
    return summaries;
  }, [modelIds, panels]);

  if (!modelIds.length || !panels.length) {
    return (
      <div className="border-[2px] border-dashed border-ink-black/20 p-10 text-center font-meta text-[0.72rem] tracking-[0.16em] text-ink-black/40">
        No results yet
      </div>
    );
  }

  function openLightbox(panelIdx: number, modelId: string) {
    setLightbox({ panelIdx, modelId });
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: PANEL_COL_PX }} />
            {modelIds.map((mid) => (
              <col key={mid} style={{ width: CELL_SIZE_PX + 24 }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="sticky left-0 z-10 border-b-[2px] border-ink-black bg-pulp-paper p-3 text-left align-bottom">
                <span className="font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/45">
                  PANEL
                </span>
              </th>
              {modelIds.map((mid) => {
                const m = modelMap.get(mid);
                const summary = modelSummaries.get(mid);
                const avgLatency =
                  summary && summary.latencyCount > 0
                    ? Math.round(summary.latencyMs / summary.latencyCount)
                    : null;
                return (
                  <th key={mid} className="border-b-[2px] border-ink-black p-3 text-left align-bottom">
                    <div className="line-clamp-2 font-display text-[0.92rem] font-bold leading-tight">
                      {m?.label ?? mid}
                    </div>
                    <div className="mt-1 font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/45">
                      {m ? PROVIDER_LABEL[m.provider] : "unknown"}
                    </div>
                    <div className="mt-1 font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/55">
                      {summary?.costCount ? `${formatCost(summary.cost)} total` : "— total"}
                      {" · "}
                      {formatLatency(avgLatency)}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {panels.map((p) => (
              <tr key={p.idx} className="align-top">
                <td className="sticky left-0 z-10 border-b border-ink-black/10 bg-pulp-paper p-3">
                  <div className="font-meta text-[0.56rem] font-bold tracking-[0.16em] text-ink-black/55">
                    PANEL {p.idx}
                  </div>
                  <div className="mt-1 font-display text-[0.84rem] font-bold leading-tight">
                    {p.label}
                  </div>
                  <p className="mt-2 line-clamp-6 font-body text-[0.72rem] leading-snug text-ink-black/52">
                    {p.prompt}
                  </p>
                </td>
                {modelIds.map((mid) => {
                  const cell = p.cells[mid] ?? { status: "pending" as const };
                  return (
                    <td key={mid} className="border-b border-ink-black/10 p-3">
                      <CellView
                        cell={cell}
                        onOpen={() => openLightbox(p.idx, mid)}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {lightbox && (
        <Lightbox
          target={lightbox}
          panels={panels}
          modelIds={modelIds}
          modelMap={modelMap}
          onClose={() => setLightbox(null)}
          onNavigate={setLightbox}
        />
      )}
    </>
  );
}

interface CellViewProps {
  cell: LabsCell;
  onOpen: () => void;
}

function CellView({ cell, onOpen }: CellViewProps) {
  const boxStyle = { width: CELL_SIZE_PX, height: CELL_SIZE_PX };

  if (cell.status === "ok" && cell.image_url) {
    return (
      <div className="flex flex-col gap-1.5">
        <button
          type="button"
          onClick={onOpen}
          style={boxStyle}
          className="group relative block overflow-hidden border-[2px] border-ink-black/15 bg-pulp-paper transition-colors hover:border-ink-black focus:border-ink-black focus:outline-none"
          aria-label="Open image"
        >
          <img
            src={cell.image_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover"
          />
          <span className="pointer-events-none absolute inset-0 flex items-end justify-end p-2 opacity-0 transition-opacity group-hover:opacity-100">
            <span className="bg-ink-black/85 px-2 py-1 font-meta text-[0.52rem] tracking-[0.14em] text-bristol">
              EXPAND
            </span>
          </span>
        </button>
        <div className="flex items-center justify-between font-meta text-[0.56rem] tracking-[0.08em] text-ink-black/55">
          <span>{formatLatency(cell.latency_ms)}</span>
          <span>{formatCost(cell.cost_usd)}</span>
        </div>
      </div>
    );
  }
  if (cell.status === "failed") {
    return (
      <div className="flex flex-col gap-1.5">
        <button
          type="button"
          onClick={onOpen}
          style={boxStyle}
          className="group flex flex-col items-center justify-center gap-2 border-[2px] border-dashed border-hero-red/45 bg-chip-red/25 p-4 text-center transition-colors hover:border-hero-red focus:border-hero-red focus:outline-none"
          aria-label="View error details"
        >
          <span className="font-display text-[1.05rem] font-black tracking-[-0.02em] text-hero-red/85">
            ⚠
          </span>
          <span className="font-meta text-[0.62rem] font-bold tracking-[0.14em] text-hero-red">
            FAILED
          </span>
          <p className="line-clamp-3 font-body text-[0.7rem] leading-snug text-ink-black/60">
            {firstErrorLine(cell.error)}
          </p>
          <span className="mt-1 font-meta text-[0.5rem] tracking-[0.16em] text-hero-red/65 underline-offset-2 group-hover:underline">
            VIEW DETAILS
          </span>
        </button>
        <div className="flex items-center justify-between font-meta text-[0.56rem] tracking-[0.08em] text-ink-black/45">
          <span>{formatLatency(cell.latency_ms)}</span>
          <span>—</span>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div
        style={boxStyle}
        className="flex items-center justify-center border-[2px] border-dashed border-ink-black/15 bg-pulp-paper"
      >
        <span className="font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/30">
          PENDING…
        </span>
      </div>
      <div className="flex items-center justify-between font-meta text-[0.56rem] tracking-[0.08em] text-ink-black/35">
        <span>—</span>
        <span>—</span>
      </div>
    </div>
  );
}

function firstErrorLine(error: string | undefined): string {
  if (!error) return "Unknown error";
  const trimmed = error.trim();
  // Errors often pack JSON; show the first sentence/line to keep cells readable.
  const newline = trimmed.indexOf("\n");
  return newline > 0 ? trimmed.slice(0, newline) : trimmed;
}

interface LightboxProps {
  target: LightboxTarget;
  panels: { idx: number; label: string; prompt: string; cells: Record<string, LabsCell> }[];
  modelIds: string[];
  modelMap: Map<string, LabsModel>;
  onClose: () => void;
  onNavigate: (target: LightboxTarget) => void;
}

function Lightbox({ target, panels, modelIds, modelMap, onClose, onNavigate }: LightboxProps) {
  const panel = panels.find((p) => p.idx === target.panelIdx);
  const cell = panel?.cells[target.modelId];
  const model = modelMap.get(target.modelId);

  const modelIdx = modelIds.indexOf(target.modelId);
  const prevModelId = modelIdx > 0 ? modelIds[modelIdx - 1] : null;
  const nextModelId = modelIdx >= 0 && modelIdx < modelIds.length - 1 ? modelIds[modelIdx + 1] : null;

  const panelIdxs = panels.map((p) => p.idx);
  const panelPos = panelIdxs.indexOf(target.panelIdx);
  const prevPanelIdx = panelPos > 0 ? panelIdxs[panelPos - 1] : null;
  const nextPanelIdx = panelPos >= 0 && panelPos < panelIdxs.length - 1 ? panelIdxs[panelPos + 1] : null;

  const navigate = useCallback(
    (next: LightboxTarget | null) => {
      if (next) onNavigate(next);
    },
    [onNavigate],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key === "ArrowLeft" && prevModelId) {
        navigate({ panelIdx: target.panelIdx, modelId: prevModelId });
      } else if (event.key === "ArrowRight" && nextModelId) {
        navigate({ panelIdx: target.panelIdx, modelId: nextModelId });
      } else if (event.key === "ArrowUp" && prevPanelIdx != null) {
        navigate({ panelIdx: prevPanelIdx, modelId: target.modelId });
      } else if (event.key === "ArrowDown" && nextPanelIdx != null) {
        navigate({ panelIdx: nextPanelIdx, modelId: target.modelId });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, prevModelId, nextModelId, prevPanelIdx, nextPanelIdx, navigate, onClose]);

  if (!panel || !cell) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-6 backdrop-blur-[3px]"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Image detail"
    >
      <div
        className="flex max-h-[92vh] w-full max-w-[1280px] flex-col gap-4 lg:flex-row"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex min-h-0 flex-1 items-center justify-center bg-ink-black">
          {cell.status === "ok" && cell.image_url ? (
            <img
              src={cell.image_url}
              alt={panel.label}
              className="max-h-[88vh] max-w-full object-contain"
            />
          ) : cell.status === "failed" ? (
            <div className="flex h-full max-h-[88vh] w-full flex-col items-center justify-center gap-4 p-8 text-center">
              <span className="font-display text-[5rem] font-black leading-none text-hero-red">⚠</span>
              <span className="font-meta text-[0.78rem] font-bold tracking-[0.2em] text-hero-red">
                GENERATION FAILED
              </span>
              <pre className="max-h-[60vh] w-full max-w-[720px] overflow-auto whitespace-pre-wrap break-words border border-hero-red/40 bg-ink-black/40 p-4 text-left font-body text-[0.82rem] leading-relaxed text-bristol/85">
                {cell.error || "Unknown error"}
              </pre>
            </div>
          ) : (
            <div className="font-meta text-[0.72rem] tracking-[0.18em] text-bristol/60">
              PENDING…
            </div>
          )}
        </div>

        <div className="flex w-full shrink-0 flex-col gap-3 bg-bristol p-5 lg:w-[360px]">
          <div className="flex items-start justify-between gap-3 border-b border-ink-black/10 pb-3">
            <div className="min-w-0">
              <div className="font-meta text-[0.54rem] tracking-[0.18em] text-ink-black/45">
                PANEL {panel.idx}
              </div>
              <div className="font-display text-[1.05rem] font-bold leading-tight">
                {panel.label}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="font-meta text-[0.72rem] font-bold tracking-[0.16em] text-ink-black/55 hover:text-hero-red"
            >
              ✕
            </button>
          </div>

          <div>
            <div className="font-meta text-[0.54rem] tracking-[0.18em] text-ink-black/45">
              MODEL
            </div>
            <div className="font-display text-[0.92rem] font-bold leading-tight">
              {model?.label ?? target.modelId}
            </div>
            <div className="mt-1 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/50">
              {model ? PROVIDER_LABEL[model.provider] : "unknown"}
            </div>
            {cell.provider_model && (
              <div className="mt-1 break-words font-meta text-[0.48rem] tracking-[0.1em] text-ink-black/42">
                {cell.provider_model}
              </div>
            )}
          </div>

          {cell.status === "ok" && (
            <div className="grid grid-cols-2 gap-3 border-y border-ink-black/10 py-3">
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/45">
                  LATENCY
                </div>
                <div className="font-display text-[1rem] font-bold">
                  {formatLatency(cell.latency_ms)}
                </div>
              </div>
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/45">
                  COST
                </div>
                <div className="font-display text-[1rem] font-bold">
                  {formatCost(cell.cost_usd)}
                </div>
                {cell.cost_source && (
                  <div className="mt-1 break-words font-meta text-[0.46rem] tracking-[0.1em] text-ink-black/40">
                    {cell.cost_source}
                  </div>
                )}
              </div>
            </div>
          )}

          <div>
            <div className="font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/45">
              PROMPT
            </div>
            <p className="mt-1 max-h-[180px] overflow-auto font-body text-[0.78rem] leading-snug text-ink-black/75">
              {panel.prompt}
            </p>
          </div>

          {cell.status === "ok" && cell.image_url && (
            <a
              href={cell.image_url}
              target="_blank"
              rel="noreferrer"
              className="inline-block self-start border-[2px] border-ink-black px-3 py-1.5 font-meta text-[0.6rem] tracking-[0.14em] hover:bg-ink-black hover:text-bristol"
            >
              OPEN ORIGINAL ↗
            </a>
          )}

          <div className="mt-auto grid grid-cols-2 gap-2 border-t border-ink-black/10 pt-3">
            <button
              type="button"
              disabled={!prevModelId}
              onClick={() => prevModelId && navigate({ panelIdx: target.panelIdx, modelId: prevModelId })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              ← MODEL
            </button>
            <button
              type="button"
              disabled={!nextModelId}
              onClick={() => nextModelId && navigate({ panelIdx: target.panelIdx, modelId: nextModelId })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              MODEL →
            </button>
            <button
              type="button"
              disabled={prevPanelIdx == null}
              onClick={() => prevPanelIdx != null && navigate({ panelIdx: prevPanelIdx, modelId: target.modelId })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              ↑ PANEL
            </button>
            <button
              type="button"
              disabled={nextPanelIdx == null}
              onClick={() => nextPanelIdx != null && navigate({ panelIdx: nextPanelIdx, modelId: target.modelId })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              PANEL ↓
            </button>
          </div>
          <p className="font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/40">
            ← → for models · ↑ ↓ for panels · Esc to close
          </p>
        </div>
      </div>
    </div>
  );
}

type SceneSource = "fixture" | "imported";

const DEFAULT_MODEL_PICKS = ["flux-2-pro-edit", "seedream-v4-5-edit", "gemini-3-pro-current"];

export function LabsRoom() {
  const { data: modelsData, isLoading: modelsLoading } = useLabsModels();
  const { data: fixture } = useLabsFixture();

  if (modelsLoading || !modelsData || !fixture) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
          LOADING LABS…
        </p>
      </div>
    );
  }
  return <LabsRoomContent models={modelsData.models} fixture={fixture} />;
}

function LabsRoomContent({ models, fixture }: { models: LabsModel[]; fixture: LabsFixtureScene }) {
  const { data: importableProjects } = useLabsImportableProjects();

  const [sceneSource, setSceneSource] = useState<SceneSource>("fixture");
  const [importProjectId, setImportProjectId] = useState<string>("");
  const [importSceneId, setImportSceneId] = useState<string>("");
  const { data: importScenes } = useLabsProjectScenes(
    sceneSource === "imported" ? importProjectId || undefined : undefined,
  );
  const importScene = useImportLabsScene();

  const [styleTemplate, setStyleTemplate] = useState(fixture.default_style_template);
  const [panels, setPanels] = useState<LabsPanel[]>(fixture.panels);
  const [importedRefPaths, setImportedRefPaths] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<Set<string>>(
    () => new Set(DEFAULT_MODEL_PICKS.filter((id) => models.some((m) => m.id === id))),
  );
  const [runLabel, setRunLabel] = useState(fixture.label);

  const createRun = useCreateLabsRun();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const { data: activeRun } = useLabsRun(activeRunId ?? undefined);
  const { data: runsList } = useLabsRuns();

  function handleSceneSource(next: SceneSource) {
    setSceneSource(next);
    if (next === "fixture") {
      setStyleTemplate(fixture.default_style_template);
      setPanels(fixture.panels);
      setImportedRefPaths([]);
      setRunLabel(fixture.label);
    } else {
      setPanels([]);
      setImportedRefPaths([]);
      setRunLabel("");
    }
  }

  function toggleModel(id: string) {
    setSelectedModels((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleImport() {
    if (!importProjectId || !importSceneId) return;
    try {
      const result = await importScene.mutateAsync({
        projectId: importProjectId,
        sceneId: importSceneId,
        panelLimit: 8,
      });
      setStyleTemplate(result.style_template);
      setPanels(result.panels);
      setImportedRefPaths(result.imported_reference_paths);
      setRunLabel(result.label);
    } catch (err) {
      console.error("import failed", err);
    }
  }

  async function handleRun() {
    if (!selectedModels.size || !panels.length) return;
    const referenceSource: LabsReferenceSource =
      sceneSource === "imported" ? (importedRefPaths.length ? "imported" : "none") : "fixture";
    const payload: LabsRunCreatePayload = {
      label: runLabel.trim() || "Untitled run",
      model_ids: [...selectedModels],
      style_template: styleTemplate,
      panels,
      reference_source: referenceSource,
      reference_image_paths: referenceSource === "imported" ? importedRefPaths : undefined,
    };
    try {
      const result = await createRun.mutateAsync(payload);
      setActiveRunId(result.run_id);
    } catch (err) {
      console.error("run failed", err);
    }
  }

  const selectedCount = selectedModels.size;
  const runDisabled = !selectedCount || !panels.length || createRun.isPending;

  const fixtureRefThumbs =
    sceneSource === "fixture"
      ? fixture.reference_images.map((r) => ({ url: r.url, label: r.label }))
      : [];

  return (
    <div className="space-y-8">
      <header className="border-b-[3px] border-ink-black pb-6">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <div className="inline-flex bg-narrator-gold px-3 py-1 font-meta text-[0.56rem] tracking-[0.22em] text-ink-black">
              STUDIO // LABS
            </div>
            <h1 className="mt-4 font-display text-[clamp(3rem,6vw,5rem)] font-black uppercase leading-[0.85] tracking-[-0.04em] text-ink-black">
              Labs
            </h1>
            <p className="mt-3 max-w-[60ch] font-body text-[1rem] leading-snug text-ink-black/68">
              Run the same scene through multiple image-generation models in
              parallel. Tune the style guide, pick the candidates, compare the
              output side-by-side.
            </p>
          </div>
          <Link
            to="/"
            className="font-meta text-[0.62rem] font-bold uppercase tracking-[0.16em] text-ink-black/62 hover:text-hero-red"
          >
            ← Library
          </Link>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)]">
        <Surface padding="lg" className="space-y-6">
          <div>
            <div className="ui-kicker">SCENE</div>
            <h2 className="ui-title">Sample to send</h2>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => handleSceneSource("fixture")}
                className={cn(
                  "border-[2px] px-3 py-2 font-meta text-[0.62rem] tracking-[0.14em] transition-colors",
                  sceneSource === "fixture"
                    ? "border-ink-black bg-ink-black text-bristol"
                    : "border-ink-black/30 bg-pulp-paper text-ink-black/70 hover:border-ink-black",
                )}
              >
                Default fixture
              </button>
              <button
                type="button"
                onClick={() => handleSceneSource("imported")}
                className={cn(
                  "border-[2px] px-3 py-2 font-meta text-[0.62rem] tracking-[0.14em] transition-colors",
                  sceneSource === "imported"
                    ? "border-ink-black bg-ink-black text-bristol"
                    : "border-ink-black/30 bg-pulp-paper text-ink-black/70 hover:border-ink-black",
                )}
              >
                Import from project
              </button>
            </div>

            {sceneSource === "imported" && (
              <div className="mt-4 space-y-3 border-l-[3px] border-narrator-gold/60 pl-4">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto]">
                  <select
                    value={importProjectId}
                    onChange={(e) => {
                      setImportProjectId(e.target.value);
                      setImportSceneId("");
                    }}
                    className="border-[2px] border-ink-black/15 bg-pulp-paper px-3 py-2 font-meta text-[0.7rem] tracking-[0.06em]"
                  >
                    <option value="">— Project —</option>
                    {(importableProjects?.projects ?? []).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.scene_count} scenes
                      </option>
                    ))}
                  </select>
                  <select
                    value={importSceneId}
                    onChange={(e) => setImportSceneId(e.target.value)}
                    disabled={!importProjectId}
                    className="border-[2px] border-ink-black/15 bg-pulp-paper px-3 py-2 font-meta text-[0.7rem] tracking-[0.06em] disabled:opacity-50"
                  >
                    <option value="">— Scene —</option>
                    {(importScenes?.scenes ?? []).map((s) => (
                      <option key={s.scene_id} value={s.scene_id}>
                        {s.scene_id} · {s.panel_count} panels
                      </option>
                    ))}
                  </select>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!importProjectId || !importSceneId || importScene.isPending}
                    onClick={handleImport}
                  >
                    {importScene.isPending ? "IMPORTING…" : "IMPORT"}
                  </Button>
                </div>
                {importedRefPaths.length > 0 && (
                  <div className="font-meta text-[0.6rem] tracking-[0.12em] text-ink-black/50">
                    {importedRefPaths.length} reference image
                    {importedRefPaths.length === 1 ? "" : "s"} attached
                  </div>
                )}
              </div>
            )}
          </div>

          {sceneSource === "fixture" && (
            <div>
              <div className="ui-kicker">REFERENCE IMAGES</div>
              <div className="mt-3">
                <ReferencePreview urls={fixtureRefThumbs} />
              </div>
            </div>
          )}

          <div>
            <div className="ui-kicker">STYLE TEMPLATE</div>
            <textarea
              value={styleTemplate}
              onChange={(e) => setStyleTemplate(e.target.value)}
              rows={4}
              className="mt-2 w-full resize-y border-[2px] border-ink-black/15 bg-pulp-paper px-3 py-2 font-body text-[0.88rem] leading-snug focus:border-ink-black focus:outline-none"
              placeholder="A single-paragraph description of the visual style to apply to every panel"
            />
          </div>

          <div>
            <div className="ui-kicker">PANELS</div>
            <div className="mt-3">
              {panels.length === 0 ? (
                <div className="border-[2px] border-dashed border-ink-black/15 p-6 text-center font-meta text-[0.66rem] tracking-[0.14em] text-ink-black/40">
                  No panels yet
                </div>
              ) : (
                <ScenePanelEditor
                  panels={panels}
                  onChange={setPanels}
                  disabled={createRun.isPending}
                />
              )}
            </div>
          </div>
        </Surface>

        <div className="space-y-6">
          <Surface padding="lg" className="space-y-4">
            <div>
              <div className="ui-kicker">RUN</div>
              <h2 className="ui-title">Configure experiment</h2>
            </div>

            <label className="block">
              <div className="ui-kicker mb-1">LABEL</div>
              <input
                value={runLabel}
                onChange={(e) => setRunLabel(e.target.value)}
                className="w-full border-[2px] border-ink-black/15 bg-pulp-paper px-3 py-2 font-body text-[0.92rem] focus:border-ink-black focus:outline-none"
                placeholder="Untitled run"
              />
            </label>

            <div>
              <div className="ui-kicker mb-2">MODELS ({selectedCount} SELECTED)</div>
              <ModelPicker
                models={models}
                selected={selectedModels}
                onToggle={toggleModel}
                disabled={createRun.isPending}
              />
            </div>

            <Button
              variant="primary"
              size="lg"
              fullWidth
              disabled={runDisabled}
              onClick={handleRun}
            >
              {createRun.isPending
                ? "STARTING…"
                : `RUN EXPERIMENT → ${selectedCount * panels.length} CELLS`}
            </Button>
            {createRun.isError && (
              <div className="font-meta text-[0.62rem] tracking-[0.12em] text-hero-red">
                {(createRun.error as Error).message}
              </div>
            )}
          </Surface>

          <Surface padding="md">
            <div className="ui-kicker mb-3">RECENT RUNS</div>
            {!runsList || runsList.runs.length === 0 ? (
              <div className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/40">
                No runs yet
              </div>
            ) : (
              <ul className="space-y-1.5">
                {runsList.runs.slice(0, 10).map((r) => (
                  <li key={r.run_id}>
                    <button
                      type="button"
                      onClick={() => setActiveRunId(r.run_id)}
                      className={cn(
                        "flex w-full items-center justify-between gap-3 border-l-[3px] px-3 py-2 text-left transition-colors",
                        activeRunId === r.run_id
                          ? "border-narrator-gold bg-bristol"
                          : "border-transparent hover:bg-bristol/40",
                      )}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-display text-[0.86rem] font-bold">
                          {r.label || r.run_id}
                        </span>
                        <span className="block font-meta text-[0.54rem] tracking-[0.14em] text-ink-black/50">
                          {r.model_ids.length} models · {r.panel_count} panels
                          {r.total_cost_usd != null ? ` · ${formatCost(r.total_cost_usd)}` : ""}
                          {" · "}
                          {relTime(r.created_at)}
                        </span>
                      </span>
                      <span
                        className={cn(
                          "shrink-0 font-meta text-[0.5rem] tracking-[0.14em]",
                          r.status === "complete" && "text-archive-sage",
                          r.status === "running" && "text-narrator-gold",
                          r.status === "failed" && "text-hero-red",
                        )}
                      >
                        {r.status.toUpperCase()}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Surface>
        </div>
      </div>

      <section className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3 border-b-[2px] border-ink-black pb-3">
          <div>
            <div className="ui-kicker">RESULTS</div>
            <h2 className="ui-title">
              {activeRun ? activeRun.label : "No run selected"}
            </h2>
          </div>
          {activeRun && (
            <div className="font-meta text-[0.62rem] tracking-[0.14em] text-ink-black/55">
              {activeRun.cells_done}/{activeRun.cells_total} cells ·{" "}
              {formatCost(activeRun.total_cost_usd)} ·{" "}
              <span
                className={cn(
                  activeRun.status === "complete" && "text-archive-sage",
                  activeRun.status === "running" && "text-narrator-gold",
                  activeRun.status === "failed" && "text-hero-red",
                )}
              >
                {activeRun.status.toUpperCase()}
              </span>
            </div>
          )}
        </div>

        {activeRun ? (
          <ResultsGrid
            panels={activeRun.panels}
            models={models}
            modelIds={activeRun.model_ids}
          />
        ) : (
          <div className="border-[2px] border-dashed border-ink-black/20 p-10 text-center font-meta text-[0.72rem] tracking-[0.16em] text-ink-black/40">
            Run an experiment or select a past run to see results
          </div>
        )}
      </section>
    </div>
  );
}
