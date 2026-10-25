import { ErrorNotice } from "../composites/ErrorNotice";
import { useState, useRef, useEffect, useMemo, lazy, Suspense, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Check, Clock, Upload, X } from "lucide-react";
import type { ConfigOverrides, ShortStory } from "../../types/api";
import { LANGUAGES, useI18n } from "../../i18n";
import type { LanguageCode } from "../../i18n";
import { useShortStories, useSourcePreview } from "../../api/queries";
import { readManuscriptDraft, writeManuscriptDraft } from "../../lib/manuscriptDraft";
import { cn } from "../../lib/cn";
import { LetteringChoice, type LetteringMode } from "./LetteringChoice";
import { SampleLibrary } from "./SampleLibrary";
import { SourcePreviewPanel } from "./SourcePreviewPanel";
import { previewRejected } from "../../lib/sourcePreview";
import { Select } from "../ui/Select";
import { TextField } from "../ui/Field";

interface UploadStepProps {
  onSubmit: (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  onSubmitImport: (urlOrCode: string, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  isPending: boolean;
  error: Error | string | null;
  onCancel?: () => void;
  initialStoryCode?: string | null;
}

const ProjectModelControls = import.meta.env.DEV ? lazy(() => import("./ProjectModelControls")) : null;

const ACCEPTED = [".txt", ".md", ".markdown", ".docx", ".epub", ".pdf"];
const ACCEPT_ATTRIBUTE = ACCEPTED.join(",");
const ACCEPTED_LABEL = ".txt, .md, .docx, .epub, .pdf";
const PASTED_FILE_NAME = "pasted-manuscript.txt";
/** The quick shelf beside the manuscript panel; the full library is one click away. */
const QUICK_SAMPLES = 6;
const STEPS = ["source", "details", "lettering"] as const;
type Step = typeof STEPS[number];
const STEP_LABELS: Record<Step, string> = { source: "Story", details: "Details", lettering: "Lettering" };
// Source identities are unique per page session, so a cached preview never outlives its source.
let lastSourceId = 0;
const nextSourceId = () => ++lastSourceId;

/** A short first line of pasted prose is usually its title. */
function titleFromText(text: string) {
  const firstLine = text.trim().split(/\r?\n/, 1)[0]?.trim() ?? "";
  return firstLine.length > 0 && firstLine.length <= 80 ? firstLine : "";
}

function countWords(text: string) {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function formatBytes(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const readingMinutes = (words: number) => Math.max(1, Math.ceil(words / 220));

/** Where you are: three caption boxes, the current one in gold. */
function StepTracker({ step }: { step: Step }) {
  const { t } = useI18n();
  const current = STEPS.indexOf(step);
  return (
    <ol aria-label={t("Steps")} className="flex items-center gap-3">
      {STEPS.map((key, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={key} aria-current={active ? "step" : undefined} className="flex items-center gap-3">
            {index > 0 && <span aria-hidden="true" className={cn("hidden h-0.5 w-8 sm:block", index <= current ? "bg-ink-black" : "bg-ink-black/18")} />}
            <span className="flex items-center gap-2">
              <span aria-hidden="true" className={cn(
                "grid size-[26px] place-items-center border font-meta text-[0.6875rem] font-bold",
                active ? "border-ink-black bg-narrator-gold text-ink-black shadow-[2px_2px_0_0_var(--color-ink-black)]"
                  : done ? "border-ink-black bg-ink-black text-pulp-paper" : "border-ink-black/30 text-ink-soft",
              )}>
                {done ? <Check size={13} strokeWidth={3} /> : index + 1}
              </span>
              <span className={cn("font-meta text-[0.6875rem] font-bold uppercase tracking-[0.12em]", index <= current ? "text-ink-black" : "text-ink-soft", !active && "hidden md:inline")}>
                {t(STEP_LABELS[key])}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The source as an object you are taking with you: a typed title page, not a fake cover. */
function TitlePage({ kind, title, author, children }: { kind: string; title: string; author?: string; children?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="relative flex min-h-[26rem] flex-col border-[1.5px] border-ink-black bg-bristol px-8 py-8 shadow-[10px_10px_0_0_var(--color-narrator-gold),10px_10px_0_1.5px_var(--color-ink-black)]">
      <span aria-hidden="true" className="absolute -top-2.5 left-1/2 h-5 w-16 -translate-x-1/2 bg-ink-black" />
      <span className="font-meta text-[0.625rem] font-bold uppercase tracking-[0.16em] text-ink-soft">{kind}</span>
      <span className="mt-5 break-words font-display text-[2rem] font-black uppercase leading-[0.92] tracking-[-0.03em] text-ink-black">{title}</span>
      {author && <span className="mt-2.5 text-sm text-ink-muted">{t("by {author}", { author })}</span>}
      <span aria-hidden="true" className="my-5 h-[3px] w-12 bg-hero-red" />
      {children}
    </div>
  );
}

export function UploadStep({ onSubmit, onSubmitImport, isPending, error, onCancel, initialStoryCode }: UploadStepProps) {
  const { language, t } = useI18n();
  const [modelControlsOpen, setModelControlsOpen] = useState(false);
  const [modelSelections, setModelSelections] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [pastedText, setPastedText] = useState(readManuscriptDraft);
  const [draftRestored, setDraftRestored] = useState(() => Boolean(pastedText.trim()));
  const [sourceRevision, setSourceRevision] = useState(nextSourceId);
  const [dragging, setDragging] = useState(false);
  const [targetLanguage, setTargetLanguage] = useState<LanguageCode>(language);
  const [step, setStep] = useState<Step>("source");
  const [letteringMode, setLetteringMode] = useState<LetteringMode | null>(null);
  // Which source creation uses: the manuscript panel ("file") or a story ("library").
  const [tab, setTab] = useState<"file" | "library">(() => draftRestored && !initialStoryCode ? "file" : "library");
  const [browsing, setBrowsing] = useState(false);
  const [pastedUrlOrCode, setPastedUrlOrCode] = useState("");
  const [selectedStory, setSelectedStory] = useState<ShortStory | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pasteRef = useRef<HTMLTextAreaElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const previousStep = useRef(step);
  const { data: shortStories, isLoading: storiesLoading, isError: storiesError, refetch: refetchStories, isFetching: storiesFetching } = useShortStories();
  const activeStory = pastedUrlOrCode.trim() ? null
    : selectedStory ?? shortStories?.find((item) => item.code === initialStoryCode) ?? null;
  const quickSamples = useMemo(() => {
    const curated = (shortStories ?? []).filter((story) => story.source_kind !== "archive");
    const picks = curated.slice(0, QUICK_SAMPLES);
    // A story chosen elsewhere (signup, the full library) stays visible on the quick shelf.
    if (activeStory && !picks.some((story) => story.code === activeStory.code)) picks.splice(picks.length ? picks.length - 1 : 0, 1, activeStory);
    return picks;
  }, [shortStories, activeStory]);
  const curatedCount = shortStories?.filter((story) => story.source_kind !== "archive").length ?? 0;
  const archiveCount = (shortStories?.length ?? 0) - curatedCount;
  const ext = file ? "." + file.name.split(".").pop()?.toLowerCase() : "";
  const extOk = !file || ACCEPTED.includes(ext);
  const pastedWords = countWords(pastedText);
  const sourceReady = tab === "file" ? Boolean(file ? extOk : pastedWords) : Boolean(activeStory || pastedUrlOrCode.trim());
  const sourceTitle = tab === "file"
    ? file?.name ?? (pastedWords ? t("Pasted text · {count, plural, one {# word} other {# words}}", { count: pastedWords }) : undefined)
    : activeStory?.title ?? pastedUrlOrCode;
  const previewFile = useMemo(() => {
    if (tab !== "file" || step === "source") return null;
    if (file) return extOk ? file : null;
    return pastedWords ? new File([pastedText], PASTED_FILE_NAME, { type: "text/plain" }) : null;
  }, [tab, step, file, extOk, pastedText, pastedWords]);
  const preview = useSourcePreview(previewFile, sourceRevision);
  const sourceBlocked = previewFile !== null && preview.isError && previewRejected(preview.error);
  const sourceKind = tab === "file" ? t("Your manuscript") : activeStory ? t("Sample story") : t("Story link");
  const manuscriptActive = tab === "file" && Boolean(file ? extOk : pastedWords);

  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    contentRef.current?.scrollTo?.({ top: 0 });
    headingRef.current?.focus({ preventScroll: true });
  }, [step]);

  useEffect(() => {
    const timer = window.setTimeout(() => writeManuscriptDraft(pastedText), 400);
    return () => window.clearTimeout(timer);
  }, [pastedText]);

  function chooseFile(nextFile: File) {
    setTab("file");
    setFile(nextFile);
    setSourceRevision(nextSourceId());
    setPastedText("");
    setDraftRestored(false);
    setName(nextFile.name.replace(/\.[^.]+$/, ""));
  }

  function clearFile() {
    setFile(null);
    setSourceRevision(nextSourceId());
    setName("");
    if (fileRef.current) fileRef.current.value = "";
  }

  function changePastedText(text: string) {
    if (file) clearFile();
    setTab("file");
    setSourceRevision(nextSourceId());
    setPastedText(text);
    if (!text.trim()) setDraftRestored(false);
  }

  function chooseStory(story: ShortStory) {
    setTab("library");
    setSelectedStory(story);
    setPastedUrlOrCode("");
    setName(story.title);
  }

  /** Pasting anywhere in the manuscript panel accepts a copied file or copied prose. */
  function handlePanelPaste(e: React.ClipboardEvent<HTMLDivElement>) {
    if (e.target === pasteRef.current) return;
    const pastedFile = e.clipboardData.files[0];
    const text = e.clipboardData.getData("text/plain");
    if (!pastedFile && !text.trim()) return;
    e.preventDefault();
    if (pastedFile) { chooseFile(pastedFile); return; }
    changePastedText(text);
    pasteRef.current?.focus();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (isPending || !sourceReady) return;
    if (step === "source") {
      if (activeStory && !name.trim()) setName(activeStory.title);
      if (tab === "file" && !file && !name.trim()) setName(titleFromText(pastedText) || t("Pasted manuscript"));
      setBrowsing(false);
      setStep("details");
      return;
    }
    if (!name.trim()) return;
    if (step === "details") { if (!sourceBlocked) setStep("lettering"); return; }
    if (!letteringMode) return;
    const overrides: Partial<ConfigOverrides> = { target_language: targetLanguage, lettering_mode: letteringMode };
    if (import.meta.env.DEV && Object.keys(modelSelections).length) overrides.dev_model_selections = modelSelections;
    if (tab === "file" && file) onSubmit(file, name.trim(), overrides);
    else if (tab === "file") onSubmit(previewFile ?? new File([pastedText], PASTED_FILE_NAME, { type: "text/plain" }), name.trim(), overrides);
    else onSubmitImport(activeStory?.code ?? pastedUrlOrCode.trim(), name.trim(), overrides);
  }

  const headingClass = "font-display text-[2.5rem] font-black uppercase leading-[0.9] tracking-[-0.035em] text-ink-black focus:outline-none sm:text-[3.25rem] short:sm:text-[2.5rem]";
  const continueDisabled = isPending || !sourceReady || (step !== "source" && !name.trim()) || (step === "lettering" && !letteringMode) || (step === "details" && sourceBlocked);

  return (
    <form onSubmit={handleSubmit} className="flex h-full min-h-0 flex-col bg-pulp-paper text-ink-black">
      {/* Identity, where you are, a way out. */}
      <header className="grid h-16 shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-3 border-b border-ink-black/12 px-4 sm:h-[72px] short:sm:h-16 sm:px-8 lg:px-10">
        <div className="flex min-w-0 items-center gap-3">
          <img src="/brand/scenewright-panel-frame/scenewright-symbol-primary.svg" alt="" className="size-7 shrink-0" />
          <span className="hidden truncate font-display text-base font-black uppercase tracking-[-0.01em] sm:inline">{t("New production")}</span>
        </div>
        <StepTracker step={step} />
        <div className="flex justify-end">
          {onCancel && (
            <button type="button" onClick={onCancel} disabled={isPending}
              className="inline-flex h-10 items-center gap-2 px-3 font-meta text-[0.8125rem] font-medium text-ink-muted transition-colors hover:bg-sidebar-tint hover:text-ink-black disabled:opacity-50">
              <X size={15} aria-hidden="true" />{t("Cancel")}
            </button>
          )}
        </div>
      </header>

      <div ref={contentRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <p className="sr-only">{step === "source" ? t("STEP 1 OF 3") : step === "details" ? t("STEP 2 OF 3") : t("STEP 3 OF 3")}</p>

        {step === "source" && browsing ? (
          <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-8 lg:px-10">
            <button type="button" onClick={() => setBrowsing(false)}
              className="mb-5 inline-flex min-h-10 items-center gap-2 font-meta text-[0.8125rem] font-medium underline decoration-ink-black/35 underline-offset-4 hover:text-hero-red">
              <ArrowLeft size={15} aria-hidden="true" />{t("Back to your manuscript")}
            </button>
            <h1 ref={headingRef} tabIndex={-1} className="sr-only">{t("Sample stories")}</h1>
            <SampleLibrary
              selectedCode={tab === "library" ? activeStory?.code : null}
              onSelect={chooseStory}
              onReadAndSelect={(story) => { chooseStory(story); setBrowsing(false); setStep("details"); }}
            />
          </div>
        ) : step === "source" ? (
          <div className="mx-auto grid w-full max-w-[1200px] items-start gap-10 px-4 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-12 lg:px-10 lg:py-11 short:lg:py-6">
            {/* Your story is the point; the panel carries the brand's ink and gold. */}
            <section aria-labelledby="new-production-heading" className="min-w-0 space-y-6">
              <div>
                <h1 id="new-production-heading" ref={headingRef} tabIndex={-1} className={headingClass}>{t("Bring your story")}</h1>
                <p className="mt-3 max-w-[40rem] text-[1.0625rem] leading-relaxed text-ink-muted">{t("A chapter, a short story or the whole book. Long books are split into parts at chapter breaks.")}</p>
              </div>
              <div onPaste={handlePanelPaste}
                className={cn(
                  "space-y-4 bg-ink-black bg-[radial-gradient(circle_at_1px_1px,rgb(252_250_237/0.09)_1px,transparent_0)] [background-size:18px_18px] p-5 text-pulp-paper sm:p-7",
                  manuscriptActive ? "shadow-[8px_8px_0_0_var(--color-narrator-gold),8px_8px_0_1px_var(--color-ink-black)]" : "shadow-[6px_6px_0_0_var(--color-ghost-shadow)]",
                )}>
                <button type="button" onClick={() => fileRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => { e.preventDefault(); setDragging(false); const dropped = e.dataTransfer.files[0]; if (dropped) chooseFile(dropped); }}
                  aria-label={file ? t("Replace file {name}", { name: file.name }) : t("Drop your manuscript or browse your files")}
                  className={cn(
                    "flex min-h-52 short:min-h-40 w-full flex-col items-center justify-center gap-2.5 border-2 border-dashed p-6 text-center transition-colors focus-visible:outline-narrator-gold",
                    dragging ? "border-narrator-gold bg-narrator-gold/12" : file && extOk ? "border-narrator-gold bg-narrator-gold/8" : "border-narrator-gold/55 bg-pulp-paper/[0.03] hover:border-narrator-gold hover:bg-narrator-gold/[0.07]",
                  )}>
                  {file && extOk ? <Check size={38} strokeWidth={2.2} aria-hidden="true" className="text-narrator-gold" /> : <Upload size={36} strokeWidth={1.8} aria-hidden="true" className="text-narrator-gold" />}
                  <span className="max-w-full break-words font-display text-2xl font-black uppercase tracking-[-0.02em]">{file?.name ?? t("Drop your manuscript")}</span>
                  <span className="text-[0.9375rem] text-on-chrome-muted">
                    {file ? formatBytes(file.size) : <>{t("or")} <span className="text-narrator-gold underline underline-offset-4">{t("browse your files")}</span></>}
                  </span>
                  {!file && <span className="mt-1 font-meta text-xs tracking-[0.04em] text-on-chrome-muted">{ACCEPTED_LABEL}</span>}
                </button>
                {file && <div className="flex justify-end"><button type="button" onClick={clearFile} className="min-h-10 px-2 font-meta text-[0.8125rem] font-medium text-narrator-gold underline underline-offset-4 focus-visible:outline-narrator-gold">{t("Remove")}</button></div>}
                {!extOk && <p role="alert" className="bg-chip-red px-3 py-2 text-sm text-status-blocked-text">{t("Unsupported file type. Accepted:")} {ACCEPTED_LABEL}. {t("From another app, copy the text and paste it below.")}</p>}
                <input ref={fileRef} name="novelFile" type="file" accept={ACCEPT_ATTRIBUTE} className="hidden" onChange={(e) => { const nextFile = e.target.files?.[0]; if (nextFile) chooseFile(nextFile); }} />
                <div className="flex items-center gap-3 font-meta text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-on-chrome-muted" aria-hidden="true">
                  <span className="h-px flex-1 bg-pulp-paper/18" />{t("Or paste it")}<span className="h-px flex-1 bg-pulp-paper/18" />
                </div>
                <div>
                  <label htmlFor="manuscript-text" className="sr-only">{t("Paste your text")}</label>
                  <textarea id="manuscript-text" ref={pasteRef} rows={4} value={pastedText} onChange={(e) => changePastedText(e.target.value)}
                    placeholder={t("Paste a chapter, a story, or the whole book.")} aria-describedby="manuscript-text-count"
                    className="block max-h-72 min-h-24 w-full resize-y border border-pulp-paper/24 bg-pulp-paper/[0.06] px-3.5 py-3 font-body text-[0.9375rem] leading-relaxed text-pulp-paper placeholder:text-on-chrome-muted focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-narrator-gold" />
                  <div className="mt-1.5 flex items-start justify-between gap-3">
                    <p className="text-xs text-on-chrome-muted">
                      {draftRestored && <>{t("Restored the text you pasted last time.")} <button type="button" className="text-narrator-gold underline underline-offset-2" onClick={() => changePastedText("")}>{t("Clear")}</button></>}
                    </p>
                    <p id="manuscript-text-count" className="shrink-0 font-meta text-xs text-on-chrome-muted" aria-live="polite">
                      {pastedWords ? t("{count, plural, one {# word} other {# words}}", { count: pastedWords }) : ""}
                    </p>
                  </div>
                </div>
              </div>
            </section>

            {/* The fallback: a short shelf of sample texts, with the whole library one click away. */}
            <aside aria-labelledby="samples-heading" className="min-w-0 lg:pt-1.5">
              <span className="font-meta text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-ink-soft">{t("No manuscript handy?")}</span>
              <h2 id="samples-heading" className="mt-2 font-display text-[1.625rem] font-black uppercase leading-none tracking-[-0.02em]">{t("Try a sample")}</h2>
              <p className="mt-1 text-sm text-ink-muted">{t("Short stories you can adapt to see how it works.")}</p>
              {storiesLoading ? <p role="status" className="mt-4 text-sm text-ink-muted">{t("LOADING SAMPLE STORIES…")}</p>
                : storiesError ? (
                  <div role="alert" className="mt-4 space-y-2 bg-chip-red px-4 py-3">
                    <p className="text-sm font-semibold text-status-blocked-text">{t("THE SAMPLE LIBRARY COULD NOT LOAD")}</p>
                    <button type="button" onClick={() => void refetchStories()} disabled={storiesFetching} className="min-h-9 font-meta text-[0.8125rem] font-medium underline underline-offset-4">{t("TRY AGAIN")}</button>
                  </div>
                ) : !shortStories?.length ? <p role="status" className="mt-4 text-sm text-ink-muted">{t("The sample library is empty. You can still upload a manuscript or paste a story URL.")}</p>
                : (
                  <fieldset className="mt-4 min-w-0 border-t border-ink-black/12">
                    <legend className="sr-only">{t("Sample stories")}</legend>
                    {quickSamples.map((story) => {
                      const checked = tab === "library" && activeStory?.code === story.code;
                      return (
                        <label key={story.code} className={cn(
                          "flex cursor-pointer items-start gap-3 border-b border-ink-black/12 px-2.5 py-3 short:py-2 transition-colors",
                          checked ? "bg-narrator-gold shadow-[inset_0_0_0_1px_var(--color-ink-black)]" : "hover:bg-sidebar-tint",
                        )}>
                          <input type="radio" name="sample-story" value={story.code} checked={checked} onChange={() => chooseStory(story)} className="mt-0.5 size-[18px] shrink-0 accent-hero-red" />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-baseline gap-2">
                              <span className="font-semibold leading-5">{story.title}</span>
                              <span className="ml-auto shrink-0 font-meta text-xs text-ink-soft">{readingMinutes(story.words)} {t("min")}</span>
                            </span>
                            {story.description && <span className="mt-0.5 block truncate text-[0.8125rem] text-ink-muted">{t(story.description)}</span>}
                          </span>
                        </label>
                      );
                    })}
                  </fieldset>
                )}
              {!storiesLoading && !storiesError && Boolean(shortStories?.length) && (
                <button type="button" onClick={() => setBrowsing(true)} className="mt-3.5 min-h-9 text-left short:mt-2 font-meta text-[0.8125rem] font-medium underline decoration-ink-black/35 underline-offset-4 hover:text-hero-red">
                  {t("All {curated} samples and {archive} classics", { curated: new Intl.NumberFormat(language).format(curatedCount), archive: new Intl.NumberFormat(language).format(archiveCount) })}
                </button>
              )}
              <details className="mt-5 border-t border-ink-black/12 pt-1 short:mt-3">
                <summary className="min-h-10 cursor-pointer py-2.5 font-meta text-[0.8125rem] font-medium">{t("Have a story code or link?")}</summary>
                <div className="pb-2">
                  <label htmlFor="story-url" className="mb-1.5 block font-meta text-xs font-medium text-ink-muted">{t("Library of Short Stories code or URL")}</label>
                  <TextField id="story-url" type="text" value={pastedUrlOrCode} onChange={(e) => {
                    const value = e.target.value;
                    setTab("library");
                    setPastedUrlOrCode(value);
                    setSelectedStory(null);
                    const code = value.match(/onlinereader\/([a-zA-Z0-9_-]+)/)?.[1] ?? value.split("/").pop() ?? "";
                    setName(code.replace(/[^a-zA-Z0-9]+/g, " ").trim().replace(/\b\w/g, (c) => c.toUpperCase()));
                  }} placeholder={t("e.g. the-open-window")} />
                </div>
              </details>
            </aside>
          </div>
        ) : step === "lettering" ? (
          <div className="mx-auto w-full max-w-[1200px] px-4 py-8 sm:px-8 lg:px-10 lg:py-9 short:lg:py-6">
            <LetteringChoice value={letteringMode} onChange={setLetteringMode} disabled={isPending}
              heading={<h1 ref={headingRef} tabIndex={-1} className={headingClass}>{t("How should the words live?")}</h1>} />
          </div>
        ) : (
          <div className="mx-auto grid w-full max-w-[1120px] items-start gap-10 px-4 py-8 sm:px-8 md:grid-cols-[minmax(0,320px)_minmax(0,1fr)] lg:gap-16 lg:px-10 lg:py-12 short:lg:py-7">
            <div className="space-y-5">
              <TitlePage kind={sourceKind} title={name.trim() || sourceTitle || t("Your manuscript")} author={tab === "library" ? activeStory?.author : undefined}>
                {tab === "library" && activeStory?.description
                  ? <p className="text-sm leading-relaxed">{t(activeStory.description)}</p>
                  : tab === "file" && !file && pastedText.trim()
                    ? <p className="line-clamp-6 whitespace-pre-line text-sm leading-relaxed">{pastedText.trim().slice(0, 420)}</p>
                    : <p className="text-sm leading-relaxed text-ink-muted">{file ? file.name : sourceTitle}</p>}
                <span className="mt-auto flex justify-between border-t border-ink-black/12 pt-3.5 font-meta text-[0.6875rem] text-ink-soft">
                  {tab === "library" && activeStory
                    ? <><span>{new Intl.NumberFormat(language).format(activeStory.words)} {t("words")}</span><span>{readingMinutes(activeStory.words)} {t("min read")}</span></>
                    : tab === "file" && !file && pastedWords ? <span>{t("{count, plural, one {# word} other {# words}}", { count: pastedWords })}</span>
                    : <span>{file ? formatBytes(file.size) : t("Story link")}</span>}
                </span>
              </TitlePage>
              <button type="button" onClick={() => setStep("source")} disabled={isPending}
                className="min-h-9 font-meta text-[0.8125rem] font-medium underline decoration-ink-black/35 underline-offset-4 hover:text-hero-red disabled:opacity-50">
                {t("Use a different story")}
              </button>
            </div>

            <div className="min-w-0 space-y-7">
              <div>
                <h1 ref={headingRef} tabIndex={-1} className={headingClass}>{t("Name your comic")}</h1>
                <p className="mt-3 text-[1.0625rem] leading-relaxed text-ink-muted">{t("You can rename it later. The language sets the comic's dialogue and narration.")}</p>
              </div>
              {previewFile && <SourcePreviewPanel preview={preview} />}
              {activeStory?.rights_note && <p className="bg-chip-gold px-4 py-3 text-sm leading-6 text-ink-black">{t(activeStory.rights_note)}</p>}
              <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_15rem]">
                <div className="flex flex-col gap-2">
                  <label htmlFor="project-name" className="font-meta text-xs font-medium text-ink-muted">{t("Production name")}</label>
                  <TextField id="project-name" name="projectName" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="off" disabled={isPending} className="h-12 text-lg font-medium" />
                </div>
                <div className="flex flex-col gap-2">
                  <span className="font-meta text-xs font-medium text-ink-muted" aria-hidden="true">{t("Comic language")}</span>
                  <Select aria-label={t("Comic language")} value={targetLanguage} onValueChange={(value) => setTargetLanguage(value as LanguageCode)} options={LANGUAGES.map((item) => ({ value: item.code, label: item.label }))} disabled={isPending} className="w-full" />
                </div>
              </div>
              {ProjectModelControls && <details className="bg-surface-container px-4" onToggle={(event) => setModelControlsOpen(event.currentTarget.open)}>
                <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs uppercase">{t("Models for this project (dev)")}</summary>
                {modelControlsOpen && <Suspense fallback={<p role="status">{t("Loading model settings…")}</p>}>
                  <ProjectModelControls selections={modelSelections} onChange={setModelSelections} disabled={isPending} />
                </Suspense>}
              </details>}
              <section aria-labelledby="next-steps-heading">
                <h2 id="next-steps-heading" className="font-meta text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-ink-soft">{t("What happens next")}</h2>
                <ol className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {([
                    ["01", "Story", "We read it and draft your adaptation brief."],
                    ["02", "Look", "You choose the art style and meet the cast."],
                    ["03", "Pages", "Every page is drawn complete for you to review."],
                    ["04", "Book", "Read it, export it, share it."],
                  ] as const).map(([number, label, text], index) => (
                    <li key={number} className={cn("p-4", index === 0 ? "border border-ink-black bg-narrator-gold shadow-[3px_3px_0_0_var(--color-ink-black)]" : "border border-ink-black/12 bg-bristol")}>
                      <span className="flex items-center gap-2">
                        <span className={cn("grid size-[22px] place-items-center border font-meta text-[0.625rem] font-bold", index === 0 ? "border-ink-black bg-pulp-paper" : "border-ink-black/30 text-ink-muted")}>{number}</span>
                        <span className="font-display text-[0.9375rem] font-black uppercase">{t(label)}</span>
                      </span>
                      <span className={cn("mt-2.5 block text-[0.8125rem] leading-[1.45]", index === 0 ? "text-ink-black" : "text-ink-muted")}>{t(text)}</span>
                    </li>
                  ))}
                </ol>
              </section>
            </div>
          </div>
        )}
      </div>

      {/* What you're taking with you, the reassurance said once, and the way forward. */}
      <footer className="shrink-0 border-t-2 border-ink-black bg-bristol px-4 py-3 short:py-2 sm:px-8 lg:px-10">
        {error && <div className="mb-3"><ErrorNotice error={error} operation="upload" /></div>}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 sm:min-h-16">
          <div className="flex min-w-0 flex-1 items-center gap-3.5" aria-live="polite">
            {sourceReady ? <>
              <span aria-hidden="true" className="flex h-[52px] w-10 shrink-0 flex-col gap-1 border border-ink-black bg-bristol px-1.5 py-2 shadow-[3px_3px_0_0_var(--color-narrator-gold),3px_3px_0_1px_var(--color-ink-black)]">
                <span className="h-[3px] w-[70%] bg-ink-black" /><span className="h-0.5 w-full bg-ink-black/25" /><span className="h-0.5 w-full bg-ink-black/25" /><span className="h-0.5 w-4/5 bg-ink-black/25" />
              </span>
              <span className="min-w-0">
                <span className="block truncate font-semibold">{step !== "source" ? name || sourceTitle : sourceTitle}</span>
                <span className="block truncate text-xs text-ink-soft">
                  {step === "lettering" && letteringMode
                    ? `${t(letteringMode === "integrated" ? "Integrated lettering" : "Editable lettering")} · ${t("Can’t be changed after creating the project")}`
                    : step === "lettering" ? t("Choose one. It can’t be changed after creating the project.") : sourceKind}
                </span>
              </span>
            </> : <span className="text-sm text-ink-soft">{t("Add your manuscript, or pick a sample, to continue.")}</span>}
          </div>
          <span className="hidden items-center gap-2 text-[0.8125rem] text-ink-muted lg:inline-flex">
            <Clock size={14} aria-hidden="true" />{t("Nothing is drawn or charged until you start it.")}
          </span>
          <div className="flex items-center gap-3">
            {step !== "source" && (
              <button type="button" onClick={() => setStep(step === "lettering" ? "details" : "source")} disabled={isPending}
                className="h-12 border border-ink-black/55 px-5 font-meta text-sm font-medium transition-colors hover:border-ink-black hover:bg-sidebar-tint disabled:opacity-50">
                {t("Back")}
              </button>
            )}
            <button type="submit" disabled={continueDisabled}
              className={cn(
                "inline-flex h-12 items-center gap-2.5 px-6 font-meta text-sm font-semibold transition-[translate,box-shadow,background-color] duration-[var(--motion-press)]",
                continueDisabled
                  ? "cursor-not-allowed border border-ink-black/18 bg-surface-variant text-ink-soft"
                  : "border-[2px] border-ink-black bg-hero-red text-bristol shadow-[4px_4px_0_0_var(--color-ink-black)] hover:translate-x-px hover:translate-y-px hover:bg-hero-red-press hover:shadow-[2px_2px_0_0_var(--color-ink-black)] active:translate-x-[3px] active:translate-y-[3px] active:shadow-none",
              )}>
              {isPending ? t("CREATING…") : step !== "lettering" ? t("Continue") : t("Create project")}
              {!isPending && <ArrowRight size={16} strokeWidth={2.25} aria-hidden="true" />}
            </button>
          </div>
        </div>
      </footer>
    </form>
  );
}
