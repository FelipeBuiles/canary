import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  useCreateLabsRun,
  useDeleteLabsRun,
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
  LabsImportedReference,
  LabsModel,
  LabsPanel,
  LabsReferenceSource,
  LabsRunCreatePayload,
  LabsTier,
} from "../api/labs";
import { Button } from "../components/ui/Button";
import { Surface } from "../components/ui/Surface";
import { cn } from "../lib/cn";
import { Select } from "../components/ui/Select";

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
  singleSelect?: boolean;
}

function ModelPicker({ models, selected, onToggle, disabled, singleSelect }: ModelPickerProps) {
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
                      type={singleSelect ? "radio" : "checkbox"}
                      name={singleSelect ? "labs-model" : undefined}
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
  compareMode?: boolean;
  onAdd: () => void;
  onRemove: (idx: number) => void;
}

function ScenePanelEditor({ panels, onChange, disabled, compareMode, onAdd, onRemove }: ScenePanelEditorProps) {
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
            <div className="flex shrink-0 items-center gap-2">
              <span className="font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/35">
                {p.width}×{p.height}
              </span>
              <button
                type="button"
                disabled={disabled || panels.length <= 1}
                onClick={() => onRemove(p.idx)}
                className="font-meta text-[0.5rem] font-bold tracking-[0.14em] text-hero-red/70 hover:text-hero-red disabled:cursor-not-allowed disabled:opacity-30"
              >
                REMOVE
              </button>
            </div>
          </div>
          <div className={cn("mt-1 grid gap-2", compareMode && "md:grid-cols-2")}>
            <label className="block">
              {compareMode && (
                <span className="font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/45">
                  PROMPT A
                </span>
              )}
              <textarea
                value={p.prompt}
                disabled={disabled}
                onChange={(e) => setPanel(p.idx, { prompt: e.target.value })}
                rows={3}
                className="mt-1 w-full resize-y border-[1.5px] border-ink-black/15 bg-pulp-paper px-2.5 py-2 font-body text-[0.84rem] leading-snug text-ink-black focus:border-ink-black focus:outline-none"
                placeholder="Prompt for this panel"
              />
            </label>
            {compareMode && (
              <label className="block">
                <span className="font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/45">
                  PROMPT B
                </span>
                <textarea
                  value={p.prompt_variant_b ?? ""}
                  disabled={disabled}
                  onChange={(e) => setPanel(p.idx, { prompt_variant_b: e.target.value })}
                  rows={3}
                  className="mt-1 w-full resize-y border-[1.5px] border-ink-black/15 bg-pulp-paper px-2.5 py-2 font-body text-[0.84rem] leading-snug text-ink-black focus:border-ink-black focus:outline-none"
                  placeholder="Prompt B for this panel"
                />
              </label>
            )}
          </div>
        </div>
      ))}
      <button
        type="button"
        disabled={disabled}
        onClick={onAdd}
        className="w-full border-[2px] border-dashed border-ink-black/20 bg-pulp-paper px-3 py-2 font-meta text-[0.62rem] font-bold tracking-[0.14em] text-ink-black/55 hover:border-ink-black hover:text-ink-black disabled:cursor-not-allowed disabled:opacity-40"
      >
        ADD PANEL
      </button>
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
  panels: { idx: number; variant: "A" | "B"; label: string; prompt: string; cells: Record<string, LabsCell> }[];
  models: LabsModel[];
  modelIds: string[];
  promptCompareMode?: boolean;
}

interface LightboxTarget {
  panelIdx: number;
  variant: "A" | "B";
  modelId: string;
}

interface ResultColumn {
  key: string;
  modelId: string;
  variant?: "A" | "B";
}

interface ResultRow {
  key: string;
  idx: number;
  variant?: "A" | "B";
  label: string;
  prompt: string;
  variants: Partial<Record<"A" | "B", ResultsGridProps["panels"][number]>>;
}

const CELL_SIZE_PX = 240;
const PANEL_COL_PX = 240;

function ResultsGrid({ panels, models, modelIds, promptCompareMode }: ResultsGridProps) {
  const modelMap = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);
  const [lightbox, setLightbox] = useState<LightboxTarget | null>(null);
  const columns = useMemo<ResultColumn[]>(
    () => promptCompareMode
      ? modelIds.flatMap((modelId) => [
          { key: `${modelId}:A`, modelId, variant: "A" as const },
          { key: `${modelId}:B`, modelId, variant: "B" as const },
        ])
      : modelIds.map((modelId) => ({ key: modelId, modelId })),
    [modelIds, promptCompareMode],
  );
  const rows = useMemo<ResultRow[]>(() => {
    if (!promptCompareMode) {
      return panels.map((panel) => ({
        key: `${panel.idx}:${panel.variant}`,
        idx: panel.idx,
        variant: panel.variant,
        label: panel.label,
        prompt: panel.prompt,
        variants: { [panel.variant]: panel },
      }));
    }
    const grouped = new Map<number, ResultRow>();
    for (const panel of panels) {
      const existing = grouped.get(panel.idx);
      if (existing) {
        existing.variants[panel.variant] = panel;
        if (panel.variant === "A") {
          existing.label = panel.label;
          existing.prompt = panel.prompt;
        }
      } else {
        grouped.set(panel.idx, {
          key: String(panel.idx),
          idx: panel.idx,
          label: panel.label,
          prompt: panel.prompt,
          variants: { [panel.variant]: panel },
        });
      }
    }
    return [...grouped.values()].sort((a, b) => a.idx - b.idx);
  }, [panels, promptCompareMode]);
  const columnSummaries = useMemo(() => {
    const summaries = new Map<string, { cost: number; costCount: number; latencyMs: number; latencyCount: number }>();
    for (const col of columns) {
      summaries.set(col.key, { cost: 0, costCount: 0, latencyMs: 0, latencyCount: 0 });
    }
    for (const panel of panels) {
      for (const col of columns) {
        if (col.variant && panel.variant !== col.variant) continue;
        const cell = panel.cells[col.modelId];
        if (!cell || cell.status !== "ok") continue;
        const summary = summaries.get(col.key);
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
  }, [columns, panels]);

  if (!modelIds.length || !panels.length) {
    return (
      <div className="border-[2px] border-dashed border-ink-black/20 p-10 text-center font-meta text-[0.72rem] tracking-[0.16em] text-ink-black/40">
        No results yet
      </div>
    );
  }

  function openLightbox(panelIdx: number, variant: "A" | "B", modelId: string) {
    setLightbox({ panelIdx, variant, modelId });
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0" style={{ tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: PANEL_COL_PX }} />
            {columns.map((col) => (
              <col key={col.key} style={{ width: CELL_SIZE_PX + 24 }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="sticky left-0 z-10 border-b-[2px] border-ink-black bg-pulp-paper p-3 text-left align-bottom">
                <span className="font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/45">
                  PANEL
                </span>
              </th>
              {columns.map((col) => {
                const m = modelMap.get(col.modelId);
                const summary = columnSummaries.get(col.key);
                const avgLatency =
                  summary && summary.latencyCount > 0
                    ? Math.round(summary.latencyMs / summary.latencyCount)
                    : null;
                return (
                  <th key={col.key} className="border-b-[2px] border-ink-black p-3 text-left align-bottom">
                    {col.variant && (
                      <div className="mb-1 inline-flex bg-narrator-gold/45 px-2 py-0.5 font-meta text-[0.48rem] font-bold tracking-[0.16em] text-ink-black/65">
                        PROMPT {col.variant}
                      </div>
                    )}
                    <div className="line-clamp-2 font-display text-[0.92rem] font-bold leading-tight">
                      {m?.label ?? col.modelId}
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
            {rows.map((row) => (
              <tr key={row.key} className="align-top">
                <td className="sticky left-0 z-10 border-b border-ink-black/10 bg-pulp-paper p-3">
                  <div className="font-meta text-[0.56rem] font-bold tracking-[0.16em] text-ink-black/55">
                    PANEL {row.idx}{!promptCompareMode && row.variant !== "A" ? ` / ${row.variant}` : ""}
                  </div>
                  <div className="mt-1 font-display text-[0.84rem] font-bold leading-tight">
                    {row.label}
                  </div>
                  {promptCompareMode ? (
                    <div className="mt-2 space-y-1.5">
                      {(["A", "B"] as const).map((variant) => {
                        const panel = row.variants[variant];
                        if (!panel) return null;
                        return (
                          <p key={variant} className="line-clamp-3 font-body text-[0.72rem] leading-snug text-ink-black/52">
                            <span className="font-meta text-[0.56rem] font-bold tracking-[0.12em] text-ink-black/45">
                              {variant}
                            </span>{" "}
                            {panel.prompt}
                          </p>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="mt-2 line-clamp-6 font-body text-[0.72rem] leading-snug text-ink-black/52">
                      {row.prompt}
                    </p>
                  )}
                </td>
                {columns.map((col) => {
                  const variant = col.variant ?? row.variant ?? "A";
                  const panel = row.variants[variant];
                  const cell = panel?.cells[col.modelId] ?? { status: "pending" as const };
                  return (
                    <td key={col.key} className="border-b border-ink-black/10 p-3">
                      <CellView
                        cell={cell}
                        onOpen={() => openLightbox(row.idx, variant, col.modelId)}
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
          columns={columns}
          rowKeys={promptCompareMode
            ? rows.map((row) => ({ idx: row.idx }))
            : rows.map((row) => ({ idx: row.idx, variant: row.variant ?? "A" }))
          }
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
  panels: { idx: number; variant: "A" | "B"; label: string; prompt: string; cells: Record<string, LabsCell> }[];
  columns: ResultColumn[];
  rowKeys: { idx: number; variant?: "A" | "B" }[];
  modelMap: Map<string, LabsModel>;
  onClose: () => void;
  onNavigate: (target: LightboxTarget) => void;
}

function Lightbox({ target, panels, columns, rowKeys, modelMap, onClose, onNavigate }: LightboxProps) {
  const panel = panels.find((p) => p.idx === target.panelIdx && p.variant === target.variant);
  const cell = panel?.cells[target.modelId];
  const model = modelMap.get(target.modelId);

  const colIdx = columns.findIndex(
    (col) => col.modelId === target.modelId && (col.variant ?? target.variant) === target.variant,
  );
  const prevCol = colIdx > 0 ? columns[colIdx - 1] : null;
  const nextCol = colIdx >= 0 && colIdx < columns.length - 1 ? columns[colIdx + 1] : null;

  const rowPos = rowKeys.findIndex(
    (row) => row.idx === target.panelIdx && (row.variant ?? target.variant) === target.variant,
  );
  const prevRow = rowPos > 0 ? rowKeys[rowPos - 1] : null;
  const nextRow = rowPos >= 0 && rowPos < rowKeys.length - 1 ? rowKeys[rowPos + 1] : null;

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
      if (event.key === "ArrowLeft" && prevCol) {
        navigate({
          panelIdx: target.panelIdx,
          variant: prevCol.variant ?? target.variant,
          modelId: prevCol.modelId,
        });
      } else if (event.key === "ArrowRight" && nextCol) {
        navigate({
          panelIdx: target.panelIdx,
          variant: nextCol.variant ?? target.variant,
          modelId: nextCol.modelId,
        });
      } else if (event.key === "ArrowUp" && prevRow) {
        navigate({ panelIdx: prevRow.idx, variant: prevRow.variant ?? target.variant, modelId: target.modelId });
      } else if (event.key === "ArrowDown" && nextRow) {
        navigate({ panelIdx: nextRow.idx, variant: nextRow.variant ?? target.variant, modelId: target.modelId });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, prevCol, nextCol, prevRow, nextRow, navigate, onClose]);

  if (!panel || !cell) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-black/80 p-6"
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
                {panel.variant !== "A" ? ` / ${panel.variant}` : ""}
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
              disabled={!prevCol}
              onClick={() => prevCol && navigate({
                panelIdx: target.panelIdx,
                variant: prevCol.variant ?? target.variant,
                modelId: prevCol.modelId,
              })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              ← COLUMN
            </button>
            <button
              type="button"
              disabled={!nextCol}
              onClick={() => nextCol && navigate({
                panelIdx: target.panelIdx,
                variant: nextCol.variant ?? target.variant,
                modelId: nextCol.modelId,
              })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              COLUMN →
            </button>
            <button
              type="button"
              disabled={!prevRow}
              onClick={() => prevRow && navigate({ panelIdx: prevRow.idx, variant: prevRow.variant ?? target.variant, modelId: target.modelId })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              ↑ PANEL
            </button>
            <button
              type="button"
              disabled={!nextRow}
              onClick={() => nextRow && navigate({ panelIdx: nextRow.idx, variant: nextRow.variant ?? target.variant, modelId: target.modelId })}
              className="border-[2px] border-ink-black/15 bg-pulp-paper px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] hover:border-ink-black disabled:cursor-not-allowed disabled:opacity-40"
            >
              PANEL ↓
            </button>
          </div>
          <p className="font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/40">
            ← → for columns · ↑ ↓ for panels · Esc to close
          </p>
        </div>
      </div>
    </div>
  );
}

type SceneSource = "fixture" | "imported";

const DEFAULT_MODEL_PICKS = ["flux-2-pro-edit", "seedream-v4-5-edit", "gemini-3-pro-vertex-native-proxy"];

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
  const [importProductionPayload, setImportProductionPayload] = useState(false);
  const { data: importScenes } = useLabsProjectScenes(
    sceneSource === "imported" ? importProjectId || undefined : undefined,
  );
  const importScene = useImportLabsScene();

  const [styleTemplate, setStyleTemplate] = useState(fixture.default_style_template);
  const [panels, setPanels] = useState<LabsPanel[]>(fixture.panels);
  const [importedRefs, setImportedRefs] = useState<LabsImportedReference[]>([]);
  const [importedRefPaths, setImportedRefPaths] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<Set<string>>(
    () => new Set(DEFAULT_MODEL_PICKS.filter((id) => models.some((m) => m.id === id))),
  );
  const [runLabel, setRunLabel] = useState(fixture.label);
  const [promptCompareMode, setPromptCompareMode] = useState(false);

  const createRun = useCreateLabsRun();
  const deleteRun = useDeleteLabsRun();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const { data: activeRun } = useLabsRun(activeRunId ?? undefined);
  const { data: runsList } = useLabsRuns();

  function handleSceneSource(next: SceneSource) {
    setSceneSource(next);
    if (next === "fixture") {
      setStyleTemplate(fixture.default_style_template);
      setPanels(fixture.panels.map((panel) => ({
        ...panel,
        prompt_variant_b: promptCompareMode ? panel.prompt : panel.prompt_variant_b,
      })));
      setImportedRefPaths([]);
      setImportedRefs([]);
      setRunLabel(fixture.label);
    } else {
      setPanels([]);
      setImportedRefPaths([]);
      setImportedRefs([]);
      setRunLabel("");
    }
  }

  function toggleModel(id: string) {
    setSelectedModels((current) => {
      if (promptCompareMode) {
        return new Set([id]);
      }
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handlePromptCompareMode(next: boolean) {
    setPromptCompareMode(next);
    if (next) {
      setSelectedModels((current) => {
        const first = [...current][0] ?? models[0]?.id;
        return first ? new Set([first]) : new Set();
      });
      setPanels((current) => current.map((panel) => ({
        ...panel,
        prompt_variant_b: panel.prompt_variant_b || panel.prompt,
      })));
    }
  }

  function nextPanelIdx(): number {
    return Math.max(0, ...panels.map((panel) => panel.idx)) + 1;
  }

  function handleAddPanel() {
    const idx = nextPanelIdx();
    setPanels((current) => [
      ...current,
      {
        idx,
        label: `Panel ${idx}`,
        prompt: "",
        prompt_variant_b: promptCompareMode ? "" : null,
        width: 1024,
        height: 1024,
      },
    ]);
  }

  function handleRemovePanel(idx: number) {
    setPanels((current) => current.length <= 1 ? current : current.filter((panel) => panel.idx !== idx));
  }

  async function handleImport() {
    if (!importProjectId || !importSceneId) return;
    try {
      const result = await importScene.mutateAsync({
        projectId: importProjectId,
        sceneId: importSceneId,
        panelLimit: 8,
      });
      if (importProductionPayload) {
        // Exact S7 replay: the production prompt embeds the style section,
        // so the experiment-level style template must stay empty.
        setStyleTemplate("");
        setPanels(result.panels.map((panel) => ({
          ...panel,
          prompt: panel.production_prompt || panel.prompt,
          prompt_variant_b: promptCompareMode ? (panel.prompt_variant_b ?? panel.prompt) : panel.prompt_variant_b,
        })));
      } else {
        setStyleTemplate(result.style_template);
        setPanels(result.panels.map((panel) => ({
          ...panel,
          prompt_variant_b: promptCompareMode ? (panel.prompt_variant_b ?? panel.prompt) : panel.prompt_variant_b,
        })));
      }
      const refs = result.imported_references ?? [];
      setImportedRefs(refs);
      setImportedRefPaths(
        refs.length ? refs.map((ref) => ref.path) : result.imported_reference_paths,
      );
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
      prompt_compare_mode: promptCompareMode,
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

  async function handleDeleteRun(runId: string, label?: string) {
    const ok = window.confirm(`Delete experiment "${label || runId}"? This removes its images and metadata.`);
    if (!ok) return;
    try {
      await deleteRun.mutateAsync(runId);
      if (activeRunId === runId) {
        setActiveRunId(null);
      }
    } catch (err) {
      console.error("delete run failed", err);
    }
  }

  const selectedCount = selectedModels.size;
  const hasPrompts = panels.every((panel) => panel.prompt.trim().length > 0);
  const hasComparePrompts = panels.every((panel) => (panel.prompt_variant_b || "").trim().length > 0);
  const runDisabled = !selectedCount || !panels.length || !hasPrompts || (promptCompareMode && !hasComparePrompts) || createRun.isPending;

  const fixtureRefThumbs =
    sceneSource === "fixture"
      ? fixture.reference_images.map((r) => ({ url: r.url, label: r.label }))
      : [];
  const importedRefThumbs =
    sceneSource === "imported"
      ? importedRefs.map((r) => ({ url: r.url, label: r.label }))
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
                  <Select
                    aria-label="Import project"
                    value={importProjectId}
                    onValueChange={(value) => {
                      setImportProjectId(value);
                      setImportSceneId("");
                      setImportedRefs([]);
                      setImportedRefPaths([]);
                    }}
                    options={[
                      { value: "", label: "— Project —" },
                      ...(importableProjects?.projects ?? []).map((p) => ({
                        value: p.id,
                        label: `${p.name} · ${p.scene_count} scenes`,
                      })),
                    ]}
                  />
                  <Select
                    aria-label="Import scene"
                    value={importSceneId}
                    onValueChange={(value) => {
                      setImportSceneId(value);
                      setImportedRefs([]);
                      setImportedRefPaths([]);
                    }}
                    disabled={!importProjectId}
                    options={[
                      { value: "", label: "— Scene —" },
                      ...(importScenes?.scenes ?? []).map((scene) => ({
                        value: scene.scene_id,
                        label: `${scene.scene_id} · ${scene.panel_count} panels`,
                      })),
                    ]}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!importProjectId || !importSceneId || importScene.isPending}
                    onClick={handleImport}
                  >
                    {importScene.isPending ? "IMPORTING…" : "IMPORT"}
                  </Button>
                </div>
                <label className="flex cursor-pointer items-center gap-2 font-meta text-[0.62rem] tracking-[0.12em] text-ink-black/70">
                  <input
                    type="checkbox"
                    checked={importProductionPayload}
                    onChange={(e) => setImportProductionPayload(e.target.checked)}
                    className="h-3.5 w-3.5 accent-ink-black"
                  />
                  REPLAY PRODUCTION PAYLOAD
                  <span className="normal-case tracking-normal text-ink-black/45">
                    exact S7 prompt incl. style &amp; constraints — style template stays empty
                  </span>
                </label>
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

          {sceneSource === "imported" && (
            <div>
              <div className="ui-kicker">REFERENCE IMAGES</div>
              <div className="mt-3">
                <ReferencePreview urls={importedRefThumbs} />
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
                  compareMode={promptCompareMode}
                  onAdd={handleAddPanel}
                  onRemove={handleRemovePanel}
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

            <label className="flex items-center justify-between gap-3 border-[2px] border-ink-black/15 bg-pulp-paper px-3 py-2">
              <span className="font-meta text-[0.62rem] tracking-[0.14em] text-ink-black/70">
                Compare two prompts
              </span>
              <input
                type="checkbox"
                checked={promptCompareMode}
                disabled={createRun.isPending}
                onChange={(e) => handlePromptCompareMode(e.target.checked)}
                className="h-4 w-4 accent-hero-red"
              />
            </label>

            <div>
              <div className="ui-kicker mb-2">MODELS ({selectedCount} SELECTED)</div>
              <ModelPicker
                models={models}
                selected={selectedModels}
                onToggle={toggleModel}
                disabled={createRun.isPending}
                singleSelect={promptCompareMode}
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
                : `RUN EXPERIMENT → ${selectedCount * panels.length * (promptCompareMode ? 2 : 1)} CELLS`}
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
                  <li key={r.run_id} className="flex items-stretch gap-1">
                    <button
                      type="button"
                      onClick={() => setActiveRunId(r.run_id)}
                      className={cn(
                        "flex min-w-0 flex-1 items-center justify-between gap-3 border-l-[3px] px-3 py-2 text-left transition-colors",
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
                    <button
                      type="button"
                      disabled={deleteRun.isPending}
                      onClick={() => handleDeleteRun(r.run_id, r.label)}
                      className="shrink-0 border-l border-ink-black/10 px-2 font-meta text-[0.54rem] font-bold tracking-[0.14em] text-ink-black/35 transition-colors hover:bg-chip-red/30 hover:text-hero-red disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label={`Delete ${r.label || r.run_id}`}
                      title="Delete experiment"
                    >
                      DELETE
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
            <div className="flex flex-wrap items-center gap-3">
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
              <button
                type="button"
                disabled={deleteRun.isPending}
                onClick={() => handleDeleteRun(activeRun.run_id, activeRun.label)}
                className="border-[2px] border-hero-red/35 px-2 py-1 font-meta text-[0.56rem] font-bold tracking-[0.14em] text-hero-red hover:bg-chip-red/30 disabled:cursor-not-allowed disabled:opacity-40"
              >
                DELETE
              </button>
            </div>
          )}
        </div>

        {activeRun ? (
          <ResultsGrid
            panels={activeRun.panels}
            models={models}
            modelIds={activeRun.model_ids}
            promptCompareMode={activeRun.prompt_compare_mode}
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
