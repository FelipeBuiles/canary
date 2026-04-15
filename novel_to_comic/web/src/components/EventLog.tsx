import { useEffect, useRef } from "react";
import type { PipelineEvent } from "../types";

interface Props {
  events: PipelineEvent[];
  connected: boolean;
}

const LEVEL_COLORS: Record<string, string> = {
  info: "#3b82f6",
  warn: "#f59e0b",
  error: "#ef4444",
  dim: "#999",
  bold: "#111",
};

function formatEvent(e: PipelineEvent): string {
  switch (e.type) {
    case "stage_begin":
      return `[${e.stage}] Started (${e.total} items)`;
    case "stage_progress":
      return `[${e.stage}] ${e.done}/${e.total}`;
    case "stage_complete":
      return `[${e.stage}] Complete (${e.done}/${e.total})`;
    case "stage_fail":
      return `[${e.stage}] FAILED: ${e.message}`;
    case "log":
      return `[${e.stage}] ${e.message}`;
    case "pipeline_done":
      return "Pipeline run finished.";
    default:
      return JSON.stringify(e);
  }
}

export function EventLog({ events, connected }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  if (events.length === 0 && !connected) return null;

  return (
    <div style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>
        Event Log
        {connected && (
          <span style={{ color: "#22c55e", fontSize: 12, marginLeft: 8 }}>
            ● live
          </span>
        )}
      </h2>
      <div
        style={{
          maxHeight: 240,
          overflow: "auto",
          backgroundColor: "#1a1a2e",
          color: "#e0e0e0",
          borderRadius: 6,
          padding: 12,
          fontFamily: "monospace",
          fontSize: 13,
          lineHeight: 1.6,
        }}
      >
        {events.map((e, i) => (
          <div
            key={i}
            style={{
              color:
                e.type === "stage_fail" || e.level === "error"
                  ? "#ef4444"
                  : e.type === "log"
                    ? LEVEL_COLORS[e.level ?? "info"]
                    : "#e0e0e0",
            }}
          >
            {formatEvent(e)}
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
