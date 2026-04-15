import { jsxs as _jsxs, jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { getConfig, updateConfig } from "../api";
// Fields to show in a compact editor (non-secret, commonly edited)
const EDITABLE_FIELDS = [
    "style_template",
    "comic_theme",
    "max_panels_per_scene",
    "max_panels_per_page",
    "max_words_per_bubble",
    "parallel_batch_size",
    "max_concurrent_requests",
    "image_model",
    "extraction_model",
    "screenplay_model",
];
export function ConfigPanel({ project }) {
    const [config, setConfig] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    useEffect(() => {
        getConfig(project).then(setConfig).catch(console.error);
    }, [project]);
    async function handleSave(field, value) {
        setSaving(true);
        setError(null);
        try {
            // Try to parse as number if applicable
            let parsed = value;
            if (typeof config?.[field] === "number") {
                const n = Number(value);
                if (!isNaN(n))
                    parsed = n;
            }
            const updated = await updateConfig(project, { [field]: parsed });
            setConfig(updated);
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
        finally {
            setSaving(false);
        }
    }
    if (!config)
        return null;
    return (_jsxs("div", { children: [_jsxs("h2", { style: { fontSize: 16, marginBottom: 8, cursor: "pointer" }, onClick: () => setExpanded(!expanded), children: ["Config ", expanded ? "▼" : "▶"] }), error && _jsx("p", { style: { color: "#ef4444", fontSize: 13 }, children: error }), expanded && (_jsx("div", { style: { fontSize: 13 }, children: EDITABLE_FIELDS.map((field) => {
                    const val = config[field];
                    if (val === undefined)
                        return null;
                    const isTextarea = field === "style_template";
                    return (_jsxs("div", { style: { marginBottom: 8 }, children: [_jsx("label", { style: { display: "block", fontWeight: 500, marginBottom: 2 }, children: field }), isTextarea ? (_jsx("textarea", { defaultValue: String(val), onBlur: (e) => handleSave(field, e.target.value), disabled: saving, rows: 3, style: { width: "100%", fontSize: 12, fontFamily: "monospace" } })) : (_jsx("input", { defaultValue: String(val), onBlur: (e) => handleSave(field, e.target.value), disabled: saving, style: { width: "100%", fontSize: 12, padding: "3px 6px" } }))] }, field));
                }) }))] }));
}
