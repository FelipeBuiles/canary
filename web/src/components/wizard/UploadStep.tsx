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
  onCancel?: () => void;
}

const ACCEPTED = [".txt", ".epub", ".pdf"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

type ImageProvider = NonNullable<ConfigOverrides["image_provider"]>;

const DEFAULT_IMAGE_MODEL = "image-balanced";
const IMAGE_MODEL_OPTIONS: Array<{ value: string; label: string; provider: ImageProvider }> = [
  { value: "image-fast", label: "Fast image model", provider: "gemini" },
  { value: DEFAULT_IMAGE_MODEL, label: "Balanced image model", provider: "openai" },
  { value: "image-quality", label: "Quality image model", provider: "gemini" },
];

function _defaultProviderForModel(model: string): ImageProvider {
  const value = model.trim().toLowerCase();
  if (value === "image-balanced") return "openai";
  if (value === "image-fast" || value === "image-quality") return "gemini";
  if (value.startsWith("gpt-image-") || value === "chatgpt-image-latest") return "openai";
  if (value.includes("/")) return "together";
  return "gemini";
}

type RenderPreset = "fast_draft" | "balanced" | "high_quality";

interface CreditRange {
  min: number;
  max: number;
}

function estimateProjectCredits({
  fileSizeBytes,
  imageModel,
  renderPreset,
  devMode,
  maxPanelsPerScene,
}: {
  fileSizeBytes: number;
  imageModel: string;
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

  // Image cost per panel in USD, keyed by model + preset
  const modelLower = imageModel.toLowerCase();
  let imageCostPerPanel: number;
  if (modelLower === "image-balanced" || modelLower.includes("gpt-image")) {
    imageCostPerPanel =
      renderPreset === "high_quality" ? 0.28 : renderPreset === "balanced" ? 0.042 : 0.011;
  } else if (modelLower === "image-fast" || modelLower === "image-quality" || modelLower.includes("gemini") || modelLower.includes("flash")) {
    imageCostPerPanel = 0.015;
  } else if (modelLower.includes("flux")) {
    imageCostPerPanel = renderPreset === "high_quality" ? 0.075 : 0.055;
  } else {
    imageCostPerPanel = 0.025;
  }
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

export function UploadStep({ onSubmit, isPending, error, onCancel }: UploadStepProps) {
  const { language, t } = useI18n();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState<LanguageCode>(language);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showExpert, setShowExpert] = useState(false);
  const [devMode, setDevMode] = useState(false);
  const [renderPreset, setRenderPreset] = useState<RenderPreset>("balanced");
  const [imageModel, setImageModel] = useState(DEFAULT_IMAGE_MODEL);
  const [imageWidth, setImageWidth] = useState(1024);
  const [imageHeight, setImageHeight] = useState(1024);
  const [imageSteps, setImageSteps] = useState(28);
  const [imageQuality, setImageQuality] = useState<"auto" | "low" | "medium" | "high">("medium");
  const [maxPanelsPerScene, setMaxPanelsPerScene] = useState(8);
  const [maxPanelsPerPage, setMaxPanelsPerPage] = useState(6);
  const [styleTemplate, setStyleTemplate] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const ext = file ? "." + file.name.split(".").pop()?.toLowerCase() : "";
  const extOk = !file || ACCEPTED.includes(ext);
  const derivedProvider = _defaultProviderForModel(imageModel);
  const isTogetherProvider = derivedProvider === "together";
  const isOpenAIProvider = derivedProvider === "openai";

  function handleModelChange(model: string) {
    setImageModel(model);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const selectedImageModel = imageModel.trim();
    if (!file || !name.trim() || !extOk || !selectedImageModel) return;
    const overrides: Partial<ConfigOverrides> = { target_language: targetLanguage };

    // Derive provider from model selection.
    const provider = _defaultProviderForModel(selectedImageModel);
    overrides.image_provider = provider;
    if (selectedImageModel !== DEFAULT_IMAGE_MODEL) overrides.image_model = selectedImageModel;

    // Dev mode: force fast preset and dev overrides.
    if (devMode) {
      overrides.dev_mode = true;
      overrides.quality_preset = "fast";
      overrides.dev_image_scale = 0.6;
      overrides.dev_image_steps = 8;
      overrides.dev_image_concurrency = 5;
      overrides.max_panels_per_scene = 6;
      overrides.max_panels_per_page = 6;
      if (isTogetherProvider) {
        overrides.image_steps = 8;
      }
      if (isOpenAIProvider) {
        overrides.image_quality = "low";
      }
    } else {
      // Normal quality preset handling.
      if (renderPreset === "high_quality") {
        overrides.quality_preset = "quality";
        overrides.dev_mode = false;
        overrides.max_panels_per_scene = 10;
        overrides.max_panels_per_page = 5;
        if (isTogetherProvider) {
          overrides.image_steps = 36;
        }
        if (isOpenAIProvider) {
          overrides.image_quality = "high";
        }
      } else {
        overrides.quality_preset = "balanced";
        overrides.dev_mode = false;
        overrides.max_panels_per_scene = 8;
        overrides.max_panels_per_page = 6;
        if (isTogetherProvider) {
          overrides.image_steps = 24;
        }
        if (isOpenAIProvider) {
          overrides.image_quality = "medium";
        }
      }
    }

    // Advanced manual overrides are opt-in and override presets.
    if (showAdvanced) {
      if (styleTemplate.trim()) overrides.style_template = styleTemplate.trim();
      if (showExpert) {
        if (imageWidth !== 1024) overrides.image_width = imageWidth;
        if (imageHeight !== 1024) overrides.image_height = imageHeight;
        if (isTogetherProvider && imageSteps !== 28) overrides.image_steps = imageSteps;
        if (isOpenAIProvider && imageQuality !== "medium") overrides.image_quality = imageQuality;
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

          {/* Dev mode toggle */}
          <label className="flex items-center gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={devMode}
              onChange={(e) => setDevMode(e.target.checked)}
              className="h-4 w-4 accent-hero-red"
            />
            <div>
              <div className="font-display text-[0.9rem] font-bold uppercase leading-none tracking-[-0.02em] text-ink-black">
                Dev mode
              </div>
              <div className="mt-0.5 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55">
                Process only the first scene for rapid iteration. Forces fast quality preset.
              </div>
            </div>
          </label>
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

        {/* Credit preview strip */}
        {(() => {
          const estimate = file
            ? estimateProjectCredits({
                fileSizeBytes: file.size,
                imageModel,
                renderPreset: devMode ? "fast_draft" : renderPreset,
                devMode,
                maxPanelsPerScene,
              })
            : null;
          return (
            <div className="mt-3 flex items-center justify-between gap-3 border-[2px] border-ink-black bg-chip-gold px-4 py-2 shadow-ink-sm">
              <div>
                <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60">
                  {t("ESTIMATED CREDITS")}
                </div>
                <div className="mt-0.5 font-display text-[1.05rem] font-bold leading-none tracking-[-0.03em] text-ink-black tabular-nums">
                  {estimate ? formatCreditRange(estimate) : t("Upload a file to estimate")}
                </div>
              </div>
              <div className="text-right font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/55">
                {estimate ? (
                  <>
                    {devMode ? "1 scene (dev)" : `~${Math.max(1, Math.round((file?.size ?? 0) / 10_000))} scenes`}
                    <br />
                    {maxPanelsPerScene} {t("panels/scene")}
                  </>
                ) : (
                  <>{maxPanelsPerScene} {t("panels/scene")}</>
                )}
              </div>
            </div>
          );
        })()}

        {showAdvanced && (
          <div className="mt-4 space-y-3 border-t-[2px] border-ink-black pt-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  {t("IMAGE MODEL")}
                </label>
                <select
                  name="imageModel"
                  value={IMAGE_MODEL_OPTIONS.some(o => o.value === imageModel) ? imageModel : "__custom__"}
                  onChange={(e) => {
                    if (e.target.value !== "__custom__") {
                      handleModelChange(e.target.value);
                    }
                  }}
                  className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
                >
                  {IMAGE_MODEL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                  {!IMAGE_MODEL_OPTIONS.some(o => o.value === imageModel) && (
                    <option value="__custom__">Custom: {imageModel}</option>
                  )}
                  <option value="__custom__">Custom model ID...</option>
                </select>
                {!IMAGE_MODEL_OPTIONS.some(o => o.value === imageModel) && (
                  <input
                    type="text"
                    value={imageModel}
                    onChange={(e) => handleModelChange(e.target.value)}
                    placeholder="e.g. black-forest-labs/flux-1-dev"
                    className="mt-2 w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
                  />
                )}
                <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
                  Provider ({derivedProvider}) is auto-derived from model selection.
                </p>
              </div>
            </div>
            <div>
              <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                {t("QUALITY PRESET")}
              </label>
              <select
                name="renderPreset"
                value={devMode ? "fast_draft" : renderPreset}
                onChange={(e) => setRenderPreset(e.target.value as RenderPreset)}
                disabled={devMode}
                className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <option value="fast_draft">Fast draft{devMode ? " (locked — dev mode)" : ""}</option>
                <option value="balanced">Balanced (recommended)</option>
                <option value="high_quality">High quality</option>
              </select>
              <p className="mt-1 text-[0.72rem] leading-relaxed text-ink-black/45">
                {devMode
                  ? "Locked to fast in dev mode."
                  : "Fast draft lowers credit use and latency. Balanced is safe default. High quality increases runtime and credits used."}
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

                {isTogetherProvider && (
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

                {isOpenAIProvider && (
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

        <div className="mt-6 flex items-center gap-3">
          <Button
            type="submit"
            size="lg"
            disabled={!file || !name.trim() || !extOk || !imageModel.trim() || isPending}
          >
            {isPending ? t("CREATING…") : t("CREATE PROJECT")}
          </Button>
          {onCancel && (
            <Button
              type="button"
              size="lg"
              variant="outline"
              onClick={onCancel}
            >
              {t("BACK")}
            </Button>
          )}
        </div>
      </Card>
    </form>
  );
}
