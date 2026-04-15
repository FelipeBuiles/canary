import { useState } from "react";
import { triggerExport, exportDownloadUrl } from "../api";

interface Props {
  project: string;
}

export function ExportPanel({ project }: Props) {
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function handleExport(format: "pdf" | "cbz") {
    setExporting(true);
    setError(null);
    setDone(null);
    try {
      await triggerExport(project, format);
      setDone(format);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>Export</h2>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={() => handleExport("pdf")}
          disabled={exporting}
          style={{ padding: "6px 16px", fontSize: 13 }}
        >
          {exporting ? "Exporting..." : "Export PDF"}
        </button>
        <button
          onClick={() => handleExport("cbz")}
          disabled={exporting}
          style={{ padding: "6px 16px", fontSize: 13 }}
        >
          Export CBZ
        </button>
      </div>
      {error && <p style={{ color: "#ef4444", fontSize: 13, marginTop: 8 }}>{error}</p>}
      {done && (
        <p style={{ fontSize: 13, marginTop: 8 }}>
          Export ready:{" "}
          <a href={exportDownloadUrl(project, done)} download>
            Download {done.toUpperCase()}
          </a>
        </p>
      )}
    </div>
  );
}
