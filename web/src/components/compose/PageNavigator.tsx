import { useEffect, useState } from "react";
import type { PageSummary } from "../../types/api";
import { pagePreviewUrl } from "../../api/pages";

interface PageNavigatorProps {
  project: string;
  pages: PageSummary[];
  currentPage: number;
  onSelect: (pageNum: number) => void;
  /**
   * While true, thumbnails whose PNG has not loaded yet keep re-fetching on an
   * interval (cache-busting query param). The compose stage writes page PNGs
   * in a render phase that runs *after* the page JSON, so on first reach the
   * PNGs can still be missing — without this, a one-shot onError hides the
   * thumbnail forever (the page-number placeholder stays, the image never
   * recovers until a remount). Drive this from the compose stage status
   * (running → retry, otherwise stop).
   */
  shouldRetryThumbs?: boolean;
}

/**
 * Thumbnails use the rendered page PNGs (written by the compose stage /
 * export), not live preview iframes — a full 2480x3508 document with
 * full-resolution panel images per thumbnail is far too heavy for a rail.
 * They can lag behind unexported edits; the canvas is the live view.
 */
function pageThumbUrl(project: string, pageNumber: number, tick: number): string {
  const name = `page_${String(pageNumber).padStart(3, "0")}.png`;
  // `t` cache-busts so the browser actually re-requests after a 404 while the
  // compose renderer is still catching up. t=0 is omitted to keep the common
  // (PNG already present) path identical to the old behavior.
  return tick > 0
    ? `/api/projects/${encodeURIComponent(project)}/files/compose/pages/${name}?t=${tick}`
    : `/api/projects/${encodeURIComponent(project)}/files/compose/pages/${name}`;
}

const THUMB_RETRY_MS = 3000;
const PAGE_W = 2480;
const PAGE_H = 3508;
const THUMB_SCALE = 124 / PAGE_W;

function Thumb({
  project,
  pageNumber,
  shouldRetry,
}: {
  project: string;
  pageNumber: number;
  shouldRetry: boolean;
}) {
  // `failed` means the last fetch 404'd; `tick` cache-busts the next attempt.
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    // Only poll while the PNG is missing AND we're allowed to retry (compose
    // still running). Once the stage is complete, stop hammering the server.
    if (!failed || !shouldRetry) return;
    const id = window.setInterval(() => setTick((t) => t + 1), THUMB_RETRY_MS);
    return () => window.clearInterval(id);
  }, [failed, shouldRetry]);

  return (
    <>
      <img
        src={pageThumbUrl(project, pageNumber, tick)}
        alt={`Page ${pageNumber} thumbnail`}
        className={`${failed ? "hidden" : "relative"} h-full w-full object-contain`}
        loading="lazy"
        onLoad={() => setFailed(false)}
        onError={() => setFailed(true)}
      />
      {failed && (
        <iframe
          src={pagePreviewUrl(project, pageNumber)}
          title={`Page ${pageNumber} live preview`}
          className="absolute left-0 top-0 border-0 bg-white"
          style={{
            width: PAGE_W,
            height: PAGE_H,
            transform: `scale(${THUMB_SCALE})`,
            transformOrigin: "top left",
          }}
          tabIndex={-1}
          loading="lazy"
        />
      )}
    </>
  );
}

export function PageNavigator({
  project,
  pages,
  currentPage,
  onSelect,
  shouldRetryThumbs = false,
}: PageNavigatorProps) {
  return (
    <div className="min-h-0 border-[3px] border-ink-black bg-pulp-paper shadow-[3px_3px_0_0_var(--color-ink-black)] md:flex md:max-h-full md:flex-col">
      <div className="border-b border-ink-black/20 px-2.5 py-2">
        <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
          PAGES
        </div>
      </div>
      <div className="flex gap-2 overflow-x-auto p-2 md:min-h-0 md:flex-1 md:flex-col md:overflow-x-hidden md:overflow-y-auto">
        {pages.map((p) => {
          const isActive = p.page_number === currentPage;

          return (
            <button
              key={p.page_number}
              onClick={() => onSelect(p.page_number)}
              aria-current={isActive ? "page" : undefined}
              className={`group block w-[124px] shrink-0 border-[2px] text-left transition-[background-color,border-color,box-shadow,transform] duration-150 md:w-full ${
                isActive
                  ? "border-hero-red bg-bristol shadow-[2px_2px_0_0_var(--color-outline-ghost)]"
                  : "border-ink-black/25 bg-bristol hover:border-ink-black/55 hover:shadow-[2px_2px_0_0_var(--color-ghost-shadow)]"
              }`}
            >
              <div className="relative aspect-[2480/3508] w-full overflow-hidden bg-[#f3eedf] p-1">
                <span className="absolute inset-0 flex items-center justify-center font-display text-[1.4rem] font-black text-ink-black/15">
                  {p.page_number}
                </span>
                <Thumb
                  project={project}
                  pageNumber={p.page_number}
                  shouldRetry={shouldRetryThumbs}
                />
              </div>
              <div className="flex items-center justify-between border-t border-ink-black/15 px-1.5 py-1.5">
                <span className="font-meta text-[0.54rem] tracking-[0.14em] text-ink-black/62">
                  PAGE {String(p.page_number).padStart(2, "0")}
                </span>
                <span className="font-meta text-[0.5rem] tracking-[0.1em] text-ink-black/38">
                  {p.panel_count}p
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
