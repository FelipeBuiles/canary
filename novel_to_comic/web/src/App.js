import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState, useEffect, useCallback } from "react";
import { listProjects, getStatus } from "./api";
import { ProjectSelector } from "./components/ProjectSelector";
import { PipelineStatus } from "./components/PipelineStatus";
import { EventLog } from "./components/EventLog";
import { PageBrowser } from "./components/PageBrowser";
import { ExportPanel } from "./components/ExportPanel";
import { ConfigPanel } from "./components/ConfigPanel";
import { useSSE } from "./hooks/useSSE";
export function App() {
    const [projects, setProjects] = useState([]);
    const [selected, setSelected] = useState(null);
    const [status, setStatus] = useState(null);
    const sse = useSSE(selected);
    // Load project list on mount
    useEffect(() => {
        listProjects().then(setProjects).catch(console.error);
    }, []);
    const refreshStatus = useCallback(() => {
        if (!selected)
            return;
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
    return (_jsxs("div", { style: { fontFamily: "system-ui, sans-serif", maxWidth: 1200, margin: "0 auto", padding: 24 }, children: [_jsxs("h1", { style: { fontSize: 24, marginBottom: 24 }, children: ["Canary ", _jsx("span", { style: { fontWeight: 400, color: "#888" }, children: "Novel to Comic" })] }), _jsx(ProjectSelector, { projects: projects, selected: selected, onSelect: setSelected }), selected && status && (_jsxs(_Fragment, { children: [_jsx(PipelineStatus, { project: selected, status: status, onRunStarted: sse.connect, onApproved: refreshStatus, running: sse.connected }), _jsx(EventLog, { events: sse.events, connected: sse.connected }), _jsxs("div", { style: { display: "grid", gridTemplateColumns: "1fr 320px", gap: 24, marginTop: 24 }, children: [_jsx(PageBrowser, { project: selected }), _jsxs("div", { children: [_jsx(ExportPanel, { project: selected }), _jsx(ConfigPanel, { project: selected })] })] })] }))] }));
}
