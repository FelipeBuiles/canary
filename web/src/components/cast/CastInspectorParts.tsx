import { useState, type ReactNode } from "react";
import { useCastAssetVersions, useRestoreCastAssetVersion } from "../../api/queries";
import { seriesPath } from "../../api/projectScope";
import { useImageViewer } from "../../hooks/useImageViewer";
import { useI18n } from "../../i18n";
import { readableAnchor } from "../../lib/visualAnchor";
import { ErrorNotice } from "../composites/ErrorNotice";

export const OVERLINE = "font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted";

/** One inspector block, divided from the one above it. */
export function InspectorSection({ label, children, labelledBy }: { label?: ReactNode; children: ReactNode; labelledBy?: string }) {
  return (
    <section aria-labelledby={labelledBy} className="mt-5 border-t border-ink-black/10 pt-4">
      {label && <h3 id={labelledBy} className={OVERLINE}>{label}</h3>}
      {children}
    </section>
  );
}

/** A reference's look in reader terms. Internal subject-count tags stay hidden. */
export function AnchorSection({ anchor }: { anchor: string }) {
  const { t } = useI18n();
  return (
    <section aria-label={t("VISUAL ANCHOR")}>
      <p className="mt-3 break-words font-body text-[0.9375rem] leading-6 text-ink-black">{readableAnchor(anchor)}</p>
    </section>
  );
}

const REF_VIEWS = [
  { pose: "portrait", label: "Portrait" },
  { pose: "full_body", label: "Full body" },
] as const;

/**
 * Read-only derived views sent to the image model. Panel framing chooses the
 * portrait for close shots and the full-body crop for other shots.
 */
export function ReferenceViews({ projectName, charId, timestamp }: { projectName: string; charId: string; timestamp: string | number }) {
  const { t } = useI18n();
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const inspector = useImageViewer();
  const visiblePoses = REF_VIEWS.filter(({ pose }) => !failed[pose]);
  if (visiblePoses.length === 0) return null;
  const poseImages = visiblePoses.map(({ pose, label }) => ({
    src: `/api${seriesPath(projectName)}/files/refs/${encodeURIComponent(charId)}/${pose}.png?t=${encodeURIComponent(timestamp)}`,
    alt: `${t(label)} ${t("reference")}`,
  }));

  return (
    <InspectorSection label={t("Views pages use")}>
      <div className="mt-2 flex gap-2">
        {visiblePoses.map(({ pose, label }, position) => (
          <button
            type="button"
            key={pose}
            title={t("Zoom and inspect")}
            aria-label={`${t("Zoom and inspect")} · ${poseImages[position].alt}`}
            onClick={() => inspector.open(poseImages, position)}
            className="group w-20 cursor-zoom-in text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red"
          >
            <span className="block overflow-hidden bg-surface-container outline outline-1 -outline-offset-1 outline-ink-black/12 transition-[outline-color] group-hover:outline-ink-black/50">
              <img
                src={poseImages[position].src}
                alt={poseImages[position].alt}
                className="aspect-square w-full object-cover"
                onError={() => setFailed((current) => ({ ...current, [pose]: true }))}
              />
            </span>
            <span className="mt-1 block font-meta text-[0.6875rem] text-ink-muted">{t(label)}</span>
          </button>
        ))}
      </div>
      <p className="mt-2 font-body text-xs text-ink-muted">{t("Selected automatically to suit each shot.")}</p>
      {inspector.viewer}
    </InspectorSection>
  );
}

/**
 * Re-roll history for a character or place (main image or a look). Renders
 * nothing until at least one prior version has been archived, so it stays out
 * of the way until a redraw. Clicking another thumbnail restores it.
 */
export function RefVersionHistory({
  projectName,
  assetType,
  assetId,
  stateId,
  refreshKey,
  onRestored,
  busy = false,
}: {
  projectName: string;
  assetType: "character" | "location";
  assetId: string;
  stateId?: string;
  refreshKey?: unknown;
  onRestored?: () => void;
  busy?: boolean;
}) {
  const { t } = useI18n();
  const { data, error, isPending } = useCastAssetVersions(projectName, assetType, assetId, stateId, refreshKey);
  const restore = useRestoreCastAssetVersion();
  const versions = data?.versions ?? [];
  if (isPending) return null;
  if (error) return <p role="alert" className="mt-5 font-body text-sm text-hero-red">{t("Version history could not be loaded.")}</p>;
  if (!versions.some((version) => !version.current)) return null;
  const fileUrl = (relPath: string) => `/api${seriesPath(projectName)}/files/${relPath}`;

  return (
    <section aria-label={t("Versions")} className="mt-5 border-t border-ink-black/10 pt-4">
      <h3 className={OVERLINE}>{t("Versions")} <span className="tabular-nums">· {versions.length}</span></h3>
      <div className="mt-2 flex flex-wrap items-start gap-2">
        {versions.map((version) => (
          <button
            key={`${version.version}-${version.image_path}`}
            type="button"
            title={`${version.current ? t("Selected version") : t("Restore")} v${version.version}`}
            aria-label={`${version.current ? t("Selected version") : t("Restore")} v${version.version}`}
            aria-pressed={!!version.current}
            disabled={!!version.current || busy || restore.isPending}
            onClick={() => restore.mutate(
              { project: projectName, assetType, assetId, version: version.version, stateId },
              { onSuccess: () => onRestored?.() },
            )}
            className={`group w-[4.5rem] text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red ${busy || restore.isPending ? "opacity-50" : ""}`}
          >
            <span className={`block overflow-hidden bg-surface-container ${version.current ? "outline-2 outline-ink-black shadow-[2px_2px_0_0_var(--color-ink-black)]" : "outline outline-1 -outline-offset-1 outline-ink-black/15 group-hover:outline-ink-black/60"}`}>
              <img src={`${fileUrl(version.image_path)}${version.current ? `?t=${encodeURIComponent(String(refreshKey ?? "current"))}` : ""}`} alt="" className="aspect-square w-full object-cover" />
            </span>
            <span className={`mt-1 block font-meta text-[0.6875rem] ${version.current ? "font-semibold text-ink-black" : "text-ink-muted"}`}>
              v{version.version}{version.current && <> · {t("In use")}</>}
            </span>
          </button>
        ))}
      </div>
      {restore.error && <ErrorNotice error={restore.error} operation="save" />}
    </section>
  );
}
