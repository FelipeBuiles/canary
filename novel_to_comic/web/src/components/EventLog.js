import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
const LEVEL_COLORS = {
    info: "#3b82f6",
    warn: "#f59e0b",
    error: "#ef4444",
    dim: "#999",
    bold: "#111",
};
function formatEvent(e) {
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
export function EventLog({ events, connected }) {
    const endRef = useRef(null);
    useEffect(() => {
        endRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [events.length]);
    if (events.length === 0 && !connected)
        return null;
    return (_jsxs("div", { style: { marginBottom: 24 }, children: [_jsxs("h2", { style: { fontSize: 16, marginBottom: 8 }, children: ["Event Log", connected && (_jsx("span", { style: { color: "#22c55e", fontSize: 12, marginLeft: 8 }, children: "\u25CF live" }))] }), _jsxs("div", { style: {
                    maxHeight: 240,
                    overflow: "auto",
                    backgroundColor: "#1a1a2e",
                    color: "#e0e0e0",
                    borderRadius: 6,
                    padding: 12,
                    fontFamily: "monospace",
                    fontSize: 13,
                    lineHeight: 1.6,
                }, children: [events.map((e, i) => (_jsx("div", { style: {
                            color: e.type === "stage_fail" || e.level === "error"
                                ? "#ef4444"
                                : e.type === "log"
                                    ? LEVEL_COLORS[e.level ?? "info"]
                                    : "#e0e0e0",
                        }, children: formatEvent(e) }, i))), _jsx("div", { ref: endRef })] })] }));
}
