import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { projectPath } from "../../api/projectScope";

interface Archive {
  id: string;
  created_at: number;
  page_count: number;
  files: string[];
}

export function ArchivedArtwork({ project }: { project: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const archives = useQuery({
    queryKey: ["project", project, "restart-archives"],
    queryFn: () => apiFetch<{ archives: Archive[] }>(`${projectPath(project)}/restart-archives`),
  });
  const artworkArchives = archives.data?.archives.filter((archive) => archive.files.length > 0) ?? [];
  if (artworkArchives.length === 0) return null;

  return <details className="my-4 border-y border-ink-black/20 py-2" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm">{t("Archived artwork")}</summary>
    {open && <div className="space-y-3 pb-3 text-sm leading-6">
      <p>{t("Previous artwork is kept for viewing and download. It does not belong to the current page plan.")}</p>
      {archives.error && <div role="alert"><p>{t("Archived artwork could not be loaded.")}</p><Button variant="outline" onClick={() => void archives.refetch()}>{t("Try again")}</Button></div>}
      {artworkArchives.map((archive) => <details key={archive.id}>
        <summary className="min-h-11 cursor-pointer py-3">{new Date(archive.created_at * 1000).toLocaleString()} · {t("{count} drawn pages", { count: archive.page_count })}</summary>
        <ul className="max-h-96 space-y-2 overflow-auto py-2">
          {archive.files.map((file) => <li key={file} className="[overflow-wrap:anywhere]">
            <a className="inline-block min-h-11 py-3 underline underline-offset-4" target="_blank" rel="noreferrer"
              href={`/api${projectPath(project)}/restart-archives/${archive.id}/file?path=${encodeURIComponent(file)}`}>
              {file}
            </a>
          </li>)}
        </ul>
      </details>)}
    </div>}
  </details>;
}
