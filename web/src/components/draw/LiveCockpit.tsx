import { useEffect, useState } from "react";
import {
  useInFlight,
  useRecentFinishes,
  computeThroughputPerMin,
  computeEtaSeconds,
  formatEta,
  formatRelative,
} from "../../store/drawProgress";
import { Surface } from "../ui/Surface";

// ── Donut summary (kept from old DrawRoom, adapted) ─────────────────────────

export function PanelProgressDonut({
  generated,
  pending,
  failed,
  total,
}: {
  generated: number;
  pending: number;
  failed: number;
  total: number;
}) {
  const R = 32;
  const C = 2 * Math.PI * R;
  const genPct = total > 0 ? generated / total : 0;
  const failPct = total > 0 ? failed / total : 0;
  const pendPct = total > 0 ? pending / total : 0;
  const genLen = genPct * C;
  const failLen = failPct * C;
  const pendLen = pendPct * C;

  return (
    <div className="flex items-center gap-4">
      <svg width={80} height={80} viewBox="0 0 80 80" className="shrink-0 -rotate-90">
        <circle cx={40} cy={40} r={R} fill="none" stroke="currentColor" strokeWidth={9}
          className="text-ink-black/8" />
        {pendLen > 0 && (
          <circle cx={40} cy={40} r={R} fill="none" stroke="currentColor" strokeWidth={9}
            strokeDasharray={`${pendLen} ${C - pendLen}`}
            strokeDashoffset={0}
            className="text-narrator-gold/70" />
        )}
        {failLen > 0 && (
          <circle cx={40} cy={40} r={R} fill="none" stroke="currentColor" strokeWidth={9}
            strokeDasharray={`${failLen} ${C - failLen}`}
            strokeDashoffset={-pendLen}
            className="text-hero-red" />
        )}
        {genLen > 0 && (
          <circle cx={40} cy={40} r={R} fill="none" stroke="currentColor" strokeWidth={9}
            strokeDasharray={`${genLen} ${C - genLen}`}
            strokeDashoffset={-(pendLen + failLen)}
            className="text-archive-sage" />
        )}
      </svg>
      <div className="space-y-1.5 text-[0.7rem]">
        <Legend dot="bg-archive-sage" label="Generated" value={generated} />
        <Legend dot="bg-narrator-gold/70" label="Pending" value={pending} />
        <Legend dot="bg-hero-red" label="Failed" value={failed} />
      </div>
    </div>
  );
}

function Legend({ dot, label, value }: { dot: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
      <span className="text-ink-black/60">{label}</span>
      <span className="ml-auto font-bold text-ink-black">{value}</span>
    </div>
  );
}

// ── Stale banner ─────────────────────────────────────────────────────────────

export function StaleStripe({
  lastProgressAt,
  onContinue,
  onReset,
  continuing,
  resetting,
}: {
  lastProgressAt: string | null;
  onContinue: () => void;
  onReset: () => void;
  continuing: boolean;
  resetting: boolean;
}) {
  const ago = lastProgressAt ? formatRelative(Date.parse(lastProgressAt)) : null;
  const busy = continuing || resetting;
  return (
    <div className="mb-4 border-[2px] border-hero-red bg-hero-red/8 p-3">
      <div className="font-meta text-[0.55rem] tracking-[0.18em] text-hero-red">
        STAGE STUCK
      </div>
      <div className="mt-1 text-[0.78rem] leading-snug text-ink-black">
        {ago ? `Last progress ${ago} ago — server may have stopped.` : "Server may have stopped working on this stage."}
      </div>
      <div className="mt-1 text-[0.7rem] leading-snug text-ink-black/65">
        Continue asks the server to resume pending panels and keeps generated art.
      </div>
      <button
        type="button"
        onClick={onContinue}
        disabled={busy}
        className="mt-2 w-full border-[2px] border-ink-black bg-narrator-gold px-3 py-1.5 font-meta text-[0.6rem] tracking-[0.14em] text-ink-black transition-colors hover:bg-bristol disabled:cursor-not-allowed disabled:opacity-60"
      >
        {continuing ? "CONTINUING..." : "CONTINUE DRAW"}
      </button>
      <button
        type="button"
        onClick={onReset}
        disabled={busy}
        className="mt-2 w-full border-[2px] border-hero-red bg-bristol px-3 py-1.5 font-meta text-[0.6rem] tracking-[0.14em] text-hero-red transition-colors hover:bg-hero-red hover:text-bristol disabled:cursor-not-allowed disabled:opacity-60"
      >
        {resetting ? "RESETTING..." : "RESET STAGE"}
      </button>
    </div>
  );
}

// ── Live progress strip (progress bar + ETA + throughput) ────────────────────

export function LiveProgressStrip({
  itemsDone,
  itemsTotal,
  project,
}: {
  itemsDone: number;
  itemsTotal: number;
  project: string;
}) {
  const finishes = useRecentFinishes(project);
  // Re-render every 5s so the sliding window stays fresh even when no
  // events arrive (e.g. between batches).
  useTick(5_000);
  const throughput = computeThroughputPerMin(finishes);
  const remaining = Math.max(0, itemsTotal - itemsDone);
  const eta = computeEtaSeconds(remaining, throughput);
  const pct = itemsTotal > 0 ? Math.min(100, Math.round((itemsDone / itemsTotal) * 100)) : 0;

  return (
    <div className="mt-4 space-y-2">
      <div className="h-2 w-full bg-ink-black/10">
        <div
          className="h-full bg-narrator-gold transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex items-baseline justify-between font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/60">
        <span>ETA {formatEta(eta)}</span>
        <span>{throughput == null ? "—" : `${throughput.toFixed(1)} / MIN`}</span>
      </div>
    </div>
  );
}

// ── In-flight list ───────────────────────────────────────────────────────────

export function InFlightCard({ project }: { project: string }) {
  const inFlight = useInFlight(project);
  useTick(1_000); // elapsed time updates every second
  if (inFlight.length === 0) return null;
  // Longest-running first — surfaces stuck panels.
  const sorted = [...inFlight].sort((a, b) => a.startedAt - b.startedAt);
  return (
    <Surface border="soft" shadow="none" padding="md">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="font-meta text-[0.58rem] tracking-[0.24em] text-ink-black/40">
          IN FLIGHT
        </div>
        <div className="font-meta text-[0.58rem] tracking-[0.14em] text-narrator-gold">
          {sorted.length}
        </div>
      </div>
      <ul className="space-y-1.5 text-[0.72rem]">
        {sorted.map((p) => (
          <li key={`${p.sceneId}-${p.panelNumber}`} className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-narrator-gold animate-pulse" />
            <span className="truncate text-ink-black/85">
              {formatPanelLabel(p.sceneId, p.panelNumber)}
            </span>
            <span className="ml-auto font-meta text-[0.58rem] tracking-[0.1em] text-ink-black/45">
              {formatRelative(p.startedAt)}
            </span>
          </li>
        ))}
      </ul>
    </Surface>
  );
}

// ── Recent finishes ──────────────────────────────────────────────────────────

export function RecentFinishesCard({ project }: { project: string }) {
  const finishes = useRecentFinishes(project);
  if (finishes.length === 0) return null;
  return (
    <Surface border="soft" shadow="none" padding="md">
      <div className="mb-3 font-meta text-[0.58rem] tracking-[0.24em] text-ink-black/40">
        RECENT FINISHES
      </div>
      <ul className="space-y-1.5 text-[0.72rem]">
        {finishes.map((f, i) => (
          <li
            key={`${f.sceneId}-${f.panelNumber}-${f.finishedAt}-${i}`}
            className="flex items-center gap-2"
          >
            <span
              className={`font-bold ${f.status === "ok" ? "text-archive-sage" : "text-hero-red"}`}
              aria-hidden
            >
              {f.status === "ok" ? "✓" : "✗"}
            </span>
            <span className="truncate text-ink-black/85">
              {formatPanelLabel(f.sceneId, f.panelNumber)}
            </span>
            <span className="ml-auto font-meta text-[0.58rem] tracking-[0.1em] text-ink-black/45">
              {f.status === "failed" ? "failed" : formatDuration(f.durationMs)}
            </span>
          </li>
        ))}
      </ul>
    </Surface>
  );
}

// ── Per-scene progress ───────────────────────────────────────────────────────

export interface SceneProgress {
  sceneId: string;
  generated: number;
  failed: number;
  total: number;
}

export function BySceneCard({
  scenes,
  defaultExpanded = false,
}: {
  scenes: SceneProgress[];
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  if (scenes.length === 0) return null;
  // Auto-expand on any failure.
  const hasFailure = scenes.some((s) => s.failed > 0);
  const isOpen = expanded || hasFailure;
  return (
    <Surface border="soft" shadow="none" padding="md">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-baseline justify-between"
      >
        <div className="font-meta text-[0.58rem] tracking-[0.24em] text-ink-black/40">
          BY SCENE
        </div>
        <span className="font-meta text-[0.58rem] tracking-[0.14em] text-ink-black/40">
          {isOpen ? "▾" : "▸"}
        </span>
      </button>
      {isOpen && (
        <ul className="mt-3 space-y-2 text-[0.7rem]">
          {scenes.map((s) => {
            const pct = s.total > 0 ? Math.round((s.generated / s.total) * 100) : 0;
            return (
              <li key={s.sceneId} className="space-y-1">
                <div className="flex items-baseline justify-between">
                  <span className="truncate text-ink-black/80">
                    {s.sceneId.replace(/_/g, " ").toUpperCase()}
                  </span>
                  <span className="font-meta text-[0.56rem] tracking-[0.12em] text-ink-black/50">
                    {s.generated}/{s.total}
                    {s.failed > 0 && (
                      <span className="ml-1 text-hero-red">· {s.failed} failed</span>
                    )}
                  </span>
                </div>
                <div className="h-1.5 w-full bg-ink-black/8">
                  <div
                    className="h-full bg-archive-sage"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Surface>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatPanelLabel(sceneId: string, panelNumber: number): string {
  // "scene_03 / 08"
  const num = String(panelNumber).padStart(2, "0");
  return `${sceneId.replace(/_/g, "_")} / ${num}`;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.round(s / 60)}m`;
}

function useTick(intervalMs: number) {
  const [, setT] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setT((t) => t + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
