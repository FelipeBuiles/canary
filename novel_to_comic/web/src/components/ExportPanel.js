import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { triggerExport, exportDownloadUrl } from "../api";
export function ExportPanel({ project }) {
    const [exporting, setExporting] = useState(false);
    const [error, setError] = useState(null);
    const [done, setDone] = useState(null);
    async function handleExport(format) {
        setExporting(true);
        setError(null);
        setDone(null);
        try {
            await triggerExport(project, format);
            setDone(format);
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
        finally {
            setExporting(false);
        }
    }
    return (_jsxs("div", { style: { marginBottom: 24 }, children: [_jsx("h2", { style: { fontSize: 16, marginBottom: 8 }, children: "Export" }), _jsxs("div", { style: { display: "flex", gap: 8 }, children: [_jsx("button", { onClick: () => handleExport("pdf"), disabled: exporting, style: { padding: "6px 16px", fontSize: 13 }, children: exporting ? "Exporting..." : "Export PDF" }), _jsx("button", { onClick: () => handleExport("cbz"), disabled: exporting, style: { padding: "6px 16px", fontSize: 13 }, children: "Export CBZ" })] }), error && _jsx("p", { style: { color: "#ef4444", fontSize: 13, marginTop: 8 }, children: error }), done && (_jsxs("p", { style: { fontSize: 13, marginTop: 8 }, children: ["Export ready:", " ", _jsxs("a", { href: exportDownloadUrl(project, done), download: true, children: ["Download ", done.toUpperCase()] })] }))] }));
}
