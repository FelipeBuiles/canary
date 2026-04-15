import { useEffect, useState } from "react";
import { getConfig, updateConfig } from "../api";
import type { ConfigData } from "../types";

interface Props {
  project: string;
}

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
] as const;

export function ConfigPanel({ project }: Props) {
  const [config, setConfig] = useState<ConfigData | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getConfig(project).then(setConfig).catch(console.error);
  }, [project]);

  async function handleSave(field: string, value: string) {
    setSaving(true);
    setError(null);
    try {
      // Try to parse as number if applicable
      let parsed: string | number = value;
      if (typeof config?.[field] === "number") {
        const n = Number(value);
        if (!isNaN(n)) parsed = n;
      }
      const updated = await updateConfig(project, { [field]: parsed });
      setConfig(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (!config) return null;

  return (
    <div>
      <h2
        style={{ fontSize: 16, marginBottom: 8, cursor: "pointer" }}
        onClick={() => setExpanded(!expanded)}
      >
        Config {expanded ? "▼" : "▶"}
      </h2>
      {error && <p style={{ color: "#ef4444", fontSize: 13 }}>{error}</p>}
      {expanded && (
        <div style={{ fontSize: 13 }}>
          {EDITABLE_FIELDS.map((field) => {
            const val = config[field];
            if (val === undefined) return null;
            const isTextarea = field === "style_template";
            return (
              <div key={field} style={{ marginBottom: 8 }}>
                <label style={{ display: "block", fontWeight: 500, marginBottom: 2 }}>
                  {field}
                </label>
                {isTextarea ? (
                  <textarea
                    defaultValue={String(val)}
                    onBlur={(e) => handleSave(field, e.target.value)}
                    disabled={saving}
                    rows={3}
                    style={{ width: "100%", fontSize: 12, fontFamily: "monospace" }}
                  />
                ) : (
                  <input
                    defaultValue={String(val)}
                    onBlur={(e) => handleSave(field, e.target.value)}
                    disabled={saving}
                    style={{ width: "100%", fontSize: 12, padding: "3px 6px" }}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
