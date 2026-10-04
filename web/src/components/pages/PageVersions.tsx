import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCompletePage } from "../../api/queries";
import { pageRenderPreviewUrl, selectPageRender } from "../../api/pages";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { PageArtwork } from "./PageArtwork";
import { InspectButton } from "../ui/InspectButton";
import { invalidateProject } from "../../api/projectScope";

export function PageVersions({ project, pageNumber, activeRevision, disabled, onSelected }: {
  project: string;
  pageNumber: number;
  activeRevision: number | null;
  disabled: boolean;
  onSelected: () => void;
}) {
  const { t } = useI18n();
  const detail = useCompletePage(project, pageNumber);
  const qc = useQueryClient();
  const [preview, setPreview] = useState<number | null>(null);
  const revision = preview ?? activeRevision;
  const render = detail.data?.renders.find((item) => item.render.revision === revision)?.render;
  const stale = render && detail.data && (render.comic_page_sha256 !== detail.data.page.content_sha256 || render.comic_page_revision !== detail.data.page.revision);
  const select = useMutation({
    mutationFn: (chosen: number) => selectPageRender(project, pageNumber, chosen, activeRevision!),
    onSuccess: async () => {
      await invalidateProject(qc, project);
      onSelected();
    },
  });

  return <section aria-label={t("Versions")} className="space-y-4">
    <h3 className="font-display text-2xl font-black">{t("Choose your best version")}</h3>
    <p className="max-w-prose text-sm leading-6 text-ink-muted">{t("The selected version is used for reading, export and your next correction. Every version stays saved. Choosing one costs no credits.")}</p>
    {detail.isLoading && <p role="status">{t("Loading…")}</p>}
    {detail.error && <div role="alert"><p>{t("Versions could not be loaded.")}</p><Button variant="outline" onClick={() => void detail.refetch()}>{t("Try again")}</Button></div>}
    {detail.data && <>
      <div className="flex gap-3 overflow-x-auto pb-3" role="group" aria-label={t("Preview a version")}>
        {detail.data.renders.map(({ render: item }) => <button
          key={item.revision} type="button" aria-pressed={revision === item.revision}
          onClick={() => { setPreview(item.revision); select.reset(); }}
          className={`w-28 shrink-0 border-2 p-2 text-left ${revision === item.revision ? "border-ink-black bg-bristol" : "border-transparent hover:border-ink-black/30"}`}
        >
          <img loading="lazy" className="aspect-[2/3] w-full object-contain" alt="" src={pageRenderPreviewUrl(project, pageNumber, item.revision, "thumbnail")} />
          <span className="mt-2 block font-meta text-xs">{t("Revision")} {item.revision}</span>
          {item.revision === activeRevision && <span className="text-xs font-bold">{t("Selected")}</span>}
        </button>)}
      </div>
      {revision != null && <>
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={disabled || select.isPending || revision === activeRevision || !!stale || activeRevision == null}
            onClick={() => select.mutate(revision)}>
            {select.isPending ? t("Selecting…") : revision === activeRevision ? t("Selected version") : t("Use this version")}
          </Button>
          {stale && <p className="text-sm">{t("This version belongs to an earlier page plan.")}</p>}
          {select.error && <p role="alert" className="text-sm text-hero-red">{select.error.message}</p>}
        </div>
        <div className="relative h-[75vh]">
          <PageArtwork src={pageRenderPreviewUrl(project, pageNumber, revision, "reader")}
            alt={`${t("Page")} ${pageNumber}, ${t("Revision")} ${revision}`} />
          <InspectButton
            images={detail.data.renders.map(({ render: item }) => ({
              src: pageRenderPreviewUrl(project, pageNumber, item.revision, "reader"),
              alt: `${t("Page")} ${pageNumber}, ${t("Revision")} ${item.revision}`,
            }))}
            index={Math.max(0, detail.data.renders.findIndex(({ render: item }) => item.revision === revision))}
            onIndexChange={(next) => { setPreview(detail.data.renders[next].render.revision); select.reset(); }}
          />
        </div>
      </>}
    </>}
  </section>;
}
