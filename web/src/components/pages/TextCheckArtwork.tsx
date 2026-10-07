import { useCompletePage } from "../../api/queries";
import { pageRenderUrl } from "../../api/pages";
import { useI18n } from "../../i18n";
import type { PageIssue } from "../../types/api";
import { normalizeLettering as normalize, readTextEvidence } from "./lettering";

/** Display evidence from the exact revision the checker saw, never a newer redraw. */
export function TextCheckArtwork({ project, issue }: { project: string; issue: PageIssue }) {
  const { t } = useI18n();
  const { data } = useCompletePage(project, issue.page_number);
  const render = data?.renders.find((item) => item.render.revision === issue.render_revision)?.render;
  const analysis = data?.analyses.find((item) => item.render_revision === issue.render_revision
    && item.render_image_sha256 === render?.image_sha256);
  const expected = new Set((readTextEvidence(issue, "expected_text=") ?? []).map(normalize));
  const regions = (analysis?.ocr_observations ?? []).flatMap((observation) => {
    if (expected.has(normalize(observation.text))) return [];
    // The OCR adapter retains a tight region for every observation, separately
    // from its containing panel (which is used only for reading order).
    const region = analysis?.observed_regions?.find((item) => item.id === observation.id.replace(/^ocr_/, "region_"));
    if (!region?.polygon.length) return [];
    const x = Math.max(0, Math.min(...region.polygon.map((point) => point[0])) - 0.01);
    const y = Math.max(0, Math.min(...region.polygon.map((point) => point[1])) - 0.01);
    const width = Math.min(1, Math.max(...region.polygon.map((point) => point[0])) + 0.01) - x;
    const height = Math.min(1, Math.max(...region.polygon.map((point) => point[1])) + 0.01) - y;
    return width > 0 && height > 0 ? [{ id: region.id, x, y, width, height }] : [];
  });
  const src = pageRenderUrl(project, issue.page_number, issue.render_revision);
  return <div className="space-y-3">
    {render && regions.map((region) => <a key={region.id} href={src} target="_blank" rel="noreferrer"
      className="block max-w-2xl overflow-hidden bg-pulp-paper" aria-label={t("Open full-size artwork")}
      style={{ aspectRatio: `${region.width * render.width} / ${region.height * render.height}` }}>
      <svg role="img" aria-label={t("Saved artwork near the possible text difference")}
        className="h-full w-full" viewBox={`${region.x * render.width} ${region.y * render.height} ${region.width * render.width} ${region.height * render.height}`}>
        <image href={src} width={render.width} height={render.height} />
      </svg>
    </a>)}
    <a href={src} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center font-meta text-xs font-bold underline underline-offset-4">
      {t("Open full-size artwork")} · {t("Revision")} {issue.render_revision}
    </a>
  </div>;
}
