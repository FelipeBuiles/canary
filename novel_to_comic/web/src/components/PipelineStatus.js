import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { runPipeline, approveStage } from "../api";
import { STAGE_NAMES, CHECKPOINT_STAGES } from "../types";
const STATUS_COLORS = {
    pending: "#aaa",
    running: "#3b82f6",
    awaiting_review: "#f59e0b",
    complete: "#22c55e",
    failed: "#ef4444",
};
export function PipelineStatus({ project, status, onRunStarted, onApproved, running }) {
    const [error, setError] = useState(null);
    async function handleRun(stage) {
        setError(null);
        try {
            await runPipeline(project, stage);
            onRunStarted();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }
    async function handleApprove(stage) {
        setError(null);
        try {
            await approveStage(project, stage);
            onApproved();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
    }
    return (_jsxs("div", { style: { marginBottom: 24 }, children: [_jsxs("div", { style: { display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }, children: [_jsx("h2", { style: { fontSize: 18, margin: 0 }, children: "Pipeline" }), _jsx("button", { onClick: () => handleRun(), disabled: running, style: { padding: "4px 12px", fontSize: 13 }, children: running ? "Running..." : "Run All" }), _jsxs("span", { style: { color: "#888", fontSize: 13 }, children: ["Total cost: $", status.total_cost_usd.toFixed(2)] })] }), error && _jsx("p", { style: { color: "#ef4444", fontSize: 13, margin: "0 0 8px" }, children: error }), _jsxs("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: 14 }, children: [_jsx("thead", { children: _jsxs("tr", { style: { borderBottom: "2px solid #ddd", textAlign: "left" }, children: [_jsx("th", { style: { padding: "6px 8px" }, children: "Stage" }), _jsx("th", { style: { padding: "6px 8px" }, children: "Status" }), _jsx("th", { style: { padding: "6px 8px" }, children: "Progress" }), _jsx("th", { style: { padding: "6px 8px" }, children: "Cost" }), _jsx("th", { style: { padding: "6px 8px" }, children: "Actions" })] }) }), _jsx("tbody", { children: STAGE_NAMES.map((name) => {
                            const s = status.stages[name];
                            if (!s)
                                return null;
                            const isCheckpoint = CHECKPOINT_STAGES.has(name);
                            return (_jsxs("tr", { style: { borderBottom: "1px solid #eee" }, children: [_jsxs("td", { style: { padding: "6px 8px", fontWeight: 500 }, children: [name, isCheckpoint && _jsx("span", { style: { color: "#f59e0b", marginLeft: 4 }, title: "Checkpoint stage", children: "*" })] }), _jsx("td", { style: { padding: "6px 8px" }, children: _jsx("span", { style: {
                                                display: "inline-block",
                                                padding: "2px 8px",
                                                borderRadius: 4,
                                                fontSize: 12,
                                                backgroundColor: STATUS_COLORS[s.status] ?? "#aaa",
                                                color: "#fff",
                                            }, children: s.status.replace("_", " ") }) }), _jsxs("td", { style: { padding: "6px 8px", color: "#666" }, children: [s.items_total > 0 ? `${s.items_done}/${s.items_total}` : "—", s.items_failed.length > 0 && (_jsxs("span", { style: { color: "#ef4444", marginLeft: 4 }, children: ["(", s.items_failed.length, " failed)"] }))] }), _jsx("td", { style: { padding: "6px 8px", color: "#666" }, children: s.cost_usd > 0 ? `$${s.cost_usd.toFixed(3)}` : "—" }), _jsxs("td", { style: { padding: "6px 8px" }, children: [s.status === "awaiting_review" && (_jsx("button", { onClick: () => handleApprove(name), style: { padding: "2px 8px", fontSize: 12, cursor: "pointer" }, children: "Approve" })), (s.status === "pending" || s.status === "failed") && (_jsx("button", { onClick: () => handleRun(name), disabled: running, style: { padding: "2px 8px", fontSize: 12, cursor: "pointer" }, children: "Run" }))] })] }, name));
                        }) })] }), status.stages.assemble?.error && (_jsxs("p", { style: { color: "#ef4444", fontSize: 13, marginTop: 8 }, children: ["Error: ", status.stages.assemble.error] }))] }));
}
