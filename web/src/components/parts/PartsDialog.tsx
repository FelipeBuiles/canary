import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useI18n } from "../../i18n";
import { Sheet } from "../composites/Sheet";
import { ConfirmModal } from "../composites/ConfirmModal";
import { Button } from "../ui/Button";
import { FieldLabel, TextField } from "../ui/Field";
import { PartTextInput } from "./PartTextInput";
import {
  useAddPart,
  useDeletePart,
  usePartChapters,
  useRenamePart,
  useReplacePartText,
  useSplitPart,
} from "../../api/seriesQueries";
import { partProjectKey, splitProjectKey, withProjectKey } from "../../api/projectScope";
import { hasPartText, type DetectedChapter, type PartTextInput as PartText } from "../../api/parts";
import type { PartSummary, StageName } from "../../types/api";

const PART_STAGES: StageName[] = ["extract", "brief", "adapt", "plan", "draw", "finish"];

interface Props {
  open: boolean;
  project: string;
  parts: PartSummary[];
  onClose: () => void;
}

/** Each part is its own issue; the Story Bible, Style and Cast are shared. */
export function PartsDialog({ open, project, parts, onClose }: Props) {
  const { t } = useI18n();
  const [adding, setAdding] = useState(false);
  const [splitting, setSplitting] = useState<{ part: PartSummary; chapters?: DetectedChapter[] } | null>(null);
  return (
    <Sheet
      open={open}
      onClose={onClose}
      wide
      title={t("Parts")}
      description={t("Each part is its own issue with its own Brief, pages and export. Characters, places, props, Style and Cast are shared by every part.")}
      footer={!adding && !splitting && <Button onClick={() => setAdding(true)}>{t("Add a part")}</Button>}
    >
      {splitting ? (
        <SplitPanel project={project} part={splitting.part} proposed={splitting.chapters} onDone={() => setSplitting(null)} />
      ) : adding ? (
        <AddPartPanel project={project} onCancel={() => setAdding(false)} onAdded={(part, chapters) => {
          setAdding(false);
          if (chapters.length > 1) setSplitting({ part, chapters });
        }} parts={parts} />
      ) : (
        <ol className="divide-y-[2px] divide-ink-black/10">
          {parts.map((part) => (
            <PartRow key={part.id} project={project} part={part} last={parts.length === 1}
              onSplit={() => setSplitting({ part })} onOpen={onClose} />
          ))}
        </ol>
      )}
    </Sheet>
  );
}

function progressLabel(part: PartSummary, { t, stageName, statusName }: ReturnType<typeof useI18n>) {
  if (part.stages.finish === "complete") return t("Finished");
  const current = PART_STAGES.find((stage) => part.stages[stage] !== "complete") ?? "finish";
  const status = part.stages[current] ?? "pending";
  if (current === "extract" && status === "pending") return t("Not started");
  return t("{stage}: {status}", { stage: stageName(current), status: statusName(status) });
}

function PartRow({ project, part, last, onSplit, onOpen }: {
  project: string; part: PartSummary; last: boolean; onSplit: () => void; onOpen: () => void;
}) {
  const i18n = useI18n();
  const { t } = i18n;
  const navigate = useNavigate();
  const location = useLocation();
  const rename = useRenamePart();
  const replace = useReplacePartText();
  const remove = useDeletePart();
  const [title, setTitle] = useState(part.title);
  const [replacing, setReplacing] = useState(false);
  const [text, setText] = useState<PartText>({});
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { id, part: openPart } = splitProjectKey(project);
  const isOpen = openPart === part.id;

  function open() {
    navigate({ pathname: withProjectKey(location.pathname, partProjectKey(id, part.id)) });
    onOpen();
  }

  return (
    <li className="py-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="font-meta text-xs tracking-[0.1em] text-ink-muted">
            {t("PART {number}", { number: part.ordinal })}{isOpen ? ` · ${t("open now")}` : ""}
          </p>
          <form className="mt-1 flex flex-wrap items-end gap-2" onSubmit={(event) => {
            event.preventDefault();
            if (!title.trim() || title.trim() === part.title) return;
            setError(null);
            rename.mutate({ project, part: part.id, title: title.trim() }, { onError: (err) => setError(err.message) });
          }}>
            <label className="sr-only" htmlFor={`part-title-${part.id}`}>{t("Part title")}</label>
            <TextField id={`part-title-${part.id}`} value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)}
              className="max-w-[28rem] font-display text-lg" />
            {title.trim() !== part.title && <Button type="submit" size="sm" variant="outline" disabled={rename.isPending || !title.trim()}>{t("Rename")}</Button>}
          </form>
          <p className="mt-2 font-body text-sm text-ink-muted">
            {t("{characters} characters of text · {pages} pages · {progress}", {
              characters: part.characters.toLocaleString(), pages: part.page_count, progress: progressLabel(part, i18n),
            })}
          </p>
          {part.earlier_part_changed && (
            <p className="mt-2 font-body text-sm text-hero-red">{t("An earlier part was re-adapted after this one, so its continuity may have changed. Nothing re-runs on its own.")}</p>
          )}
          {!part.text_editable && part.text_locked_reason && (
            <p className="mt-2 font-body text-xs text-ink-muted">{part.text_locked_reason}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {!isOpen && <Button size="sm" onClick={open}>{t("Open")}</Button>}
          {part.text_editable && <Button size="sm" variant="outline" onClick={() => setReplacing(!replacing)} aria-expanded={replacing}>{t("Replace text")}</Button>}
          {part.text_editable && <Button size="sm" variant="outline" onClick={onSplit}>{t("Split")}</Button>}
          {part.text_editable && !last && <Button size="sm" variant="outline" onClick={() => setConfirmingDelete(true)}>{t("Delete")}</Button>}
        </div>
      </div>
      {replacing && (
        <form className="mt-4 space-y-4 bg-surface-container p-4" onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          replace.mutate({ project, part: part.id, input: text }, {
            onSuccess: () => { setReplacing(false); setText({}); },
            onError: (err) => setError(err.message),
          });
        }}>
          <p className="font-body text-sm text-ink-muted">{t("Replacing the text clears this part's extraction, so Extract runs again when you start it.")}</p>
          <PartTextInput value={text} onChange={setText} disabled={replace.isPending} />
          <Button type="submit" size="sm" disabled={replace.isPending || !hasPartText(text)}>{t("Replace text")}</Button>
        </form>
      )}
      {error && <p role="alert" className="mt-3 font-body text-sm text-hero-red">{error}</p>}
      <ConfirmModal
        open={confirmingDelete}
        destructive
        title={t("Delete {title}?", { title: part.title })}
        body={t("This removes the part's text and anything extracted from it. Later parts move up.")}
        confirmLabel={t("Delete")}
        busy={remove.isPending}
        error={remove.error?.message}
        onClose={() => setConfirmingDelete(false)}
        onConfirm={() => remove.mutate({ project, part: part.id }, {
          onSuccess: () => {
            setConfirmingDelete(false);
            if (isOpen) navigate({ pathname: withProjectKey(location.pathname, id) });
          },
        })}
      />
    </li>
  );
}

function AddPartPanel({ project, parts, onAdded, onCancel }: {
  project: string; parts: PartSummary[];
  onAdded: (part: PartSummary, chapters: DetectedChapter[]) => void; onCancel: () => void;
}) {
  const { t } = useI18n();
  const add = useAddPart();
  const [text, setText] = useState<PartText>({});
  return (
    <form className="space-y-5" onSubmit={(event) => {
      event.preventDefault();
      add.mutate({ project, input: text }, {
        onSuccess: (response) => {
          const summary = response.parts.find((item) => item.id === response.part.id);
          if (summary) onAdded(summary, response.chapters);
        },
      });
    }}>
      <p className="font-body text-sm text-ink-muted">
        {t("Part {number} continues the story. Adding it is free; extraction runs when you start the part, and only reads its new text.", { number: parts.length + 1 })}
      </p>
      <PartTextInput value={text} onChange={setText} withTitle disabled={add.isPending} />
      {add.error && <p role="alert" className="font-body text-sm text-hero-red">{add.error.message}</p>}
      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="outline" onClick={onCancel} disabled={add.isPending}>{t("Cancel")}</Button>
        <Button type="submit" disabled={add.isPending || !hasPartText(text)}>{add.isPending ? t("Adding…") : t("Add part")}</Button>
      </div>
    </form>
  );
}

function SplitPanel({ project, part, proposed, onDone }: {
  project: string; part: PartSummary; proposed?: DetectedChapter[]; onDone: () => void;
}) {
  const { t } = useI18n();
  const split = useSplitPart();
  const { data, isLoading, error } = usePartChapters(project, part.id, !proposed);
  const chapters = proposed ?? data?.chapters ?? [];
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [titles, setTitles] = useState<Record<number, string>>({});
  // Every chapter after the first can start a new part.
  const candidates = chapters.filter((chapter) => chapter.start_offset > 0);
  const boundaries = candidates.filter((chapter) => selected.has(chapter.index));

  return (
    <form className="space-y-5" onSubmit={(event) => {
      event.preventDefault();
      if (!boundaries.length) return;
      split.mutate({
        project, part: part.id,
        boundaries: boundaries.map((chapter) => chapter.start_offset),
        titles: [part.title, ...boundaries.map((chapter) => titles[chapter.index]?.trim() || chapter.title)],
      }, { onSuccess: onDone });
    }}>
      <p className="font-body text-sm text-ink-muted">
        {t("Choose the chapters where a new part begins. {title} keeps the text before the first one.", { title: part.title })}
      </p>
      {isLoading && <p className="font-body text-sm">{t("Finding chapters…")}</p>}
      {error && <p role="alert" className="font-body text-sm text-hero-red">{error.message}</p>}
      {!isLoading && !candidates.length && <p className="font-body text-sm">{t("No chapter headings were found in this part's text.")}</p>}
      <ul className="space-y-3">
        {candidates.map((chapter) => (
          <li key={chapter.index} className="flex flex-wrap items-center gap-3">
            <label className="flex min-h-11 items-center gap-3 font-body text-sm">
              <input type="checkbox" className="h-5 w-5" checked={selected.has(chapter.index)} onChange={(event) => {
                const next = new Set(selected);
                if (event.target.checked) next.add(chapter.index); else next.delete(chapter.index);
                setSelected(next);
              }} />
              <span>{t("New part at “{title}”", { title: chapter.title })}</span>
            </label>
            {selected.has(chapter.index) && (
              <span className="flex items-center gap-2">
                <FieldLabel htmlFor={`split-title-${chapter.index}`} className="sr-only">{t("Part title")}</FieldLabel>
                <TextField id={`split-title-${chapter.index}`} placeholder={chapter.title} value={titles[chapter.index] ?? ""}
                  maxLength={200} onChange={(event) => setTitles({ ...titles, [chapter.index]: event.target.value })} />
              </span>
            )}
          </li>
        ))}
      </ul>
      {split.error && <p role="alert" className="font-body text-sm text-hero-red">{split.error.message}</p>}
      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="outline" onClick={onDone} disabled={split.isPending}>{proposed ? t("Keep as one part") : t("Cancel")}</Button>
        <Button type="submit" disabled={split.isPending || !boundaries.length}>
          {t("Split into {count} parts", { count: boundaries.length + 1 })}
        </Button>
      </div>
    </form>
  );
}
