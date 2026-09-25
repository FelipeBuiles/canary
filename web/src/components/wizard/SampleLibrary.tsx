import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { readShortStory } from "../../api/projects";
import { useShortStories } from "../../api/queries";
import { useI18n } from "../../i18n";
import { browseStories, deriveGenres, genreLabel, SORT_OPTIONS, type SortKey } from "../../lib/storyBrowser";
import type { ShortStory } from "../../types/api";
import { Button } from "../ui/Button";
import { FieldLabel, TextField } from "../ui/Field";
import { Select } from "../ui/Select";

const PAGE_SIZE = 8;
const TONES: Record<string, string> = {
  "sci-fi": "bg-secondary-container",
  drama: "bg-chip-sage",
  horror: "bg-chip-red",
  fantasy: "bg-chip-gold",
};

interface SampleLibraryProps {
  initialReadCode?: string | null;
  selectedCode?: string | null;
  onSelect?: (story: ShortStory) => void;
  onReadAndSelect?: (story: ShortStory) => void;
  onReaderChange?: (code: string | null) => void;
}

export function SampleLibrary({ initialReadCode, selectedCode, onSelect, onReadAndSelect, onReaderChange }: SampleLibraryProps) {
  const { language, t } = useI18n();
  const { data: stories, isLoading, isError, refetch, isFetching } = useShortStories();
  const [search, setSearch] = useState("");
  const [genres, setGenres] = useState<string[]>([]);
  const [source, setSource] = useState<"all" | "curated" | "archive">("all");
  const [sort, setSort] = useState<SortKey>("relevance");
  const [page, setPage] = useState(0);
  const [readingCode, setReadingCode] = useState<string | null>(initialReadCode ?? null);
  const [readingText, setReadingText] = useState<string | null>(null);
  const [readingError, setReadingError] = useState(false);
  const readerTitleRef = useRef<HTMLHeadingElement>(null);
  const readerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const availableGenres = useMemo(() => deriveGenres(stories ?? []), [stories]);
  const filtered = useMemo(() => browseStories(stories ?? [], { search, genres, sort, source }), [stories, search, genres, sort, source]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const readingStory = stories?.find((story) => story.code === readingCode);
  const curatedCount = stories?.filter((story) => story.source_kind !== "archive").length ?? 0;
  const archiveCount = (stories?.length ?? 0) - curatedCount;

  useEffect(() => {
    if (!readingCode) return;
    const controller = new AbortController();
    readShortStory(readingCode, controller.signal)
      .then(({ text }) => setReadingText(text))
      .catch(() => { if (!controller.signal.aborted) setReadingError(true); });
    return () => controller.abort();
  }, [readingCode]);

  useEffect(() => {
    if (readingCode) {
      readerTitleRef.current?.focus({ preventScroll: true });
      readerTitleRef.current?.scrollIntoView?.({ block: "start" });
    }
  }, [readingCode]);

  function openReader(code: string, trigger: HTMLButtonElement) {
    readerTriggerRef.current = trigger;
    setReadingText(null);
    setReadingError(false);
    setReadingCode(code);
    onReaderChange?.(code);
  }

  function closeReader() {
    setReadingCode(null);
    onReaderChange?.(null);
    requestAnimationFrame(() => {
      readerTriggerRef.current?.focus({ preventScroll: true });
      readerTriggerRef.current?.scrollIntoView?.({ block: "nearest" });
    });
  }

  function toggleGenre(genre: string) {
    setGenres((current) => current.includes(genre) ? current.filter((item) => item !== genre) : [...current, genre]);
    setPage(0);
  }

  if (isLoading) return <p role="status" className="py-8 text-sm">{t("LOADING SAMPLE STORIES…")}</p>;
  if (isError) return (
    <div role="alert" className="space-y-3 bg-chip-red/40 p-5">
      <p className="text-sm font-semibold text-hero-red">{t("THE SAMPLE LIBRARY COULD NOT LOAD")}</p>
      <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>{t("TRY AGAIN")}</Button>
    </div>
  );
  if (!stories?.length) return <p role="status" className="py-8 text-sm">{t("The sample library is empty. You can still upload a manuscript or paste a story URL.")}</p>;

  if (readingStory) {
    const body = readingText?.replace(/^.*\nBy [^\n]+\n+/u, "").trim();
    return (
      <section aria-label={t("Story reader")} className="space-y-5">
        <Button variant="outline" size="sm" onClick={closeReader}>← {t("Back to stories")}</Button>
        <header className="bg-ink-black px-5 py-7 text-bristol sm:px-7">
          <p className="font-meta text-[0.7rem] font-bold uppercase tracking-[0.18em] text-narrator-gold">{t("READ THE ORIGINAL")}</p>
          <h2 ref={readerTitleRef} tabIndex={-1} className="mt-3 font-display text-3xl font-black leading-none tracking-tight sm:text-4xl">{readingStory.title}</h2>
          <p className="mt-4 text-sm text-bristol/80">{readingStory.author} · {Math.max(1, Math.ceil(readingStory.words / 220))} {t("min read")}</p>
        </header>
        {readingStory.content_note && <p className="bg-chip-red/45 p-3 text-sm"><strong>{t("Content note")}:</strong> {t(readingStory.content_note)}</p>}
        {readingStory.rights_note && <p className="bg-chip-gold/45 p-3 text-sm">{t(readingStory.rights_note)}</p>}
        {readingError ? <div role="alert" className="space-y-3"><p>{t("The story could not be opened. Try again.")}</p><Button variant="outline" onClick={() => { setReadingCode(null); setReadingText(null); setReadingError(false); requestAnimationFrame(() => setReadingCode(readingStory.code)); }}>{t("TRY AGAIN")}</Button></div>
          : !body ? <p role="status">{t("Opening story…")}</p>
            : <div className="mx-auto max-w-[68ch] space-y-5 px-1 py-2 font-serif text-[1.05rem] leading-[1.85] text-ink-black sm:px-5">{body.split(/\n\s*\n/u).map((paragraph, index) => <p key={index} className="whitespace-pre-line">{paragraph}</p>)}</div>}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t-2 border-ink-black/15 pt-5">
          <div className="text-sm text-ink-muted">
            {readingStory.source_note && <p className="mb-2">{t(readingStory.source_note)}</p>}
            {readingStory.source_url && <a className="underline underline-offset-4 hover:text-hero-red" href={readingStory.source_url} target="_blank" rel="noopener noreferrer">{t(readingStory.source_kind === "archive" ? "Original archive page" : "Author's source")} ↗</a>}
            {readingStory.attribution_url && <span> · <a className="underline underline-offset-4 hover:text-hero-red" href={readingStory.attribution_url} target="_blank" rel="noopener noreferrer">{t("Author credit")} ↗</a></span>}
            {readingStory.license_url && <span> · <a className="underline underline-offset-4 hover:text-hero-red" href={readingStory.license_url} target="_blank" rel="noopener noreferrer">{readingStory.license}</a></span>}
          </div>
          {onSelect ? <Button onClick={() => (onReadAndSelect ?? onSelect)(readingStory)}>{t("USE THIS STORY")} →</Button>
            : <Link className="inline-flex min-h-11 items-center border-2 border-ink-black bg-hero-red px-4 font-meta text-xs font-bold text-bristol shadow-ink-sm hover:bg-[#94141c]" to={`/signup?sample=${encodeURIComponent(readingStory.code)}`}>{t("START WITH THIS STORY")} →</Link>}
        </div>
      </section>
    );
  }

  return (
    <section aria-label={t("SHORT STORY LIBRARY")} className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="font-meta text-[0.68rem] font-bold uppercase tracking-[0.16em] text-hero-red">{t("THE STORY LIBRARY")}</p>
          <h2 className="mt-1 font-display text-xl font-black uppercase leading-none text-ink-black sm:text-2xl">{t("Choose the world you want to draw")}</h2>
        </div>
        <span className="font-meta text-xs text-ink-muted">{t("{curated} selected · {archive} classics").replace("{curated}", String(curatedCount)).replace("{archive}", String(archiveCount))}</span>
      </div>
      <p className="text-sm leading-6 text-ink-muted">{t("Browse selected modern stories and the full classic archive. Read the original before starting a project.")}</p>
      <div className="grid gap-3 bg-surface-container p-4 sm:grid-cols-[minmax(0,1fr)_190px] sm:items-end">
        <div>
          <FieldLabel htmlFor="story-search">{t("Search stories")}</FieldLabel>
          <TextField id="story-search" type="search" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} placeholder={t("Title, author, tag, or theme")}/>
        </div>
        <div>
          <FieldLabel>{t("Sort by")}</FieldLabel>
          <Select aria-label={t("Sort stories")} className="w-full" value={sort} onValueChange={(value) => { setSort(value as SortKey); setPage(0); }} options={SORT_OPTIONS.map((option) => ({ value: option.value, label: t(option.label) }))} />
        </div>
      </div>
      <div role="group" aria-label={t("Filter by collection")} className="flex flex-wrap gap-2">
        {(["all", "curated", "archive"] as const).map((choice) => (
          <button key={choice} type="button" aria-pressed={source === choice} onClick={() => { setSource(choice); setPage(0); }} className={`min-h-11 border-2 px-3 font-meta text-xs font-bold ${source === choice ? "border-ink-black bg-ink-black text-bristol" : "border-ink-black/15 bg-bristol text-ink-muted hover:border-ink-black"}`}>{t(choice === "all" ? "All stories" : choice === "curated" ? "Selected stories" : "Classic archive")}</button>
        ))}
      </div>
      <div role="group" aria-label={t("Filter by tag")} className="flex flex-wrap gap-2">
        <button type="button" aria-pressed={genres.length === 0} onClick={() => { setGenres([]); setPage(0); }} className={`min-h-11 border-2 px-3 font-meta text-xs font-bold ${genres.length ? "border-ink-black/15 bg-bristol text-ink-muted hover:border-ink-black" : "border-ink-black bg-ink-black text-bristol"}`}>{t("All tags")}</button>
        {availableGenres.map((genre) => <button key={genre} type="button" aria-pressed={genres.includes(genre)} onClick={() => toggleGenre(genre)} className={`min-h-11 border-2 px-3 font-meta text-xs font-bold ${genres.includes(genre) ? "border-ink-black bg-ink-black text-bristol" : "border-ink-black/15 bg-bristol text-ink-muted hover:border-ink-black"}`}>{t(genreLabel(genre))}</button>)}
      </div>
      <div className="flex items-center justify-between gap-2 border-t-2 border-ink-black/10 pt-3 text-xs text-ink-muted">
        <span role="status">{t("{count} stories shown").replace("{count}", String(filtered.length))}</span>
        {(search || genres.length > 0 || source !== "all") && <button type="button" onClick={() => { setSearch(""); setGenres([]); setSource("all"); setPage(0); }} className="min-h-11 font-meta font-bold underline underline-offset-4 hover:text-hero-red">{t("Clear filters")}</button>}
      </div>
      {visible.length ? <div className="grid gap-4 sm:grid-cols-2" aria-label={t("Story choices")}>{visible.map((story) => {
        const selected = selectedCode === story.code;
        const index = story.source_kind === "archive" ? null : stories.findIndex((item) => item.code === story.code) + 1;
        return <article key={story.code} className={`flex min-w-0 flex-col border-2 bg-bristol shadow-paper-sm ${selected ? "border-ink-black" : "border-ink-black/10"}`}>
          <div className={`relative min-h-20 overflow-hidden px-4 py-3 ${TONES[story.genres?.[0]] ?? "bg-pulp-paper"}`}>
            {index !== null && <div className="absolute -right-2 -top-8 font-display text-[6.5rem] font-black leading-none text-ink-black/[0.07]" aria-hidden="true">{String(index).padStart(2, "0")}</div>}
            <p className="relative font-meta text-[0.68rem] font-bold uppercase tracking-[0.16em] text-ink-black/70">{t(genreLabel(story.genres?.[0] ?? "story"))} / {index !== null ? String(index).padStart(2, "0") : t("CLASSIC ARCHIVE")}</p>
            <h3 className="relative mt-2 font-display text-[1.4rem] font-black leading-tight tracking-tight text-ink-black">{story.title}</h3>
          </div>
          <div className="flex flex-1 flex-col px-4 py-4">
            <p className="font-meta text-xs text-ink-muted">{story.author} · {new Intl.NumberFormat(language).format(story.words)} {t("words")} · {Math.max(1, Math.ceil(story.words / 220))} {t("min read")}</p>
            {story.publish_year && <p className="mt-2 text-xs text-ink-muted">{story.publish_source ? `${story.publish_source} · ` : ""}{story.publish_year}</p>}
            {story.genres.length > 1 && <div className="mt-2 flex flex-wrap gap-1.5" aria-label={t("Story tags")}>{story.genres.slice(1, 4).map((genre) => <span key={genre} className="border border-ink-black/15 px-2 py-0.5 font-meta text-[0.67rem] text-ink-muted">{t(genreLabel(genre))}</span>)}</div>}
            {story.license && <p className="mt-2 w-fit bg-pulp-paper px-2 py-1 font-meta text-[0.68rem] font-bold uppercase tracking-[0.08em] text-ink-muted">{story.license}</p>}
            {story.source_kind === "archive" && <p className="mt-2 w-fit bg-chip-gold/45 px-2 py-1 font-meta text-[0.68rem] font-bold uppercase tracking-[0.08em] text-ink-muted">{t("Rights vary by location")}</p>}
            {story.description && <p className="mt-3 text-sm leading-6 text-ink-black">{t(story.description)}</p>}
            {story.showcase_note && <p className="mt-3 border-l-[3px] border-hero-red pl-3 text-xs leading-5 text-ink-muted">{t(story.showcase_note)}</p>}
            {story.content_note && <p className="mt-3 text-xs text-ink-muted"><strong>{t("Content note")}:</strong> {t(story.content_note)}</p>}
            <div className="mt-auto flex flex-wrap items-center gap-2 pt-5">
              {onSelect ? <Button size="sm" variant={selected ? "secondary" : "primary"} aria-pressed={selected} onClick={() => onSelect(story)}>{selected ? t("SELECTED") : t("CHOOSE STORY")}</Button>
                : <Link className="inline-flex min-h-11 items-center border-2 border-ink-black bg-hero-red px-3 font-meta text-xs font-bold text-bristol shadow-ink-sm hover:bg-[#94141c]" to={`/signup?sample=${encodeURIComponent(story.code)}`}>{t("START HERE")}</Link>}
              <Button size="sm" variant="outline" id={`read-${story.code}`} onClick={(event) => openReader(story.code, event.currentTarget)}>{t("READ STORY")}</Button>
            </div>
          </div>
        </article>;
      })}</div> : <div role="status" className="bg-pulp-paper p-7 text-center"><p className="font-display text-xl font-bold">{t("NO STORIES FOUND")}</p><p className="mt-2 text-sm text-ink-muted">{t("Try another title, theme, or tag.")}</p></div>}
      {pageCount > 1 && <nav aria-label={t("Sample story pages")} className="flex items-center justify-between gap-2 pt-2">
        <Button variant="outline" size="sm" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t("PREVIOUS")}</Button>
        <span className="font-meta text-xs tabular-nums">{t("Page {page} of {total}").replace("{page}", String(currentPage + 1)).replace("{total}", String(pageCount))}</span>
        <Button variant="outline" size="sm" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>{t("NEXT")}</Button>
      </nav>}
    </section>
  );
}
