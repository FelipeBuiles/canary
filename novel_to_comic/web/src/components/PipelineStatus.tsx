import { useState } from "react";
import { runPipeline, approveStage } from "../api";
import { STAGE_NAMES, CHECKPOINT_STAGES } from "../types";
import type { ProjectStatus } from "../types";

interface Props {
  project: string;
  status: ProjectStatus;
  onRunStarted: () => void;
  onApproved: () => void;
  running: boolean;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "#aaa",
  running: "#3b82f6",
  awaiting_review: "#f59e0b",
  complete: "#22c55e",
  failed: "#ef4444",
};

export function PipelineStatus({ project, status, onRunStarted, onApproved, running }: Props) {
  const [error, setError] = useState<string | null>(null);

  async function handleRun(stage?: string) {
    setError(null);
    try {
      await runPipeline(project, stage);
      onRunStarted();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleApprove(stage: string) {
    setError(null);
    try {
      await approveStage(project, stage);
      onApproved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>Pipeline</h2>
        <button
          onClick={() => handleRun()}
          disabled={running}
          style={{ padding: "4px 12px", fontSize: 13 }}
        >
          {running ? "Running..." : "Run All"}
        </button>
        <span style={{ color: "#888", fontSize: 13 }}>
          Total cost: ${status.total_cost_usd.toFixed(2)}
        </span>
      </div>

      {error && <p style={{ color: "#ef4444", fontSize: 13, margin: "0 0 8px" }}>{error}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ borderBottom: "2px solid #ddd", textAlign: "left" }}>
            <th style={{ padding: "6px 8px" }}>Stage</th>
            <th style={{ padding: "6px 8px" }}>Status</th>
            <th style={{ padding: "6px 8px" }}>Progress</th>
            <th style={{ padding: "6px 8px" }}>Cost</th>
            <th style={{ padding: "6px 8px" }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {STAGE_NAMES.map((name) => {
            const s = status.stages[name];
            if (!s) return null;
            const isCheckpoint = CHECKPOINT_STAGES.has(name);
            return (
              <tr key={name} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "6px 8px", fontWeight: 500 }}>
                  {name}
                  {isCheckpoint && <span style={{ color: "#f59e0b", marginLeft: 4 }} title="Checkpoint stage">*</span>}
                </td>
                <td style={{ padding: "6px 8px" }}>
                  <span
                    style={{
                      display: "inline-block",
                      padding: "2px 8px",
                      borderRadius: 4,
                      fontSize: 12,
                      backgroundColor: STATUS_COLORS[s.status] ?? "#aaa",
                      color: "#fff",
                    }}
                  >
                    {s.status.replace("_", " ")}
                  </span>
                </td>
                <td style={{ padding: "6px 8px", color: "#666" }}>
                  {s.items_total > 0 ? `${s.items_done}/${s.items_total}` : "—"}
                  {s.items_failed.length > 0 && (
                    <span style={{ color: "#ef4444", marginLeft: 4 }}>
                      ({s.items_failed.length} failed)
                    </span>
                  )}
                </td>
                <td style={{ padding: "6px 8px", color: "#666" }}>
                  {s.cost_usd > 0 ? `$${s.cost_usd.toFixed(3)}` : "—"}
                </td>
                <td style={{ padding: "6px 8px" }}>
                  {s.status === "awaiting_review" && (
                    <button
                      onClick={() => handleApprove(name)}
                      style={{ padding: "2px 8px", fontSize: 12, cursor: "pointer" }}
                    >
                      Approve
                    </button>
                  )}
                  {(s.status === "pending" || s.status === "failed") && (
                    <button
                      onClick={() => handleRun(name)}
                      disabled={running}
                      style={{ padding: "2px 8px", fontSize: 12, cursor: "pointer" }}
                    >
                      Run
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {status.stages.assemble?.error && (
        <p style={{ color: "#ef4444", fontSize: 13, marginTop: 8 }}>
          Error: {status.stages.assemble.error}
        </p>
      )}
    </div>
  );
}
