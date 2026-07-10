import { useState, useRef, useMemo } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { SectionLabel } from "../SectionLabel";
import type { ConfigOverrides, ShortStory } from "../../types/api";
import { LANGUAGES, useI18n } from "../../i18n";
import type { LanguageCode } from "../../i18n";
import { useShortStories } from "../../api/queries";
import { Select } from "../ui/Select";
import { FieldLabel, TextField } from "../ui/Field";
import { browseStories, deriveGenres, genreLabel, SORT_OPTIONS, type SortKey } from "../../lib/storyBrowser";

interface UploadStepProps {
  onSubmit: (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  onSubmitImport: (urlOrCode: string, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  isPending: boolean;
  error: string | null;
  onCancel?: () => void;
}

const ACCEPTED = [".txt", ".epub", ".pdf"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

type RenderPreset = "fast_draft" | "balanced" | "high_quality";

interface CreditRange {
  min: number;
  max: number;
}

function estimateProjectCredits({
  fileSizeBytes,
  renderPreset,
  devMode,
  maxPanelsPerScene,
}: {
  fileSizeBytes: number;
  renderPreset: RenderPreset;
  devMode: boolean;
  maxPanelsPerScene: number;
}): CreditRange {
  // Estimate scenes from file size (~10 KB per scene)
  const estimatedScenes = devMode
    ? 1
    : Math.max(1, Math.min(150, Math.round(fileSizeBytes / 10_000)));

  // Panels: scenes × avg fill factor (scenes rarely hit the max)
  const estimatedPanels = Math.round(estimatedScenes * maxPanelsPerScene * 0.7);

  let imageCostPerPanel =
    renderPreset === "high_quality" ? 0.075 : renderPreset === "balanced" ? 0.042 : 0.015;
  if (devMode) imageCostPerPanel *= 0.6; // dev mode downscales image quality

  // Text-stage costs (USD)
  const extractCost = Math.max(0.01, fileSizeBytes * 0.000003); // ~$0.003/KB
  const castCost = 0.05; // character & location reference images
  const perSceneText = 0.035; // adapt + plan per scene
  const textCostUsd = extractCost + castCost + estimatedScenes * perSceneText;
  const imageCostUsd = estimatedPanels * imageCostPerPanel;
  const totalUsd = textCostUsd + imageCostUsd;

  // 100 credits per $1 (default rate matches backend PULP_CREDITS_PER_PROVIDER_USD)
  const base = Math.ceil(totalUsd * 100);
  return {
    min: Math.max(10, Math.round(base * 0.75)),
    max: Math.round(base * 1.5),
  };
}

function formatCreditRange(range: CreditRange): string {
  const fmt = (n: number) =>
    n >= 10_000 ? `${(n / 1000).toFixed(0)}k` : n.toLocaleString();
  return `~${fmt(range.min)}–${fmt(range.max)}`;
}

export function UploadStep({ onSubmit, onSubmitImport, isPending, error, onCancel }: UploadStepProps) {
  const { language, t } = useI18n();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState<LanguageCode>(language);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [step, setStep] = useState<"source" | "details">("source");
  const devMode = false;
  const [renderPreset, setRenderPreset] = useState<RenderPreset>("balanced");
  const fileRef = useRef<HTMLInputElement>(null);

  // Lead with the sample-story library — "try a sample story" is the
  // zero-friction first success; uploading your own novel is the second
  // project, not the first.
  const [tab, setTab] = useState<"file" | "library">("library");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("recommended");
  const [selectedGenres, setSelectedGenres] = useState<string[]>([]);
  const [pastedUrlOrCode, setPastedUrlOrCode] = useState("");
  const [selectedStory, setSelectedStory] = useState<ShortStory | null>(null);

  const { data: shortStories } = useShortStories();

  const allGenres = useMemo(() => deriveGenres(shortStories ?? []), [shortStories]);
  const visibleStories = useMemo(
    () =>
      browseStories(shortStories ?? [], {
        search: searchQuery,
        genres: selectedGenres,
        sort: sortBy,
      }),
    [shortStories, searchQuery, selectedGenres, sortBy],
  );
  const filtersActive = searchQuery.trim() !== "" || selectedGenres.length > 0;

  function toggleGenre(genre: string) {
    setSelectedGenres((prev) =>
      prev.includes(genre) ? prev.filter((g) => g !== genre) : [...prev, genre],
    );
  }

  function clearFilters() {
    setSearchQuery("");
    setSelectedGenres([]);
  }

  function chooseFile(nextFile: File) {
    setFile(nextFile);
    if (!name.trim()) setName(nextFile.name.replace(/\.[^.]+$/, ""));
  }

  const ext = file ? "." + file.name.split(".").pop()?.toLowerCase() : "";
  const extOk = !file || ACCEPTED.includes(ext);
  const presetPanelsPerScene =
    devMode || renderPreset === "fast_draft" ? 6 : renderPreset === "high_quality" ? 10 : 8;
  const sourceReady = tab === "file"
    ? Boolean(file && extOk)
    : Boolean(selectedStory || pastedUrlOrCode.trim());

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (step === "source") {
      if (sourceReady) setStep("details");
      return;
    }
    if (tab === "file") {
      if (!file || !name.trim() || !extOk) return;
    } else {
      if (!selectedStory && !pastedUrlOrCode.trim()) return;
      if (!name.trim()) return;
    }

    const overrides: Partial<ConfigOverrides> = { target_language: targetLanguage };

    // Dev mode: force fast preset and dev overrides.
    if (devMode) {
      overrides.dev_mode = true;
      overrides.quality_preset = "fast";
      overrides.dev_image_scale = 0.6;
      overrides.dev_image_steps = 8;
      overrides.dev_image_concurrency = 5;
      overrides.max_panels_per_scene = 6;
      overrides.max_panels_per_page = 6;
    } else {
      // Normal quality preset handling.
      if (renderPreset === "fast_draft") {
        overrides.quality_preset = "fast";
        overrides.dev_mode = false;
        overrides.max_panels_per_scene = 6;
        overrides.max_panels_per_page = 6;
      } else if (renderPreset === "high_quality") {
        overrides.quality_preset = "quality";
        overrides.dev_mode = false;
        overrides.max_panels_per_scene = 10;
        overrides.max_panels_per_page = 5;
      } else {
        overrides.quality_preset = "balanced";
        overrides.dev_mode = false;
        overrides.max_panels_per_scene = 8;
        overrides.max_panels_per_page = 6;
      }
    }

    if (tab === "file") {
      onSubmit(file!, name.trim(), overrides);
    } else {
      const importSource = selectedStory ? selectedStory.code : pastedUrlOrCode.trim();
      onSubmitImport(importSource, name.trim(), overrides);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <Card className="p-5 md:p-6">
        <div className="flex items-center justify-between gap-3">
          <SectionLabel tone="red">{t("NEW PRODUCTION")}</SectionLabel>
          <span className="font-meta text-[0.58rem] font-bold uppercase tracking-[0.08em] text-ink-muted">
            {step === "source" ? t("STEP 1 OF 2") : t("STEP 2 OF 2")}
          </span>
        </div>
        <h1 className="mt-4 font-display text-[2.4rem] font-black uppercase leading-[0.9] tracking-[-0.035em] text-ink-black sm:text-[3rem]">
          {step === "source" ? t("CHOOSE A STARTING POINT") : t("NAME AND START")}
        </h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          {step === "source"
            ? t("Try a sample for the fastest tour, or bring your own manuscript.")
            : t("Scenewright starts by finding the people, places, and shape of your story.")}
        </p>

        {step === "source" && <div className="mt-6 flex border-b-[2px] border-ink-black/12">
          <button
            type="button"
            onClick={() => setTab("library")}
            className={`min-h-11 px-4 py-2 font-body text-[0.76rem] font-bold transition-colors ${
              tab === "library"
                ? "border-b-[3px] border-hero-red text-ink-black"
                : "text-ink-muted hover:text-ink-black"
            }`}
          >
            {t("TRY A SAMPLE")}
          </button>
          <button
            type="button"
            onClick={() => setTab("file")}
            className={`min-h-11 px-4 py-2 font-body text-[0.76rem] font-bold transition-colors ${
              tab === "file"
                ? "border-b-[3px] border-hero-red text-ink-black"
                : "text-ink-muted hover:text-ink-black"
            }`}
          >
            {t("UPLOAD MANUSCRIPT")}
          </button>
        </div>}

        <div className="mt-6 space-y-4">
          {step === "details" && (
            <div className="flex items-center justify-between gap-4 bg-surface-container px-4 py-3">
              <div className="min-w-0">
                <div className="font-meta text-[0.56rem] font-bold uppercase tracking-[0.08em] text-ink-muted">{t("SOURCE")}</div>
                <div className="truncate font-body text-[0.85rem] font-bold text-ink-black">
                  {tab === "file" ? file?.name : selectedStory?.title ?? pastedUrlOrCode}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setStep("source")}
                className="min-h-9 shrink-0 font-meta text-[0.56rem] uppercase tracking-[0.14em] text-hero-red hover:underline"
              >
                {t("CHANGE")}
              </button>
            </div>
          )}

          {step === "details" && <div>
            <FieldLabel htmlFor="project-name">{t("PROJECT NAME")}</FieldLabel>
            <TextField
              id="project-name"
              name="projectName"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. The Last Question"
              autoComplete="off"
              required
            />
          </div>}

          {step === "source" && (tab === "file" ? (
            <div>
              <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                {t("NOVEL FILE")}
              </label>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const dropped = e.dataTransfer.files[0];
                  if (dropped) chooseFile(dropped);
                }}
                aria-label={t("DROP FILE OR CLICK TO BROWSE")}
                className={`flex min-h-[120px] w-full cursor-pointer flex-col items-center justify-center border-[2px] border-dashed px-4 py-6 transition-colors ${
                  file && extOk
                    ? "border-archive-sage bg-chip-sage/40"
                    : !extOk
                      ? "border-hero-red bg-chip-red/30"
                      : "border-ink-black bg-pulp-paper hover:bg-ghost-shadow/30"
                }`}
              >
                {file ? (
                  <>
                    {extOk && (
                      <div className="mb-2 inline-flex h-8 w-8 items-center justify-center border-[2px] border-ink-black bg-archive-sage text-bristol shadow-paper-sm">
                        <Icon name="check" size={14} />
                      </div>
                    )}
                    <div className="font-display text-[1rem] font-bold tracking-[-0.04em]">
                      {file.name}
                    </div>
                    <div className="mt-1 font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/50">
                      {formatBytes(file.size)}
                    </div>
                    {!extOk && (
                      <div className="mt-2 text-[0.78rem] text-hero-red">
                        {t("Unsupported file type. Accepted:")} {ACCEPTED.join(", ")}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <Icon name="plus" size={22} className="text-ink-black/40" />
                    <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50">
                      {t("DROP FILE OR CLICK TO BROWSE")}
                    </div>
                    <div className="mt-1 text-[0.72rem] text-ink-black/40">
                      .txt, .epub, .pdf
                    </div>
                  </>
                )}
              </button>
              <input
                ref={fileRef}
                name="novelFile"
                type="file"
                accept=".txt,.epub,.pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) chooseFile(f);
                }}
              />
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  {t("SHORT STORY LIBRARY")}
                </label>
                <p className="text-[0.78rem] leading-relaxed text-ink-black/60 mb-2">
                  {t("Select a story from the library or paste a URL below to import it.")}
                </p>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <TextField
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder={t("Search stories by title, author, or genre...")}
                      className="pl-8"
                    />
                    <div className="absolute left-2.5 top-3.5 text-ink-muted">
                      <Icon name="search" size={14} />
                    </div>
                  </div>
                  <Select
                    aria-label={t("Sort stories")}
                    value={sortBy}
                    onValueChange={(value) => setSortBy(value as SortKey)}
                    options={SORT_OPTIONS.map((option) => ({
                      value: option.value,
                      label: t(option.label),
                    }))}
                    className="shrink-0"
                  />
                </div>

                {allGenres.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    {allGenres.map((genre) => {
                      const active = selectedGenres.includes(genre);
                      return (
                        <button
                          key={genre}
                          type="button"
                          onClick={() => toggleGenre(genre)}
                          aria-pressed={active}
                      className={`border px-2 py-1 font-meta text-[10px] uppercase tracking-wide transition-colors ${
                            active
                              ? "border-ink-black bg-ink-black text-bristol"
                              : "border-transparent bg-ink-black/5 text-ink-black/55 hover:border-ink-black/30"
                          }`}
                        >
                          {genreLabel(genre)}
                        </button>
                      );
                    })}
                  </div>
                )}

                <div className="mt-2 flex min-h-[16px] items-center justify-between">
                  <span className="font-meta text-[10px] tracking-[0.14em] text-ink-black/45 tabular-nums">
                    {visibleStories.length}
                    {filtersActive ? ` / ${(shortStories ?? []).length}` : ""}
                  </span>
                  {filtersActive && (
                    <button
                      type="button"
                      onClick={clearFilters}
                      className="font-meta text-[10px] uppercase tracking-[0.14em] text-hero-red hover:underline"
                    >
                      {t("Clear")}
                    </button>
                  )}
                </div>

                <div className="mt-2 max-h-[180px] overflow-y-auto border-[2px] border-ink-black bg-pulp-paper divide-y divide-ink-black/10">
                  {visibleStories.length === 0 ? (
                    <div className="p-4 text-center text-xs text-ink-black/40 font-meta">
                      {t("NO STORIES FOUND")}
                    </div>
                  ) : (
                    visibleStories.map((story) => {
                      const isSelected = selectedStory?.code === story.code;
                      return (
                        <button
                          key={story.code}
                          type="button"
                          onClick={() => {
                            setSelectedStory(story);
                            setPastedUrlOrCode("");
                            setName(story.title);
                          }}
                          className={`w-full text-left p-3 transition-colors text-xs flex justify-between items-center ${
                            isSelected
                              ? "bg-chip-gold/30 font-bold"
                              : "hover:bg-bristol/30"
                          }`}
                        >
                          <div className="flex-1 pr-4">
                            <div className="font-display font-bold text-sm text-ink-black">
                              {story.title}
                            </div>
                            <div className="text-ink-black/50 mt-0.5">
                              by {story.author}
                            </div>
                            <div className="mt-1 flex flex-wrap gap-1">
                              {story.genres.map((g: string) => (
                                <span key={g} className="bg-ink-black/5 px-1.5 py-0.5 font-meta text-[9px] uppercase text-ink-black/60">
                                  {g}
                                </span>
                              ))}
                            </div>
                          </div>
                          <div className="text-right whitespace-nowrap">
                            <div className="font-meta text-[10px] text-ink-black/60 uppercase">
                              {story.words.toLocaleString()} {t("Word count")}
                            </div>
                            <div className="mt-0.5 font-meta text-[10px] text-ink-black/45">
                              {formatCreditRange(estimateProjectCredits({
                                fileSizeBytes: story.words * 6,
                                renderPreset: devMode ? "fast_draft" : renderPreset,
                                devMode,
                                maxPanelsPerScene: presetPanelsPerScene,
                              }))} credits
                            </div>
                            {story.rating && (
                              <div className="mt-0.5 text-narrator-gold flex items-center justify-end gap-0.5">
                                {"★".repeat(story.rating)}
                              </div>
                            )}
                          </div>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>

              <details className="bg-surface-container px-4 py-3">
                <summary className="cursor-pointer font-meta text-[0.56rem] uppercase tracking-[0.14em] text-ink-black/65">
                  {t("USE ANOTHER SOURCE")}
                </summary>
                <div className="mt-3">
                  <FieldLabel>{t("PASTE URL OR CODE")}</FieldLabel>
                  <TextField
                    type="text"
                    value={pastedUrlOrCode}
                    onChange={(e) => {
                      setPastedUrlOrCode(e.target.value);
                      setSelectedStory(null);
                      const codeMatch = e.target.value.match(/onlinereader\/([a-zA-Z0-9_-]+)/);
                      const code = codeMatch ? codeMatch[1] : e.target.value.split("/").pop() || "";
                      if (code && code.trim()) {
                        const nameSug = code
                          .replace(/[^a-zA-Z0-9]+/g, " ")
                          .trim()
                          .replace(/\b\w/g, (c: string) => c.toUpperCase());
                        if (nameSug) setName(nameSug);
                      }
                    }}
                    placeholder="e.g. story URL or library code"
                  />
                </div>
              </details>
            </div>
          ))}

          {step === "details" && showAdvanced && <div>
            <FieldLabel>
              {t("OUTPUT LANGUAGE")}
            </FieldLabel>
            <Select
              aria-label={t("OUTPUT LANGUAGE")}
              value={targetLanguage}
              onValueChange={(value) => setTargetLanguage(value as LanguageCode)}
              options={LANGUAGES.map((item) => ({ value: item.code, label: item.label }))}
              className="w-full"
            />
            <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
              {t("Controls generated dialogue, narration, style suggestions, and prompt artifacts.")}
            </p>
          </div>}

        </div>

        {/* Advanced config disclosure */}
        {step === "details" && <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          aria-expanded={showAdvanced}
          className="mt-5 flex w-full items-center justify-between gap-3 border-[2px] border-ink-black bg-bristol px-4 py-3 text-left transition-colors hover:bg-ghost-shadow/30"
        >
          <div>
            <div className="font-display text-[0.95rem] font-bold uppercase leading-none tracking-[-0.02em] text-ink-black">
              {t("PRODUCTION SETTINGS")}
            </div>
            <div className="mt-1 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55">
              {targetLanguage.toUpperCase()} · {t("Balanced by default")}
            </div>
          </div>
          <span aria-hidden="true" className="font-meta text-[0.7rem] text-ink-black/60">
            {showAdvanced ? "▼" : "▶"}
          </span>
        </button>}

        {/* Credit preview strip */}
        {step === "details" && (() => {
          const estimate = file || (tab === "library" && (selectedStory || pastedUrlOrCode.trim()))
            ? estimateProjectCredits({
                fileSizeBytes: file
                  ? file.size
                  : selectedStory
                    ? selectedStory.words * 6 // Average 6 bytes per word
                    : 15000, // Fallback default size (~15KB)
                renderPreset: devMode ? "fast_draft" : renderPreset,
                devMode,
                maxPanelsPerScene: presetPanelsPerScene,
              })
            : null;
          
          const sceneCount = file
            ? Math.max(1, Math.round(file.size / 10000))
            : selectedStory
              ? Math.max(1, Math.round((selectedStory.words * 6) / 10000))
              : 1;

          return (
            <div className="mt-3 flex items-center justify-between gap-3 border-[2px] border-ink-black bg-chip-gold px-4 py-2 shadow-ink-sm">
              <div>
                <div className="font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-muted">
                  {t("PROJECT RANGE")}
                </div>
                <div className="mt-0.5 font-display text-[1.05rem] font-bold leading-none tracking-[-0.03em] text-ink-black tabular-nums">
                  {estimate ? `${formatCreditRange(estimate)} ${t("credits")}` : t("Upload a file or select a story to estimate")}
                </div>
              </div>
              <div className="text-right font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55">
                {estimate ? (
                  <>
                    {devMode ? "1 scene (dev)" : `about ${sceneCount} scene${sceneCount !== 1 ? "s" : ""}`}
                    <br />
                    about {presetPanelsPerScene} {t("panels per scene")}
                  </>
                ) : (
                  <>about {presetPanelsPerScene} {t("panels per scene")}</>
                )}
              </div>
            </div>
          );
        })()}

        {step === "details" && showAdvanced && (
          <div className="mt-4 space-y-3 border-t-[2px] border-ink-black pt-4">
            <div>
              <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                {t("GENERATION QUALITY")}
              </label>
              <Select
                aria-label={t("GENERATION QUALITY")}
                value={devMode ? "fast_draft" : renderPreset}
                onValueChange={(value) => setRenderPreset(value as RenderPreset)}
                disabled={devMode}
                options={[
                  { value: "fast_draft", label: `Fast draft${devMode ? " (locked — dev mode)" : ""}` },
                  { value: "balanced", label: "Balanced (recommended)" },
                  { value: "high_quality", label: "High quality" },
                ]}
                className="w-full"
              />
              <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
                {devMode
                  ? "Locked to fast in dev mode."
                  : "Fast draft lowers credit use and latency. Balanced is safe default. High quality increases runtime and credits used."}
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-4 text-[0.82rem] text-hero-red" role="alert">{error}</div>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-3">
          {step === "source" ? (
            <Button type="submit" size="lg" disabled={!sourceReady}>
              {t("CONTINUE")} →
            </Button>
          ) : (
            <>
              <Button type="submit" size="lg" disabled={isPending || !name.trim() || !sourceReady}>
                {isPending ? t("CREATING…") : t("START PRODUCTION")}
              </Button>
              <Button type="button" size="lg" variant="outline" onClick={() => setStep("source")}>
                ← {t("BACK")}
              </Button>
            </>
          )}
          {onCancel && (
            <Button
              type="button"
              size="lg"
              variant="outline"
              onClick={onCancel}
            >
              {t("CANCEL")}
            </Button>
          )}
        </div>
      </Card>
    </form>
  );
}
