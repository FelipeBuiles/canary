import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useColdOpen, useSetColdOpenFavorite } from "../../api/queries";
import type { ColdOpen as ColdOpenData, ColdOpenLook } from "../../api/styles";
import { ImageGenerationPreview } from "../composites/ImageGenerationPreview";
import { useImageViewer } from "../../hooks/useImageViewer";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";

/** Sheets come off the press slightly askew, like pulled proofs on a bench. */
const SHEET_TILT = ["-rotate-[0.6deg]", "rotate-[0.4deg]", "-rotate-[0.25deg]"];

type Variant = "press" | "rail" | "look";

/**
 * The Cold Open: one page of the author's opening in three looks, drawn while
 * Extract reads the rest of the book. Canary pays for it, so it shows no
 * credits, and a favorite is a preference Look highlights, never a selection.
 * Look adopts the printed pages as its first proofs when it opens empty.
 *
 * Each placement matches what the author is doing: the `press` fills the wait
 * while Extract and Brief run; beside the Brief, a quiet `rail` card keeps the
 * Brief the task; in Look's empty room, `look` shows pages Look could not take
 * as proofs (still printing, or a different scene) as a first impression.
 */
export function ColdOpen({ project, variant, watching = false, lookReady = false, className }: {
  project: string;
  variant: Variant;
  /** Extract is reading: poll until the first pages are admitted. */
  watching?: boolean;
  /** Look is open to this project, so the pages can lead there. */
  lookReady?: boolean;
  className?: string;
}) {
  const { data } = useColdOpen(project, watching);
  const coldOpen = data?.cold_open;
  if (!coldOpen) return null;
  const printing = coldOpen.status === "printing";
  if (!printing && !coldOpen.looks.some((look) => look.status === "ready")) {
    // A press that printed nothing explains itself once; elsewhere it is absent.
    return variant === "press" && coldOpen.looks.length
      ? <ColdOpenPress project={project} coldOpen={coldOpen} className={className} /> : null;
  }
  if (variant === "rail") return <ColdOpenRail project={project} coldOpen={coldOpen} lookReady={lookReady} className={className} />;
  if (variant === "look") return <ColdOpenLook project={project} coldOpen={coldOpen} className={className} />;
  return <ColdOpenPress project={project} coldOpen={coldOpen} className={className} />;
}

function sceneLine(coldOpen: ColdOpenData, t: ReturnType<typeof useI18n>["t"]) {
  return coldOpen.chapter
    ? t("Chapter {number} · {scene}", { number: coldOpen.chapter, scene: coldOpen.scene_title })
    : coldOpen.scene_title;
}

function viewerImages(coldOpen: ColdOpenData) {
  return coldOpen.looks.filter((look) => look.status === "ready" && look.image_url)
    .map((look) => ({ src: look.image_url!, alt: look.label, label: look.label }));
}

function ColdOpenPress({ project, coldOpen, className }: { project: string; coldOpen: ColdOpenData; className?: string }) {
  const { t } = useI18n();
  const printing = coldOpen.status === "printing";
  const printed = coldOpen.looks.some((look) => look.status === "ready");
  const heading = printing ? t("Your first page is on the press") : printed
    ? t("Your story, three ways") : t("The press jammed on your first pages");
  const status = printing
    ? coldOpen.phase === "printing" ? t("Pulling three proofs of one page from your opening…")
      : t("We've read your opening. Choosing the scene and setting the type…")
    : coldOpen.status === "interrupted" ? t("The press stopped before every page was printed.")
      : printed ? t("Pick the one that feels like your book. It will be waiting for you in Look; nothing is chosen for you.")
        : t("Nothing was charged. Your story is still being read, and Look will draw it in its own styles.");

  return (
    <section aria-labelledby="cold-open-heading" className={cn("benday-ink px-4 py-7 text-pulp-paper sm:px-8 sm:py-9", className)}>
      <div className="mx-auto w-full max-w-[72rem]">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <p className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-narrator-gold">{t("First pages")}</p>
            <h2 id="cold-open-heading" className="mt-2 font-display text-[2rem] font-black uppercase leading-[0.92] tracking-[-0.035em] sm:text-[2.75rem]">{heading}</h2>
            {coldOpen.scene_title && <p className="mt-3 font-meta text-[0.8125rem] font-semibold text-pulp-paper">{sceneLine(coldOpen, t)}</p>}
            {coldOpen.scene_summary && <p className="mt-1 line-clamp-2 max-w-[44rem] font-body text-[0.9375rem] leading-6 text-pulp-paper/72">{coldOpen.scene_summary}</p>}
          </div>
          <span className="stamp shrink-0 bg-transparent! text-narrator-gold [--stamp-rotate:-4deg]">{t("On the house")}</span>
        </div>
        <SheetRow project={project} coldOpen={coldOpen} className="mt-7" />
        <p role="status" aria-live="polite" className="mt-6 max-w-[44rem] font-body text-[0.9375rem] leading-6 text-pulp-paper/80">{status}</p>
      </div>
    </section>
  );
}

/** In Look's empty room: pages that are not proofs, shown as a first impression. */
function ColdOpenLook({ project, coldOpen, className }: { project: string; coldOpen: ColdOpenData; className?: string }) {
  const { t } = useI18n();
  return (
    <section aria-labelledby="cold-open-look" className={className}>
      <p id="cold-open-look" className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-narrator-gold">{t("Your first pages")}</p>
      <p className="mt-2 max-w-[40rem] font-body text-[0.9375rem] leading-6 text-pulp-paper/80">
        {t("A first impression of your story. To choose your book's look, create proofs below.")}
      </p>
      <SheetRow project={project} coldOpen={coldOpen} printedOnly className="mt-5 max-w-[52rem]" />
    </section>
  );
}

/** Beside the Brief: a quiet card, so the Brief stays the task. */
function ColdOpenRail({ project, coldOpen, lookReady, className }: {
  project: string; coldOpen: ColdOpenData; lookReady: boolean; className?: string;
}) {
  const { t } = useI18n();
  const { open, viewer } = useImageViewer();
  const images = viewerImages(coldOpen);
  const pick = coldOpen.looks.find((look) => look.id === coldOpen.favorite_look_id && look.status === "ready");
  const done = coldOpen.looks.filter((look) => look.status === "ready").length;
  const status = coldOpen.status === "printing"
    ? t("On the press: {done} of {count} printed", { done, count: coldOpen.looks.length || 3 })
    : pick ? t("Your pick: {look}", { look: pick.label }) : t("They'll be waiting for you in Look.");
  return (
    <section aria-labelledby="cold-open-rail" className={cn("border border-ink-black/14 bg-bristol px-4 pb-4 pt-3.5", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 id="cold-open-rail" className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("First pages")}</h3>
        <span className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-ink-muted">{t("On the house")}</span>
      </div>
      <ol className="mt-2.5 grid grid-cols-3 gap-2">
        {/* A page the press dropped has nothing to show in a glance. */}
        {coldOpen.looks.filter((look) => look.status !== "failed").map((look) => {
          const index = images.findIndex((image) => image.label === look.label);
          return (
            <li key={look.id} className={cn("relative border bg-surface-container", look.id === pick?.id ? "border-hero-red" : "border-ink-black/18")}>
              <ImageGenerationPreview project={project} target={look.preview_target} aspect="4 / 5" surface="paper"
                active={look.status === "queued" || look.status === "printing"} finalSrc={look.image_url ?? undefined}>
                {look.image_url ? (
                  <button type="button" onClick={() => open(images, Math.max(0, index))} aria-label={t("Look closer at {look}", { look: look.label })}
                    className="block h-full w-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
                    <img src={look.image_url} alt="" className="h-full w-full object-cover" />
                  </button>
                ) : null}
              </ImageGenerationPreview>
            </li>
          );
        })}
      </ol>
      <p className="mt-2.5 font-meta text-[0.8125rem] font-semibold leading-5 text-ink-black">{sceneLine(coldOpen, t)}</p>
      <p role="status" className="mt-0.5 font-body text-[0.8125rem] leading-5 text-ink-soft">{status}</p>
      {lookReady && done > 0 && (
        <Link to={`/project/${project}/styles`} className="mt-2 inline-flex min-h-9 items-center gap-1.5 font-meta text-[0.8125rem] font-semibold text-hero-red hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
          {t("Make the whole book look like this")}<ArrowRight size={14} aria-hidden="true" />
        </Link>
      )}
      {viewer}
    </section>
  );
}

/** Pulled sheets on the ink bed: each opens close up and can be the author's pick.
 *  `printedOnly` leaves out pages the press dropped, which only the press explains. */
function SheetRow({ project, coldOpen, printedOnly = false, className }: {
  project: string; coldOpen: ColdOpenData; printedOnly?: boolean; className?: string;
}) {
  const { t } = useI18n();
  const { open, viewer } = useImageViewer();
  const favorite = useSetColdOpenFavorite();
  const images = viewerImages(coldOpen);
  return (
    <>
      <ol aria-label={t("First pages")} className={cn("grid snap-x auto-cols-[80%] grid-flow-col gap-4 overflow-x-auto pb-2 sm:auto-cols-auto sm:grid-flow-row sm:grid-cols-3 sm:gap-6 sm:overflow-visible", className)}>
        {(coldOpen.looks.length ? coldOpen.looks : PENDING_SHEETS)
          .filter((look) => !printedOnly || look.status !== "failed").map((look, index) => (
          <li key={look.id} className="snap-start">
            <Sheet project={project} look={look} tilt={SHEET_TILT[index % SHEET_TILT.length]}
              favorite={coldOpen.favorite_look_id === look.id} pending={favorite.isPending}
              onOpen={() => open(images, Math.max(0, images.findIndex((image) => image.label === look.label)))}
              onFavorite={() => favorite.mutate({ project, lookId: coldOpen.favorite_look_id === look.id ? null : look.id })} />
          </li>
        ))}
      </ol>
      {viewer}
    </>
  );
}

/** Placeholder sheets while the scene is chosen and before the looks are named. */
const PENDING_SHEETS: ColdOpenLook[] = [0, 1, 2].map((index) => ({
  id: `pending-${index}`, label: "", medium: "", status: "queued", error: null, adopted: false,
  image_url: null, preview_target: `cold_open/pending_${index}.png`,
}));

function Sheet({ project, look, tilt, favorite, pending, onOpen, onFavorite }: {
  project: string; look: ColdOpenLook; tilt: string; favorite: boolean; pending: boolean;
  onOpen: () => void; onFavorite: () => void;
}) {
  const { t } = useI18n();
  const active = look.status === "queued" || look.status === "printing";
  return (
    <figure className={cn("relative bg-bristol p-2.5 text-ink-black shadow-[0_22px_36px_-22px_rgba(0,0,0,0.75)] transition-transform motion-reduce:rotate-0", tilt)}>
      <ImageGenerationPreview project={project} target={look.preview_target} active={active}
        finalSrc={look.image_url ?? undefined} aspect="4 / 5" surface="paper"
        label={look.status === "printing" ? t("On the press…") : t("Waiting for the press")}>
        {look.image_url ? (
          <button type="button" onClick={onOpen} aria-label={t("Look closer at {look}", { look: look.label })}
            className="block h-full w-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red">
            <img src={look.image_url} alt={look.label} className="animate-proof-reveal h-full w-full object-cover" />
          </button>
        ) : look.status === "failed" ? (
          <div className="flex h-full w-full items-center justify-center bg-surface-container p-6 text-center font-meta text-sm text-ink-soft">
            {t("This one didn't make it off the press.")}
          </div>
        ) : null}
      </ImageGenerationPreview>
      {favorite && (
        <span className="stamp stamp-red animate-stamp-slam pointer-events-none absolute right-4 top-5 [--stamp-rotate:-8deg]">{t("Your pick")}</span>
      )}
      <figcaption className="flex min-h-14 items-start justify-between gap-3 px-1 pt-3">
        <span className="min-w-0" title={look.label}>
          <span className="line-clamp-2 font-display text-[1.0625rem] font-black uppercase leading-tight tracking-[-0.01em]">{look.label || " "}</span>
          <span className="block truncate font-body text-[0.8125rem] text-ink-muted">{look.medium}</span>
        </span>
        {look.status === "ready" && (
          <button type="button" aria-pressed={favorite} disabled={pending} onClick={onFavorite}
            className={cn("min-h-9 shrink-0 border px-3 font-meta text-[0.75rem] font-bold uppercase tracking-[0.06em] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red",
              favorite ? "border-hero-red bg-hero-red text-pulp-paper" : "border-ink-black/30 text-ink-black hover:bg-ink-black hover:text-pulp-paper")}>
            {favorite ? t("Your pick") : t("This one")}
          </button>
        )}
      </figcaption>
    </figure>
  );
}
