import { useState, useEffect, useCallback } from "react";
import { listProjects, getStatus } from "./api";
import type { ProjectSummary, ProjectStatus } from "./types";
import { ProjectSelector } from "./components/ProjectSelector";
import { PipelineStatus } from "./components/PipelineStatus";
import { EventLog } from "./components/EventLog";
import { PageBrowser } from "./components/PageBrowser";
import { ExportPanel } from "./components/ExportPanel";
import { ConfigPanel } from "./components/ConfigPanel";
import { useSSE } from "./hooks/useSSE";

export function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<ProjectStatus | null>(null);
  const sse = useSSE(selected);

  // Load project list on mount
  useEffect(() => {
    listProjects().then(setProjects).catch(console.error);
  }, []);

  const refreshStatus = useCallback(() => {
    if (!selected) return;
    getStatus(selected).then(setStatus).catch(console.error);
  }, [selected]);

  // Load status when project changes
  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // Refresh status when SSE stream ends
  useEffect(() => {
    if (!sse.connected && sse.events.length > 0) {
      refreshStatus();
    }
  }, [sse.connected, sse.events.length, refreshStatus]);

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 24, marginBottom: 24 }}>
        Canary <span style={{ fontWeight: 400, color: "#888" }}>Novel to Comic</span>
      </h1>

      <ProjectSelector
        projects={projects}
        selected={selected}
        onSelect={setSelected}
      />

      {selected && status && (
        <>
          <PipelineStatus
            project={selected}
            status={status}
            onRunStarted={sse.connect}
            onApproved={refreshStatus}
            running={sse.connected}
          />

          <EventLog events={sse.events} connected={sse.connected} />

          <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 24, marginTop: 24 }}>
            <PageBrowser project={selected} />
            <div>
              <ExportPanel project={selected} />
              <ConfigPanel project={selected} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
