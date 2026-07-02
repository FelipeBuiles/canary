/**
 * Proscenium "S" — the Scenewright mark.
 *
 * A single ribbon-stroke curling into an S, set above a stage floor line:
 * a "maker of scenes" (scenewright). Drawn as one continuous stroke so it
 * reduces cleanly to a 16px favicon. The stroke uses `currentColor` so the
 * caller controls ink vs. paper (paper on the dark login stage, ink on light
 * surfaces). The floor line is fixed to the brand's ink-black.
 */
export function BrandMark({
  className,
  title,
}: {
  className?: string;
  title?: string;
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 48 48"
      fill="none"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <path
        d="M13 13.5c4-3 9-3.6 12.6-1.1 3.4 2.4 3.1 6.7-.7 9-2.6 1.6-6 2.2-9 3.2-3.1 1-5.7 2.9-5.8 5.8-.1 3.3 3.3 5.6 7 5.9 4.1.4 8.4-1 11.7-3.8"
        stroke="currentColor"
        strokeWidth="4.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M14 36.5h20"
        stroke="var(--color-ink-black)"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
    </svg>
  );
}
