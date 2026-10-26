import { ErrorNotice } from "../composites/ErrorNotice";
import { useState } from "react";
import { useI18n } from "../../i18n";
import { SectionHeader } from "../composites/SectionHeader";
import { Button } from "../ui/Button";
import { FieldLabel, SelectField } from "../ui/Field";
import { useExportParts } from "../../api/seriesQueries";
import { combinedExportUrl } from "../../api/parts";
import type { PartSummary } from "../../types/api";

/** One file from consecutive finished parts, without redrawing anything. */
export function CombinedExport({ project, parts, bare = false }: { project: string; parts: PartSummary[]; /** Without its own heading, inside another panel. */ bare?: boolean }) {
  const { t } = useI18n();
  const combine = useExportParts();
  const [from, setFrom] = useState(parts[0]?.id ?? "");
  const [to, setTo] = useState(parts[parts.length - 1]?.id ?? "");
  const [format, setFormat] = useState<"pdf" | "cbz">("pdf");
  if (parts.length < 2) return null;
  const start = parts.findIndex((part) => part.id === from);
  const end = parts.findIndex((part) => part.id === to);
  const range = start >= 0 && end >= start ? parts.slice(start, end + 1) : [];
  const unfinished = range.filter((part) => part.stages.finish !== "complete");
  return (
    <section aria-label={t("COMBINE PARTS")} className="space-y-4">
      {bare
        ? <p className="font-body text-xs leading-5 text-ink-muted">{t("Put consecutive finished parts into one file. Each part starts on a right-hand page; nothing is redrawn.")}</p>
        : <SectionHeader
            variant="underline"
            title={t("COMBINE PARTS")}
            description={t("Put consecutive finished parts into one file. Each part starts on a right-hand page; nothing is redrawn.")}
          />}
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <FieldLabel htmlFor="combine-from">{t("From")}</FieldLabel>
          <SelectField id="combine-from" value={from} onChange={(event) => setFrom(event.target.value)}>
            {parts.map((part) => <option key={part.id} value={part.id}>{`${part.ordinal}. ${part.title}`}</option>)}
          </SelectField>
        </div>
        <div>
          <FieldLabel htmlFor="combine-to">{t("To")}</FieldLabel>
          <SelectField id="combine-to" value={to} onChange={(event) => setTo(event.target.value)}>
            {parts.map((part) => <option key={part.id} value={part.id}>{`${part.ordinal}. ${part.title}`}</option>)}
          </SelectField>
        </div>
        <div>
          <FieldLabel htmlFor="combine-format">{t("Format")}</FieldLabel>
          <SelectField id="combine-format" value={format} onChange={(event) => setFormat(event.target.value as "pdf" | "cbz")}>
            <option value="pdf">PDF</option>
            <option value="cbz">CBZ</option>
          </SelectField>
        </div>
        <Button disabled={!range.length || unfinished.length > 0 || combine.isPending}
          onClick={() => combine.mutate({ project, partIds: range.map((part) => part.id), format })}>
          {combine.isPending ? t("Combining…") : t("Combine {count} parts", { count: range.length })}
        </Button>
      </div>
      {!range.length && <p className="font-body text-sm text-ink-muted">{t("Choose a first part that comes before the last one.")}</p>}
      {unfinished.length > 0 && (
        <p className="font-body text-sm text-ink-muted">{t("Finish {titles} first.", { titles: unfinished.map((part) => part.title).join(", ") })}</p>
      )}
      {combine.error && <ErrorNotice error={combine.error} operation="export" />}
      {combine.data && (
        <a href={combinedExportUrl(project, combine.data.file)} download
          className="inline-flex min-h-11 items-center font-meta text-sm font-bold underline underline-offset-4">
          {t("Download {file}", { file: combine.data.file })}
        </a>
      )}
    </section>
  );
}
