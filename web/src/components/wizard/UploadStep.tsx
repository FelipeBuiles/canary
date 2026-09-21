import { useState, useRef, useMemo, useEffect, lazy, Suspense } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import type { ConfigOverrides, ShortStory } from "../../types/api";
import { LANGUAGES, useI18n } from "../../i18n";
import type { LanguageCode } from "../../i18n";
import { useShortStories } from "../../api/queries";
import { LetteringChoice, type LetteringMode } from "./LetteringChoice";
import { Select } from "../ui/Select";
import { FieldLabel, TextField } from "../ui/Field";
import { browseStories, type SortKey } from "../../lib/storyBrowser";

interface UploadStepProps {
  onSubmit: (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  onSubmitImport: (urlOrCode: string, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  isPending: boolean;
  error: string | null;
  onCancel?: () => void;
}

const ProjectModelControls = import.meta.env.DEV ? lazy(() => import("./ProjectModelControls")) : null;

const ACCEPTED = [".txt", ".epub", ".pdf"];
const PAGE_SIZE = 8;
const SAMPLE_CHOICES = [
  { code: "the-gift-of-the-magi", label: "SHORT READ", basis: "A compact story of two gifts and one couple; length comes from the catalog word count." },
  { code: "the-open-window", label: "DIALOGUE-LED", basis: "A visitor, a conversation, and a surprise: a useful study in expressions and dialogue." },
  { code: "the-most-dangerous-game", label: "VISUALLY VARIED", basis: "From shipwreck to chateau to jungle pursuit: contrasting settings and physical action." },
] as const;
export function UploadStep({ onSubmit, onSubmitImport, isPending, error, onCancel }: UploadStepProps) {
  const { language, t } = useI18n();
  const [modelControlsOpen, setModelControlsOpen] = useState(false);
  const [modelSelections, setModelSelections] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState<LanguageCode>(language);
  const [step, setStep] = useState<"source" | "details" | "lettering">("source");
  const [letteringMode, setLetteringMode] = useState<LetteringMode | null>(null);
  const [tab, setTab] = useState<"file" | "library">("library");
  const [browsing, setBrowsing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("title");
  const [page, setPage] = useState(0);
  const [pastedUrlOrCode, setPastedUrlOrCode] = useState("");
  const [selectedStory, setSelectedStory] = useState<ShortStory | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const previousStep = useRef(step);
  const { data: shortStories, isLoading, isError, refetch, isFetching } = useShortStories();
  const curatedStories = useMemo(() => SAMPLE_CHOICES.flatMap((choice) => {
    const story = shortStories?.find((item) => item.code === choice.code);
    return story ? [{ story, ...choice }] : [];
  }), [shortStories]);
  const filteredStories = useMemo(() => browseStories(shortStories ?? [], {
    search: searchQuery, genres: [], sort: sortBy,
  }), [shortStories, searchQuery, sortBy]);
  const pageCount = Math.max(1, Math.ceil(filteredStories.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleStories = browsing
    ? filteredStories.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE)
    : curatedStories.map(({ story }) => story);
  const ext = file ? "." + file.name.split(".").pop()?.toLowerCase() : "";
  const extOk = !file || ACCEPTED.includes(ext);
  const sourceReady = tab === "file" ? Boolean(file && extOk) : Boolean(selectedStory || pastedUrlOrCode.trim());
  const sourceTitle = tab === "file" ? file?.name : selectedStory?.title ?? pastedUrlOrCode;
  const languageLabel = LANGUAGES.find((item) => item.code === targetLanguage)?.label ?? targetLanguage;

  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    contentRef.current?.scrollTo?.({ top: 0 });
    headingRef.current?.focus({ preventScroll: true });
  }, [step]);

  function chooseFile(nextFile: File) {
    setFile(nextFile);
    setName(nextFile.name.replace(/\.[^.]+$/, ""));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (isPending || !sourceReady) return;
    if (step === "source") {
      setStep("details");
      return;
    }
    if (!name.trim()) return;
    if (step === "details") { setStep("lettering"); return; }
    if (!letteringMode) return;
    const overrides: Partial<ConfigOverrides> = { target_language: targetLanguage, lettering_mode: letteringMode };
    if (import.meta.env.DEV && Object.keys(modelSelections).length) overrides.dev_model_selections = modelSelections;
    if (tab === "file" && file) onSubmit(file, name.trim(), overrides);
    else onSubmitImport(selectedStory?.code ?? pastedUrlOrCode.trim(), name.trim(), overrides);
  }

  return (
    <form onSubmit={handleSubmit} className="flex min-h-0 max-h-[calc(100dvh-2rem)] flex-col">
      <Card className="flex min-h-0 flex-col overflow-hidden">
        <div ref={contentRef} className="min-h-0 overflow-y-auto overscroll-contain p-5 sm:p-7">
          <div className="flex justify-end font-meta text-xs uppercase text-ink-muted">
            <span>{step === "source" ? t("STEP 1 OF 3") : step === "details" ? t("STEP 2 OF 3") : t("STEP 3 OF 3")}</span>
          </div>
          <h1 ref={headingRef} tabIndex={-1} className="mt-4 font-display text-[2rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black sm:text-[2.6rem]">
            {step === "source" ? t("CHOOSE A STARTING POINT") : step === "details" ? t("PREPARE YOUR MANUSCRIPT") : t("CHOOSE YOUR LETTERING")}
          </h1>
          <p className="mt-3 max-w-[55ch] font-body text-sm leading-relaxed text-ink-muted">
            {step === "source" ? t("Choose a sample or bring your own manuscript. You decide when generation begins.") : step === "details" ? t("Save your source now. In Story, review the credit estimate before starting analysis.") : t("This shapes how your comic looks—and how you can change it later. Compare both before choosing.")}
          </p>

          {step === "source" ? (
            <div className="mt-5 space-y-4">
              <div role="group" aria-label={t("SOURCE")} className="grid grid-cols-2 border-b-2 border-ink-black/15">
                {(["library", "file"] as const).map((sourceTab) => (
                  <button key={sourceTab} type="button" aria-pressed={tab === sourceTab} onClick={() => setTab(sourceTab)} className={`min-h-11 px-3 py-3 font-body text-sm font-bold ${tab === sourceTab ? "border-b-[3px] border-ink-black text-ink-black" : "text-ink-muted hover:bg-surface-container"}`}>
                    {sourceTab === "library" ? t("TRY A SAMPLE") : t("UPLOAD MANUSCRIPT")}
                  </button>
                ))}
              </div>
              {tab === "file" ? (
                <div>
                  <button type="button" onClick={() => fileRef.current?.click()} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const dropped = e.dataTransfer.files[0]; if (dropped) chooseFile(dropped); }} aria-label={t("DROP FILE OR CLICK TO BROWSE")} className={`flex min-h-40 w-full flex-col items-center justify-center gap-3 border-2 border-dashed p-5 ${file && extOk ? "border-archive-sage bg-chip-sage/30" : "border-ink-black bg-pulp-paper"}`}>
                    <Icon name={file && extOk ? "check" : "plus"} size={22} />
                    <span className="max-w-full break-words font-body text-sm font-bold">{file?.name ?? t("DROP FILE OR CLICK TO BROWSE")}</span>
                    <span className="text-sm text-ink-muted">.txt, .epub, .pdf</span>
                  </button>
                  {!extOk && <p role="alert" className="mt-2 text-sm text-hero-red">{t("Unsupported file type. Accepted:")} {ACCEPTED.join(", ")}</p>}
                  <input ref={fileRef} name="novelFile" type="file" accept=".txt,.epub,.pdf" className="hidden" onChange={(e) => { const nextFile = e.target.files?.[0]; if (nextFile) chooseFile(nextFile); }} />
                </div>
              ) : (
                <>
                  {browsing ? (
                    <div className="space-y-3">
                      <FieldLabel htmlFor="story-search">{t("Search stories by title, author, or genre...")}</FieldLabel>
                      <TextField id="story-search" type="search" value={searchQuery} onChange={(e) => { setSearchQuery(e.target.value); setPage(0); }} />
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <Select aria-label={t("Sort stories")} value={sortBy} onValueChange={(value) => { setSortBy(value as SortKey); setPage(0); }} options={[{ value: "title", label: t("Title (A–Z)") }, { value: "shortest", label: t("Shortest") }, { value: "year", label: t("Year (newest)") }]} />
                        <Button type="button" variant="outline" onClick={() => setBrowsing(false)}>{t("BACK TO THREE SAMPLES")}</Button>
                      </div>
                    </div>
                  ) : <p className="text-sm leading-relaxed text-ink-muted">{t("Three starting points, chosen for story length and content—not ratings or predicted results.")}</p>}

                  {isLoading ? <p role="status" className="py-5 text-sm">{t("LOADING SAMPLE STORIES…")}</p> : isError ? (
                    <div role="alert" className="space-y-3 py-4">
                      <p className="text-sm text-hero-red">{t("THE SAMPLE LIBRARY COULD NOT LOAD")}</p>
                      <Button type="button" variant="outline" onClick={() => void refetch()} disabled={isFetching}>{t("TRY AGAIN")}</Button>
                    </div>
                  ) : !shortStories?.length ? <p role="status" className="py-5 text-sm">{t("The sample library is empty. You can still upload a manuscript or paste a story URL.")}</p> : (
                    <>
                      <div className="space-y-2" aria-label={t("SHORT STORY LIBRARY")}>
                        {visibleStories.length === 0 ? <p role="status" className="py-4 text-sm">{browsing ? t("NO STORIES FOUND") : t("These featured samples are unavailable. Browse the current catalog instead.")}</p> : visibleStories.map((story) => {
                          const choice = !browsing ? curatedStories.find((item) => item.code === story.code) : null;
                          const selected = selectedStory?.code === story.code;
                          return (
                            <button key={story.code} type="button" aria-pressed={selected} onClick={() => { setSelectedStory(story); setPastedUrlOrCode(""); setName(story.title); }} className={`block min-h-11 w-full p-4 text-left transition-colors ${selected ? "bg-chip-gold ring-2 ring-inset ring-ink-black" : "bg-surface-container hover:bg-pulp-paper"}`}>
                              {choice && <span className="block font-meta text-xs font-bold text-ink-muted">{t(choice.label)}</span>}
                              <span className="mt-1 block font-display text-lg font-bold leading-snug">{story.title}</span>
                              <span className="mt-1 block text-sm text-ink-muted">{story.author} · {story.words.toLocaleString()} {t("words")}</span>
                              {choice && <span className="mt-2 block text-sm leading-relaxed text-ink-muted">{t(choice.basis)}</span>}
                              {selected && <span className="mt-2 flex items-center gap-2 font-meta text-xs font-bold"><Icon name="check" size={14} />{t("SELECTED")}</span>}
                            </button>
                          );
                        })}
                      </div>
                      {browsing ? (
                        <nav aria-label={t("Sample story pages")} className="flex items-center justify-between gap-2">
                          <Button type="button" variant="outline" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t("PREVIOUS")}</Button>
                          <span role="status" className="text-center text-xs tabular-nums">{t("Page {page} of {total}").replace("{page}", String(currentPage + 1)).replace("{total}", String(pageCount))} · {t("{count} stories").replace("{count}", String(filteredStories.length))}</span>
                          <Button type="button" variant="outline" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>{t("NEXT")}</Button>
                        </nav>
                      ) : <Button type="button" variant="outline" onClick={() => setBrowsing(true)} className="w-full">{t("BROWSE ALL STORIES")}</Button>}
                    </>
                  )}
                  <details className="bg-surface-container px-4">
                    <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs uppercase">{t("USE ANOTHER SOURCE")}</summary>
                    <div className="pb-4">
                      <FieldLabel htmlFor="story-url">{t("PASTE URL OR CODE")}</FieldLabel>
                      <TextField id="story-url" type="text" value={pastedUrlOrCode} onChange={(e) => {
                        const value = e.target.value;
                        setPastedUrlOrCode(value);
                        setSelectedStory(null);
                        const code = value.match(/onlinereader\/([a-zA-Z0-9_-]+)/)?.[1] ?? value.split("/").pop() ?? "";
                        setName(code.replace(/[^a-zA-Z0-9]+/g, " ").trim().replace(/\b\w/g, (c) => c.toUpperCase()));
                      }} placeholder={t("e.g. story URL or library code")} />
                    </div>
                  </details>
                </>
              )}
            </div>
          ) : step === "lettering" ? (
            <LetteringChoice value={letteringMode} onChange={setLetteringMode} disabled={isPending} />
          ) : (
            <div className="mt-5 space-y-5">
              <div className="animate-proof-reveal bg-pulp-paper p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0"><p className="font-meta text-xs text-ink-muted">{t("PRODUCTION TICKET")}</p><p className="mt-1 break-words font-body text-base font-bold">{sourceTitle}</p></div>
                  <Button type="button" variant="outline" onClick={() => setStep("source")} disabled={isPending}>{t("CHANGE")}</Button>
                </div>
                <p className="mt-3 text-sm">{languageLabel}</p>
                <p className="mt-2 text-sm leading-relaxed text-ink-muted">{t("First review after analysis: your characters, places, story outline, and proposed adaptation brief.")}</p>
              </div>
              <div><FieldLabel htmlFor="project-name">{t("PROJECT NAME")}</FieldLabel><TextField id="project-name" name="projectName" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="off" disabled={isPending} /></div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div><FieldLabel>{t("OUTPUT LANGUAGE")}</FieldLabel><Select aria-label={t("OUTPUT LANGUAGE")} value={targetLanguage} onValueChange={(value) => setTargetLanguage(value as LanguageCode)} options={LANGUAGES.map((item) => ({ value: item.code, label: item.label }))} disabled={isPending} className="w-full" /></div>
              </div>
              <p className="text-sm leading-relaxed text-ink-muted">{t("Output language controls generated dialogue and narration.")}</p>
              {ProjectModelControls && <details className="bg-surface-container px-4" onToggle={(event) => setModelControlsOpen(event.currentTarget.open)}>
                <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs uppercase">{t("Models for this project (dev)")}</summary>
                {modelControlsOpen && <Suspense fallback={<p role="status">{t("Loading model settings…")}</p>}>
                  <ProjectModelControls selections={modelSelections} onChange={setModelSelections} disabled={isPending} />
                </Suspense>}
              </details>}
              <p className="bg-surface-container p-4 text-sm leading-relaxed text-ink-muted">{t("Review a live credit estimate before each generation action. Set the target page range in Story.")}</p>
              <p className="text-sm leading-relaxed text-ink-muted">{t("After analysis, approve your brief in Story, choose your look, then approve the cast before preparing pages. Drawing waits for your action in Pages.")}</p>
            </div>
          )}
        </div>
        <footer className="shrink-0 border-t-2 border-ink-black bg-bristol p-4 sm:px-7 sm:py-5">
          {error && <p role="alert" className="mb-3 text-sm text-hero-red">{error}</p>}
          <div className="mb-3 min-w-0" aria-live="polite">
            <p className="truncate font-body text-sm font-bold">{sourceReady ? (step !== "source" ? name || sourceTitle : sourceTitle) : t("Choose a source to continue")}</p>
            {step === "lettering" && <p className="mt-1 text-sm font-bold">{t(letteringMode === "integrated" ? "Integrated lettering" : letteringMode === "editable" ? "Editable lettering" : "Select a lettering option to create your project.")}</p>}
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">{t("Saves your source only. No generation starts now.")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" size="lg" disabled={isPending || !sourceReady || (step !== "source" && !name.trim()) || (step === "lettering" && !letteringMode)}>{isPending ? t("CREATING…") : step !== "lettering" ? t("CONTINUE") : t("CREATE PROJECT")}</Button>
            {step !== "source" && <Button type="button" variant="outline" onClick={() => setStep(step === "lettering" ? "details" : "source")} disabled={isPending}>{t("BACK")}</Button>}
            {onCancel && <Button type="button" variant="outline" onClick={onCancel} disabled={isPending}>{t("CANCEL")}</Button>}
          </div>
        </footer>
      </Card>
    </form>
  );
}
