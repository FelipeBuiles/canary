import { useEffect, useState } from "react";
import { listPages, pageThumbnailUrl } from "../api";
import { PagePreview } from "./PagePreview";
import type { PageSummary } from "../types";

interface Props {
  project: string;
}

export function PageBrowser({ project }: Props) {
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);

  useEffect(() => {
    listPages(project).then((p) => {
      setPages(p);
      setSelectedPage(null);
    }).catch(console.error);
  }, [project]);

  if (pages.length === 0) {
    return (
      <div>
        <h2 style={{ fontSize: 16, marginBottom: 8 }}>Pages</h2>
        <p style={{ color: "#888", fontSize: 14 }}>
          No pages yet. Run stages through "assemble" first.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h2 style={{ fontSize: 16, marginBottom: 8 }}>
        Pages
        <span style={{ fontWeight: 400, color: "#888", marginLeft: 8, fontSize: 13 }}>
          {pages.length} pages
        </span>
      </h2>

      {/* Thumbnail strip */}
      <div
        style={{
          display: "flex",
          gap: 8,
          overflowX: "auto",
          paddingBottom: 8,
          marginBottom: 16,
        }}
      >
        {pages.map((p) => (
          <div
            key={p.page_number}
            onClick={() => setSelectedPage(p.page_number)}
            style={{
              cursor: "pointer",
              border: selectedPage === p.page_number ? "2px solid #3b82f6" : "2px solid #ddd",
              borderRadius: 4,
              padding: 2,
              flexShrink: 0,
            }}
          >
            <img
              src={pageThumbnailUrl(project, p.page_number)}
              alt={`Page ${p.page_number}`}
              style={{ width: 80, height: 113, objectFit: "cover", display: "block" }}
            />
            <div style={{ fontSize: 11, textAlign: "center", padding: 2, color: "#666" }}>
              {p.page_number}
            </div>
          </div>
        ))}
      </div>

      {/* Preview */}
      {selectedPage && <PagePreview project={project} pageNum={selectedPage} />}
    </div>
  );
}
