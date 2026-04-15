import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function ProjectSelector({ projects, selected, onSelect }) {
    if (projects.length === 0) {
        return _jsxs("p", { style: { color: "#888" }, children: ["No projects found. Create one with ", _jsx("code", { children: "pipeline init" }), "."] });
    }
    return (_jsxs("div", { style: { marginBottom: 24 }, children: [_jsx("label", { style: { fontWeight: 600, marginRight: 8 }, children: "Project:" }), _jsxs("select", { value: selected ?? "", onChange: (e) => onSelect(e.target.value), style: { padding: "6px 12px", fontSize: 14 }, children: [_jsx("option", { value: "", disabled: true, children: "Select a project..." }), projects.map((p) => (_jsxs("option", { value: p.name, children: [p.project_name || p.name, p.furthest_stage ? ` (${p.furthest_stage})` : "", p.total_cost_usd > 0 ? ` — $${p.total_cost_usd.toFixed(2)}` : ""] }, p.name)))] })] }));
}
