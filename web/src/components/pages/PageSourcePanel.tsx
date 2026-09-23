import { useState } from "react";
import { usePageSource } from "../../api/queries";
import { pageRenderPreviewUrl } from "../../api/pages";
import { pageCompositePreviewUrl } from "../../api/lettering";
import { useI18n } from "../../i18n";
import type { CompletePageSummary, PageSourceSegment } from "../../types/api";
import { SectionHeader } from "../composites/SectionHeader";
import { Surface } from "../ui/Surface";

const metaClass = "font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted";
const markClass: Record<"lettering" | "depicted", string> = {
  lettering: "bg-narrator-gold text-ink-black",
  depicted: "bg-transparent text-ink-black underline decoration-hero-red decoration-2 underline-offset-4",
};

function panelList(ids: string[], order: Map<string, number>) {
  return ids.map((id) => order.get(id)).filter((value): value is number => value != null).join(", ");
}

/**
 * Where this page came from: the manuscript passages its beats and lettering
 * cite. Lettering is panel-level; depiction is beat-level. Panel outlines are
 * derived from the render's text check and appear only for the art shown.
 */
export function PageSourcePanel({ project, item }: { project: string; item: CompletePageSummary }) {
  const { t } = useI18n();
  const pageNumber = item.page.page_number;
  const { data, error, isLoading } = usePageSource(project, pageNumber);
  const [active, setActive] = useState<string[]>([]);
  const revision = item.active_render?.render.revision;
  const order = new Map((data?.panels ?? []).map((panel) => [panel.id, panel.order]));
  const outlined = data && revision != null && data.geometry_render_revision === revision
    ? data.panels.filter((panel) => panel.box)
    : [];
  const outlinedIds = new Set(outlined.map((panel) => panel.id));

  if (isLoading) return <p role="status" className="font-body text-sm text-ink-muted">{t("Loading source passages…")}</p>;
  if (error || !data) {
    const detail = error instanceof Error ? error.message.replace(/^API \d+:\s*/, "") : "";
    return <Surface padding="lg" border="soft" shadow="none">
      <p role="alert" className="font-body text-sm font-semibold">{t("The source for this page is not available.")}</p>
      {detail && <p className="mt-2 font-body text-xs text-ink-muted">{detail}</p>}
    </Surface>;
  }

  // A render helper, not a component: a nested component type would remount
  // every mark on hover and drop keyboard focus.
  function renderMark(key: string, segment: PageSourceSegment, kind: "lettering" | "depicted") {
    const linked = segment.content_ids.filter((id) => outlinedIds.has(id));
    const panels = panelList(segment.content_ids, order);
    const label = kind === "lettering" ? t("Lettered in panel {panels}") : t("Drawn in panel {panels}");
    const isActive = linked.length > 0 && linked.some((id) => active.includes(id));
    return <mark
      key={key}
      className={`${markClass[kind]} box-decoration-clone transition-shadow motion-reduce:transition-none ${linked.length > 0 ? "cursor-default focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red" : ""} ${isActive ? "shadow-[0_0_0_2px_var(--color-ink-black)]" : ""}`}
      title={panels ? label.replace("{panels}", panels) : undefined}
      data-kind={kind}
      tabIndex={linked.length > 0 ? 0 : undefined}
      onMouseEnter={linked.length > 0 ? () => setActive(linked) : undefined}
      onMouseLeave={linked.length > 0 ? () => setActive([]) : undefined}
      onFocus={linked.length > 0 ? () => setActive(linked) : undefined}
      onBlur={linked.length > 0 ? () => setActive([]) : undefined}
    >{segment.text}</mark>;
  }

  const art = revision == null ? null : item.lettering_mode === "hybrid"
    ? pageCompositePreviewUrl(project, pageNumber, revision, "reader", item.lettering_revision)
    : pageRenderPreviewUrl(project, pageNumber, revision, "reader");

  return <div className="grid gap-8 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] lg:items-start">
    <div className="lg:sticky lg:top-0">
      {art ? <figure className="mx-auto max-w-sm lg:max-w-none">
        <div className="relative border-[3px] border-ink-black bg-bristol">
          <img src={art} alt={`${t("Page")} ${pageNumber}`} className="block h-auto w-full" />
          {outlined.map((panel) => panel.box && <div
            key={panel.id}
            data-testid={`source-panel-${panel.id}`}
            aria-hidden="true"
            className={`pointer-events-none absolute border-[3px] border-hero-red shadow-[3px_3px_0_var(--color-ink-black)] transition-opacity duration-150 motion-reduce:transition-none ${active.includes(panel.id) ? "opacity-100" : "opacity-0"}`}
            style={{
              left: `${panel.box.x * 100}%`, top: `${panel.box.y * 100}%`,
              width: `${panel.box.width * 100}%`, height: `${panel.box.height * 100}%`,
            }}
          >
            <span className="absolute left-0 top-0 bg-hero-red px-1.5 py-0.5 font-meta text-[10px] font-bold text-bristol">{t("Panel")} {panel.order}</span>
          </div>)}
        </div>
        <figcaption className="mt-3 font-body text-xs leading-5 text-ink-muted">
          {outlined.length > 0
            ? t("Point at a highlight to outline its panel. Outlines come from the page's text check and can be approximate.")
            : t("Panel outlines are not available for this artwork.")}
        </figcaption>
      </figure> : <p className="font-body text-sm text-ink-muted">{t("This page has not been drawn yet.")}</p>}
    </div>
    <section className="min-w-0">
      <SectionHeader variant="underline" title={t("Source passages")}
        description={t("The manuscript this page adapts, with the words that became lettering or drawn details.")} />
      <ul className="mb-6 flex flex-wrap gap-x-6 gap-y-2 font-body text-xs" aria-label={t("Highlight key")}>
        <li className="flex items-center gap-2"><span aria-hidden="true" className="inline-block h-3 w-5 bg-narrator-gold" />{t("Became lettering")}</li>
        <li className="flex items-center gap-2"><span aria-hidden="true" className="inline-block h-0 w-5 border-b-2 border-hero-red" />{t("Drawn on this page")}</li>
      </ul>
      {data.passages.length === 0 && <p className="font-body text-sm text-ink-muted">{t("This page cites no manuscript passages.")}</p>}
      <div className="space-y-8">
        {data.passages.map((passage, index) => <article key={passage.units[0]?.id ?? index}>
          {passage.scene_title && <h3 className={`${metaClass} mb-3`}>{passage.scene_title}</h3>}
          <p className="max-w-[68ch] whitespace-pre-wrap font-body text-[0.95rem] leading-8">
            {passage.units.flatMap((unit) => unit.segments.map((segment, segmentIndex) => {
              const key = `${unit.id}:${segmentIndex}`;
              return segment.kind
                ? renderMark(key, segment, segment.kind)
                : <span key={key} className="text-ink-muted">{segment.text}</span>;
            }))}
          </p>
        </article>)}
      </div>
    </section>
  </div>;
}
