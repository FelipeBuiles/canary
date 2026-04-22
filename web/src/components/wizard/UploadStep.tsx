import { useState, useRef } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { SectionLabel } from "../SectionLabel";
import type { ConfigOverrides } from "../../types/api";
import { LANGUAGES, useI18n } from "../../i18n";
import type { LanguageCode } from "../../i18n";

interface UploadStepProps {
  onSubmit: (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  isPending: boolean;
  error: string | null;
}

const ACCEPTED = [".txt", ".epub", ".pdf"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const PANEL_COST_USD = 0.07;
const DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview";
const IMAGE_MODEL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: DEFAULT_IMAGE_MODEL, label: "Gemini 3 Pro Image" },
  { value: "gemini-2.5-flash-image", label: "Gemini 2.5 Flash Image" },
  { value: "gemini-2.5-pro-image", label: "Gemini 2.5 Pro Image" },
  { value: "gemini-3.1-flash-image-preview", label: "Gemini 3.1 Flash Image" },
  { value: "gemini-3.1-pro-image-preview", label: "Gemini 3.1 Pro Image" },
  { value: "gpt-image-1.5", label: "OpenAI GPT Image 1.5" },
  { value: "gpt-image-2", label: "OpenAI GPT Image 2" },
];
type RenderPreset = "fast_draft" | "balanced" | "high_quality";

export function UploadStep({ onSubmit, isPending, error }: UploadStepProps) {
  const { language, t } = useI18n();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState<LanguageCode>(language);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showExpert, setShowExpert] = useState(false);
  const [renderPreset, setRenderPreset] = useState<RenderPreset>("balanced");
  const [theme, setTheme] = useState("auto");
  const [imageModel, setImageModel] = useState(DEFAULT_IMAGE_MODEL);
  const [imageWidth, setImageWidth] = useState(1024);
  const [imageHeight, setImageHeight] = useState(1024);
  const [imageSteps, setImageSteps] = useState(28);
  const [imageQuality, setImageQuality] = useState<"auto" | "low" | "medium" | "high">("auto");
  const [maxPanelsPerScene, setMaxPanelsPerScene] = useState(8);
  const [maxPanelsPerPage, setMaxPanelsPerPage] = useState(6);
  const [styleTemplate, setStyleTemplate] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const ext = file ? "." + file.name.split(".").pop()?.toLowerCase() : "";
  const extOk = !file || ACCEPTED.includes(ext);
  const isTogetherModel = imageModel.includes("/");
  const isOpenAIModel = imageModel.startsWith("gpt-image-");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !name.trim() || !extOk) return;
    const overrides: Partial<ConfigOverrides> = { target_language: targetLanguage };

    // Persist model choice if changed from default.
    if (imageModel !== DEFAULT_IMAGE_MODEL) overrides.image_model = imageModel;

    // Presets: keep common flows safe and avoid exposing low-level footguns by default.
    if (renderPreset === "fast_draft") {
      overrides.dev_mode = true;
      overrides.dev_image_scale = 0.6;
      overrides.dev_image_steps = 8;
      overrides.dev_image_concurrency = 5;
      overrides.max_panels_per_scene = 6;
      overrides.max_panels_per_page = 6;
      if (isTogetherModel) {
        overrides.image_steps = 8;
      }
      if (isOpenAIModel) {
        overrides.image_quality = "low";
      }
    } else if (renderPreset === "high_quality") {
      overrides.dev_mode = false;
      overrides.max_panels_per_scene = 10;
      overrides.max_panels_per_page = 5;
      if (isTogetherModel) {
        overrides.image_steps = 36;
      }
      if (isOpenAIModel) {
        overrides.image_quality = "high";
      }
    } else {
      overrides.dev_mode = false;
      overrides.max_panels_per_scene = 8;
      overrides.max_panels_per_page = 6;
      if (isTogetherModel) {
        overrides.image_steps = 24;
      }
      if (isOpenAIModel) {
        overrides.image_quality = "medium";
      }
    }

    // Advanced manual overrides are opt-in and override presets.
    if (showAdvanced) {
      if (theme !== "auto") overrides.comic_theme = theme;
      if (styleTemplate.trim()) overrides.style_template = styleTemplate.trim();
      if (showExpert) {
        if (imageWidth !== 1024) overrides.image_width = imageWidth;
        if (imageHeight !== 1024) overrides.image_height = imageHeight;
        if (isTogetherModel && imageSteps !== 28) overrides.image_steps = imageSteps;
        if (isOpenAIModel && imageQuality !== "auto") overrides.image_quality = imageQuality;
        if (maxPanelsPerScene !== 8) overrides.max_panels_per_scene = maxPanelsPerScene;
        if (maxPanelsPerPage !== 6) overrides.max_panels_per_page = maxPanelsPerPage;
      }
    }
    onSubmit(file, name.trim(), overrides);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="red">{t("NEW PRODUCTION")}</SectionLabel>
        <h1 className="mt-4 display-headline">{t("CREATE PROJECT")}</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          {t("Upload your novel file and the pipeline will take it from there — extracting characters, drawing panels, and assembling pages.")}
        </p>

        <div className="mt-6 space-y-4">
          <div>
            <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
              {t("PROJECT NAME")}
            </label>
            <input
              name="projectName"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. The Last Question"
              autoComplete="off"
              className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm font-body focus:outline-none focus:ring-2 focus:ring-hero-red"
              required
            />
          </div>

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
                if (dropped) setFile(dropped);
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
                    <div className="mb-2 inline-flex h-7 w-7 items-center justify-center rounded-full bg-archive-sage text-bristol">
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
                if (f) setFile(f);
              }}
            />
          </div>

          <div>
            <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
              {t("OUTPUT LANGUAGE")}
            </label>
            <select
              name="targetLanguage"
              value={targetLanguage}
              onChange={(e) => setTargetLanguage(e.target.value as LanguageCode)}
              className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
            >
              {LANGUAGES.map((item) => (
                <option key={item.code} value={item.code}>{item.label}</option>
              ))}
            </select>
            <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
              {t("Controls generated dialogue, narration, style suggestions, and prompt artifacts.")}
            </p>
          </div>
        </div>

        {/* Advanced config disclosure */}
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          aria-expanded={showAdvanced}
          className="mt-5 flex w-full items-center justify-between gap-3 border-[2px] border-ink-black bg-bristol px-4 py-3 text-left transition-colors hover:bg-ghost-shadow/30"
        >
          <div>
            <div className="font-display text-[0.95rem] font-bold uppercase leading-none tracking-[-0.02em] text-ink-black">
              {t("ADVANCED CONFIGURATION")}
            </div>
            <div className="mt-1 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55">
              {t("Model selection, panels per scene, style preset")}
            </div>
          </div>
          <span aria-hidden="true" className="font-meta text-[0.7rem] text-ink-black/60">
            {showAdvanced ? "▼" : "▶"}
          </span>
        </button>

        {/* Cost preview strip */}
        <div className="mt-3 flex items-center justify-between gap-3 border-[2px] border-ink-black bg-chip-gold px-4 py-2 shadow-ink-sm">
          <div>
            <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60">
              {t("ESTIMATED GENERATION COST")}
            </div>
            <div className="mt-0.5 font-display text-[1.05rem] font-bold leading-none tracking-[-0.03em] text-ink-black tabular-nums">
              ~${(maxPanelsPerScene * PANEL_COST_USD * 0.5).toFixed(2)}–${(maxPanelsPerScene * PANEL_COST_USD * 0.75).toFixed(2)}
            </div>
          </div>
          <div className="text-right font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55">
            {maxPanelsPerScene} {t("panels/scene")}
          </div>
        </div>

        {showAdvanced && (
          <div className="mt-4 space-y-3 border-t-[2px] border-ink-black pt-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  {t("COMIC THEME")}
                </label>
                <select
                  name="comicTheme"
                  value={theme}
                  onChange={(e) => setTheme(e.target.value)}
                  className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
                >
                  <option value="auto">auto</option>
                  <option value="default">default</option>
                  <option value="noir">noir</option>
                  <option value="manga">manga</option>
                  <option value="vintage">vintage</option>
                  <option value="painted">painted</option>
                </select>
              </div>
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  {t("IMAGE MODEL")}
                </label>
                <select
                  name="imageModel"
                  value={imageModel}
                  onChange={(e) => setImageModel(e.target.value)}
                  className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
                >
                  {IMAGE_MODEL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
                  Selected model is persisted to the project config and used by Stage 6.
                </p>
              </div>
            </div>
            <div>
              <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                {t("QUALITY PRESET")}
              </label>
              <select
                name="renderPreset"
                value={renderPreset}
                onChange={(e) => setRenderPreset(e.target.value as RenderPreset)}
                className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
              >
                <option value="fast_draft">Fast draft</option>
                <option value="balanced">Balanced (recommended)</option>
                <option value="high_quality">High quality</option>
              </select>
              <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
                Fast draft lowers cost/latency. Balanced is safe default. High quality increases runtime and spend.
              </p>
            </div>
            <div>
              <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                {t("STYLE TEMPLATE")}
              </label>
              <textarea
                name="styleTemplate"
                value={styleTemplate}
                onChange={(e) => setStyleTemplate(e.target.value)}
                placeholder={t("Leave empty for default style. Override to set visual identity of the comic.")}
                rows={3}
                className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm resize-y"
              />
            </div>

            <button
              type="button"
              onClick={() => setShowExpert(!showExpert)}
              className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50 hover:text-ink-black transition-colors"
            >
              {showExpert ? "▼" : "▶"} EXPERT OVERRIDES (OPTIONAL)
            </button>

            {showExpert && (
              <div className="space-y-3 border-t-[2px] border-ink-black/30 pt-3">
                <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
                  <div>
                    <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                      {t("WIDTH")}
                    </label>
                    <input name="imageWidth" type="number" value={imageWidth} onChange={(e) => setImageWidth(Number(e.target.value))} min={256} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                      {t("HEIGHT")}
                    </label>
                    <input name="imageHeight" type="number" value={imageHeight} onChange={(e) => setImageHeight(Number(e.target.value))} min={256} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                      {t("PANELS/SCENE")}
                    </label>
                    <input name="maxPanelsPerScene" type="number" value={maxPanelsPerScene} onChange={(e) => setMaxPanelsPerScene(Number(e.target.value))} min={1} max={20} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
                  </div>
                  <div>
                    <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                      {t("PANELS/PAGE")}
                    </label>
                    <input name="maxPanelsPerPage" type="number" value={maxPanelsPerPage} onChange={(e) => setMaxPanelsPerPage(Number(e.target.value))} min={1} max={12} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
                  </div>
                </div>

                {isTogetherModel && (
                  <div>
                    <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                      {t("STEPS")}
                    </label>
                    <input name="imageSteps" type="number" value={imageSteps} onChange={(e) => setImageSteps(Number(e.target.value))} min={1} max={50} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
                    <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
                      Used by diffusion-style models (Together): higher is usually cleaner but slower.
                    </p>
                  </div>
                )}

                {isOpenAIModel && (
                  <div>
                    <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                      IMAGE QUALITY (OPENAI)
                    </label>
                    <select
                      name="imageQuality"
                      value={imageQuality}
                      onChange={(e) => setImageQuality(e.target.value as "auto" | "low" | "medium" | "high")}
                      className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
                    >
                      <option value="auto">auto</option>
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </select>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="mt-4 text-[0.82rem] text-hero-red" role="alert">{error}</div>
        )}

        <div className="mt-6">
          <Button
            type="submit"
            size="lg"
            disabled={!file || !name.trim() || !extOk || isPending}
          >
            {isPending ? t("CREATING…") : t("CREATE PROJECT")}
          </Button>
        </div>
      </Card>
    </form>
  );
}
