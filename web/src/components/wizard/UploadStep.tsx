import { ErrorNotice } from "../composites/ErrorNotice";
import { useState, useRef, useEffect, useMemo, lazy, Suspense } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import type { ConfigOverrides, ShortStory } from "../../types/api";
import { LANGUAGES, useI18n } from "../../i18n";
import type { LanguageCode } from "../../i18n";
import { useShortStories, useSourcePreview } from "../../api/queries";
import { readManuscriptDraft, writeManuscriptDraft } from "../../lib/manuscriptDraft";
import { LetteringChoice, type LetteringMode } from "./LetteringChoice";
import { SampleLibrary } from "./SampleLibrary";
import { SourcePreviewPanel } from "./SourcePreviewPanel";
import { previewRejected } from "../../lib/sourcePreview";
import { Select } from "../ui/Select";
import { FieldLabel, TextAreaField, TextField } from "../ui/Field";

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
  const [step, setStep] = useState<"source" | "details" | "lettering">("source");
  const [letteringMode, setLetteringMode] = useState<LetteringMode | null>(null);
  const [tab, setTab] = useState<"file" | "library">(() => draftRestored && !initialStoryCode ? "file" : "library");
  const [pastedUrlOrCode, setPastedUrlOrCode] = useState("");
  const [selectedStory, setSelectedStory] = useState<ShortStory | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pasteRef = useRef<HTMLTextAreaElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const previousStep = useRef(step);
  const { data: shortStories } = useShortStories();
  const activeStory = pastedUrlOrCode.trim() ? null
    : selectedStory ?? shortStories?.find((item) => item.code === initialStoryCode) ?? null;
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
  const languageLabel = LANGUAGES.find((item) => item.code === targetLanguage)?.label ?? targetLanguage;

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
    setSourceRevision(nextSourceId());
    setPastedText(text);
    if (!text.trim()) setDraftRestored(false);
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
          <p className="mt-3 font-body text-sm leading-relaxed text-ink-muted">
            {step === "source" ? t("Choose a sample or bring your own manuscript. You decide when generation begins.") : step === "details" ? t("Save your source now. In Story, review the credit estimate before starting analysis.") : t("After your pages are drawn, will you want to change the words?")}
          </p>

          {step === "source" ? (
            <div className="mt-5 space-y-4">
              <div role="group" aria-label={t("SOURCE")} className="grid grid-cols-2 border-b-2 border-ink-black/15">
                {(["library", "file"] as const).map((sourceTab) => (
                  <button key={sourceTab} type="button" aria-pressed={tab === sourceTab} onClick={() => setTab(sourceTab)} className={`min-h-11 px-3 py-3 font-body text-sm font-bold ${tab === sourceTab ? "border-b-[3px] border-ink-black text-ink-black" : "text-ink-muted hover:bg-surface-container"}`}>
                    {sourceTab === "library" ? t("TRY A SAMPLE") : t("YOUR MANUSCRIPT")}
                  </button>
                ))}
              </div>
              {tab === "file" ? (
                <div onPaste={handlePanelPaste}>
                  <button type="button" onClick={() => fileRef.current?.click()}
                    onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => { e.preventDefault(); setDragging(false); const dropped = e.dataTransfer.files[0]; if (dropped) chooseFile(dropped); }}
                    aria-label={file ? t("Replace file {name}", { name: file.name }) : t("DROP FILE OR CLICK TO BROWSE")}
                    className={`flex min-h-32 w-full flex-col items-center justify-center gap-2 border-2 border-dashed p-5 transition-colors ${dragging ? "border-hero-red bg-chip-gold/40" : file && extOk ? "border-archive-sage bg-chip-sage/30" : "border-ink-black bg-pulp-paper"}`}>
                    <Icon name={file && extOk ? "check" : "plus"} size={22} />
                    <span className="max-w-full break-words font-body text-sm font-bold">{file?.name ?? t("DROP FILE OR CLICK TO BROWSE")}</span>
                    <span className="text-sm text-ink-muted">{file ? formatBytes(file.size) : ACCEPTED_LABEL}</span>
                  </button>
                  {file && <div className="mt-2 flex justify-end"><Button type="button" variant="outline" onClick={clearFile}>{t("REMOVE")}</Button></div>}
                  {!extOk && <p role="alert" className="mt-2 text-sm text-hero-red">{t("Unsupported file type. Accepted:")} {ACCEPTED_LABEL}. {t("From another app, copy the text and paste it below.")}</p>}
                  <input ref={fileRef} name="novelFile" type="file" accept={ACCEPT_ATTRIBUTE} className="hidden" onChange={(e) => { const nextFile = e.target.files?.[0]; if (nextFile) chooseFile(nextFile); }} />
                  <div className="my-4 flex items-center gap-3 font-meta text-xs uppercase text-ink-muted" aria-hidden="true">
                    <span className="h-px flex-1 bg-ink-black/15" />{t("OR")}<span className="h-px flex-1 bg-ink-black/15" />
                  </div>
                  <FieldLabel htmlFor="manuscript-text">{t("Paste your text")}</FieldLabel>
                  <TextAreaField id="manuscript-text" ref={pasteRef} rows={6} value={pastedText} onChange={(e) => changePastedText(e.target.value)}
                    placeholder={t("Paste a chapter, a story, or the whole book.")} aria-describedby="manuscript-text-count" className="max-h-72 font-body" />
                  <div className="mt-1 flex items-start justify-between gap-3">
                    <p className="text-xs text-ink-muted">
                      {draftRestored && <>{t("Restored the text you pasted last time.")} <button type="button" className="underline" onClick={() => changePastedText("")}>{t("Clear")}</button></>}
                    </p>
                    <p id="manuscript-text-count" className="shrink-0 font-meta text-xs text-ink-muted" aria-live="polite">
                      {pastedWords ? t("{count, plural, one {# word} other {# words}}", { count: pastedWords }) : ""}
                    </p>
                  </div>
                  <p className="mt-2 font-body text-sm text-ink-muted">{t("Bring the complete book. A long manuscript is split into parts at chapter breaks; Part 1 is analyzed first, and you start each later part when you're ready.")}</p>
                </div>
              ) : (
                <>
                  <SampleLibrary
                    selectedCode={activeStory?.code}
                    onSelect={(story) => { setSelectedStory(story); setPastedUrlOrCode(""); setName(story.title); }}
                    onReadAndSelect={(story) => { setSelectedStory(story); setPastedUrlOrCode(""); setName(story.title); setStep("details"); }}
                  />
                  <details className="bg-surface-container px-4">
                    <summary className="min-h-11 cursor-pointer py-3 font-meta text-xs uppercase">{t("HAVE A STORY CODE OR LINK?")}</summary>
                    <div className="pb-4">
                      <FieldLabel htmlFor="story-url">{t("Library of Short Stories code or URL")}</FieldLabel>
                      <TextField id="story-url" type="text" value={pastedUrlOrCode} onChange={(e) => {
                        const value = e.target.value;
                        setPastedUrlOrCode(value);
                        setSelectedStory(null);
                        const code = value.match(/onlinereader\/([a-zA-Z0-9_-]+)/)?.[1] ?? value.split("/").pop() ?? "";
                        setName(code.replace(/[^a-zA-Z0-9]+/g, " ").trim().replace(/\b\w/g, (c) => c.toUpperCase()));
                      }} placeholder={t("e.g. the-open-window")} />
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
                {previewFile && <SourcePreviewPanel preview={preview} />}
                <p className="mt-3 text-sm">{languageLabel}</p>
                <p className="mt-2 text-sm leading-relaxed text-ink-muted">{t("First review after analysis: your characters, places, story outline, and proposed adaptation brief.")}</p>
              </div>
              {activeStory?.rights_note && <p className="bg-chip-gold/45 p-4 text-sm leading-6">{t(activeStory.rights_note)}</p>}
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
          {error && <ErrorNotice error={error} operation="upload" />}
          <div className="mb-3 min-w-0" aria-live="polite">
            <p className="truncate font-body text-sm font-bold">{sourceReady ? (step !== "source" ? name || sourceTitle : sourceTitle) : t("Choose a source to continue")}</p>
            {step === "lettering" && <p className="mt-1 text-sm"><strong>{t(letteringMode === "integrated" ? "Integrated lettering" : letteringMode === "editable" ? "Editable lettering" : "Select a lettering option to create your project.")}</strong>{letteringMode && <span className="text-ink-muted"> · {t("Can’t be changed after creating the project")}</span>}</p>}
            <p className="mt-1 text-xs leading-relaxed text-ink-muted">{t("Saves your source only. No generation starts now.")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" size="lg" disabled={isPending || !sourceReady || (step !== "source" && !name.trim()) || (step === "lettering" && !letteringMode) || (step === "details" && sourceBlocked)}>{isPending ? t("CREATING…") : step !== "lettering" ? t("CONTINUE") : t("CREATE PROJECT")}</Button>
            {step !== "source" && <Button type="button" variant="outline" onClick={() => setStep(step === "lettering" ? "details" : "source")} disabled={isPending}>{t("BACK")}</Button>}
            {onCancel && <Button type="button" variant="outline" onClick={onCancel} disabled={isPending}>{t("CANCEL")}</Button>}
          </div>
        </footer>
      </Card>
    </form>
  );
}
