import { useState } from "react";
import { elementRect } from "@lettering-engine";
import { usePageSource } from "../../api/queries";
import { pageRenderPreviewUrl } from "../../api/pages";
import { pageCompositePreviewUrl } from "../../api/lettering";
import { useI18n } from "../../i18n";
import type { CompletePageSummary, PageSourceLettering, PageSourceSegment, PageSourceView } from "../../types/api";
import { SectionHeader } from "../composites/SectionHeader";
import { Surface } from "../ui/Surface";
import { InspectButton } from "../ui/InspectButton";
import { ErrorNotice } from "../composites/ErrorNotice";

const metaClass = "font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted";
const markClass: Record<"lettering" | "depicted", string> = {
  lettering: "bg-narrator-gold text-ink-black",
  depicted: "bg-transparent text-ink-black underline decoration-hero-red decoration-2 underline-offset-4",
};
// Text-check regions are tight around glyphs; pad so the outline clears them.
const REGION_PAD = 0.008;

interface Outline { left: number; top: number; width: number; height: number; rotation: number }

/** Outline of one lettering item on the art shown, or null when it cannot be placed. */
function outlineFor(item: PageSourceLettering): Outline | null {
  if (item.element) {
    // The shared engine owns the drawn body; scale and rotation apply about its center.
    const rect = elementRect(item.element);
    const width = rect.width * item.element.scale, height = rect.height * item.element.scale;
    return {
      left: rect.x + rect.width / 2 - width / 2, top: rect.y + rect.height / 2 - height / 2,
      width, height, rotation: item.element.rotation,
    };
  }
  if (item.region) {
    const left = Math.max(0, item.region.x - REGION_PAD), top = Math.max(0, item.region.y - REGION_PAD);
    return {
      left, top, rotation: 0,
      width: Math.min(1, item.region.x + item.region.width + REGION_PAD) - left,
      height: Math.min(1, item.region.y + item.region.height + REGION_PAD) - top,
    };
  }
  return null;
}

/** Positions count only when measured on the exact artwork this tab displays. */
function geometryMatches(data: PageSourceView, item: CompletePageSummary): boolean {
  const geometry = data.geometry;
  if (!geometry) return false;
  if (geometry.source === "lettering_placement") {
    return item.lettering_mode === "hybrid" && geometry.lettering_revision === item.lettering_revision;
  }
  return item.lettering_mode !== "hybrid" && geometry.render_revision === item.active_render?.render.revision;
}

/**
 * Where this page came from: the manuscript passages its beats and lettering
 * cite. The drawing model composes the page, so only lettering is located on
 * the art; drawn detail is marked in the text but never pinned to a place.
 */
export function PageSourcePanel({ project, item }: { project: string; item: CompletePageSummary }) {
  const { t } = useI18n();
  const pageNumber = item.page.page_number;
  const { data, error, isLoading, refetch } = usePageSource(project, pageNumber);
  const [active, setActive] = useState<string[]>([]);
  const revision = item.active_render?.render.revision;

  if (isLoading) return <p role="status" className="font-body text-sm text-ink-muted">{t("Loading source passages…")}</p>;
  if (error || !data) {
    return <Surface padding="lg" border="soft" shadow="none">
      <ErrorNotice error={error} operation="load" title="The source for this page is not available." onRetry={() => void refetch()} />
    </Surface>;
  }

  const lettering = new Map(data.lettering.map((entry) => [entry.id, entry]));
  const outlines = geometryMatches(data, item)
    ? data.lettering.flatMap((entry) => {
      const outline = outlineFor(entry);
      return outline ? [{ id: entry.id, outline }] : [];
    })
    : [];
  const locatedIds = new Set(outlines.map((entry) => entry.id));

  // A render helper, not a component: a nested component type would remount
  // every mark on hover and drop keyboard focus.
  function renderMark(key: string, segment: PageSourceSegment, kind: "lettering" | "depicted") {
    const linked = segment.lettering_item_ids.filter((id) => locatedIds.has(id));
    const copy = segment.lettering_item_ids.map((id) => lettering.get(id)?.text).filter(Boolean).join(" / ");
    const title = kind === "lettering" && copy ? t("Became lettering: {text}", { text: copy }) : t("Drawn on this page");
    const isActive = linked.length > 0 && linked.some((id) => active.includes(id));
    return <mark
      key={key}
      className={`${markClass[kind]} box-decoration-clone transition-shadow motion-reduce:transition-none ${linked.length > 0 ? "cursor-default focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red" : ""} ${isActive ? "shadow-[0_0_0_2px_var(--color-ink-black)]" : ""}`}
      title={title}
      data-kind={kind}
      tabIndex={linked.length > 0 ? 0 : undefined}
      onMouseEnter={linked.length > 0 ? () => setActive(linked) : undefined}
      onMouseLeave={linked.length > 0 ? () => setActive([]) : undefined}
      onFocus={linked.length > 0 ? () => setActive(linked) : undefined}
      onBlur={linked.length > 0 ? () => setActive([]) : undefined}
    >{segment.text}</mark>;
  }

  const hybrid = item.lettering_mode === "hybrid";
  const art = revision == null ? null : hybrid
    ? pageCompositePreviewUrl(project, pageNumber, revision, "reader", item.lettering_revision)
    : pageRenderPreviewUrl(project, pageNumber, revision, "reader");
  const caption = outlines.length > 0
    ? t("Point at highlighted lettering to outline where it sits on the page.")
    : hybrid || data.lettering.length === 0
      ? t("Lettering positions are not available for this artwork.")
      : t("Lettering positions appear after this page's text check.");

  // Lays out by its own width: beside the version preview it is a narrow column.
  return <div className="@container">
   <div className="grid gap-8 @4xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] @4xl:items-start">
    <div className="@4xl:sticky @4xl:top-0">
      {art ? <figure className="mx-auto max-w-56 @4xl:max-w-none">
        <div className="relative overflow-hidden border-[3px] border-ink-black bg-bristol">
          <img src={art} alt={`${t("Page")} ${pageNumber}`} className="block h-auto w-full" />
          <InspectButton images={{ src: art, alt: `${t("Page")} ${pageNumber}` }} />
          {outlines.map(({ id, outline }) => <div
            key={id}
            data-testid={`source-lettering-${id}`}
            aria-hidden="true"
            className={`pointer-events-none absolute border-[3px] border-hero-red shadow-[3px_3px_0_var(--color-ink-black)] transition-opacity duration-150 motion-reduce:transition-none ${active.includes(id) ? "opacity-100" : "opacity-0"}`}
            style={{
              left: `${outline.left * 100}%`, top: `${outline.top * 100}%`,
              width: `${outline.width * 100}%`, height: `${outline.height * 100}%`,
              transform: outline.rotation ? `rotate(${outline.rotation}deg)` : undefined,
            }}
          />)}
        </div>
        <figcaption className="mt-3 font-body text-xs leading-5 text-ink-muted">{caption}</figcaption>
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
          <p className="whitespace-pre-wrap font-body text-[0.95rem] leading-8">
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
   </div>
  </div>;
}
