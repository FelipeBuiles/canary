import type { UseQueryResult } from "@tanstack/react-query";
import { previewRejected } from "../../lib/sourcePreview";
import type { SourcePreview } from "../../types/api";
import { useI18n } from "../../i18n";

/** Below this, an adaptation has little to stage; advisory only. */
const SHORT_SOURCE_WORDS = 300;
const LISTED_PARTS = 6;

export function SourcePreviewPanel({ preview }: { preview: UseQueryResult<SourcePreview> }) {
  const { t } = useI18n();
  if (preview.isPending) {
    return <p role="status" className="mt-3 text-sm text-ink-muted">{t("Reading your manuscript…")}</p>;
  }
  if (preview.isError) {
    const detail = preview.error instanceof Error ? preview.error.message.replace(/^API \d+:\s*/, "") : "";
    return previewRejected(preview.error)
      ? <p role="alert" className="mt-3 text-sm text-hero-red">{detail}</p>
      : <p className="mt-3 text-sm text-ink-muted">{t("Couldn’t preview this manuscript. You can still create the project.")}</p>;
  }
  const { words, chapters, characters, parts, part_target_characters: target } = preview.data;
  const hidden = parts.length - LISTED_PARTS;
  return (
    <div className="mt-3 space-y-2 text-sm" aria-live="polite">
      <p className="font-bold">
        {t("{count, plural, one {# word} other {# words}}", { count: words })}
        {chapters > 1 && <> · {t("{count, plural, one {# chapter} other {# chapters}} found", { count: chapters })}</>}
      </p>
      {parts.length > 1 && (
        <div>
          <p>{t("Splits into {count} parts at chapter breaks. Part 1 is analyzed first; you start each later part when you’re ready.", { count: parts.length })}</p>
          <ol className="mt-2 space-y-1 border-l-2 border-ink-black/15 pl-3">
            {parts.slice(0, LISTED_PARTS).map((part, index) => (
              <li key={index} className="flex justify-between gap-3">
                <span className="min-w-0 truncate"><span className="font-meta text-xs text-ink-muted">{index + 1}</span> {part.title ?? t("Part {number}", { number: index + 1 })}</span>
                <span className="shrink-0 text-ink-muted">{t("{count, plural, one {# word} other {# words}}", { count: part.words })}</span>
              </li>
            ))}
            {hidden > 0 && <li className="text-ink-muted">{t("{count, plural, one {# more part} other {# more parts}}", { count: hidden })}</li>}
          </ol>
        </div>
      )}
      {words < SHORT_SOURCE_WORDS && (
        <p className="bg-chip-gold/45 p-3">{t("This is very short. A few hundred words may only make a page or two.")}</p>
      )}
      {parts.length === 1 && chapters <= 1 && characters > target && (
        <p className="bg-chip-gold/45 p-3">{t("No chapter headings were found, so this stays one long part. To split it, add headings such as “Chapter 1” on their own lines.")}</p>
      )}
    </div>
  );
}
