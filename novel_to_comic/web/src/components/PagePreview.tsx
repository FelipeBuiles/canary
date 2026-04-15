import { pagePreviewUrl } from "../api";

interface Props {
  project: string;
  pageNum: number;
}

export function PagePreview({ project, pageNum }: Props) {
  return (
    <div>
      <h3 style={{ fontSize: 14, marginBottom: 8 }}>Page {pageNum} Preview</h3>
      <iframe
        src={pagePreviewUrl(project, pageNum)}
        style={{
          width: "100%",
          height: 700,
          border: "1px solid #ddd",
          borderRadius: 4,
        }}
        title={`Page ${pageNum} preview`}
      />
    </div>
  );
}
