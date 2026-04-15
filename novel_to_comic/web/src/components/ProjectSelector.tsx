import type { ProjectSummary } from "../types";

interface Props {
  projects: ProjectSummary[];
  selected: string | null;
  onSelect: (name: string) => void;
}

export function ProjectSelector({ projects, selected, onSelect }: Props) {
  if (projects.length === 0) {
    return <p style={{ color: "#888" }}>No projects found. Create one with <code>pipeline init</code>.</p>;
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <label style={{ fontWeight: 600, marginRight: 8 }}>Project:</label>
      <select
        value={selected ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        style={{ padding: "6px 12px", fontSize: 14 }}
      >
        <option value="" disabled>
          Select a project...
        </option>
        {projects.map((p) => (
          <option key={p.name} value={p.name}>
            {p.project_name || p.name}
            {p.furthest_stage ? ` (${p.furthest_stage})` : ""}
            {p.total_cost_usd > 0 ? ` — $${p.total_cost_usd.toFixed(2)}` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
