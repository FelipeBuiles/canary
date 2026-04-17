import { useState, useRef } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { SectionLabel } from "../SectionLabel";
import type { ConfigOverrides } from "../../types/api";

interface UploadStepProps {
  onSubmit: (file: File, name: string, configOverrides?: Partial<ConfigOverrides>) => void;
  isPending: boolean;
  error: string | null;
}

const ACCEPTED = [".txt", ".epub", ".pdf"];

export function UploadStep({ onSubmit, isPending, error }: UploadStepProps) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [theme, setTheme] = useState("auto");
  const [imageModel, setImageModel] = useState("gemini-3-pro-image-preview");
  const [imageWidth, setImageWidth] = useState(1024);
  const [imageHeight, setImageHeight] = useState(1024);
  const [imageSteps, setImageSteps] = useState(28);
  const [maxPanelsPerScene, setMaxPanelsPerScene] = useState(8);
  const [maxPanelsPerPage, setMaxPanelsPerPage] = useState(6);
  const [styleTemplate, setStyleTemplate] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const ext = file ? "." + file.name.split(".").pop()?.toLowerCase() : "";
  const extOk = !file || ACCEPTED.includes(ext);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !name.trim() || !extOk) return;
    const overrides: Partial<ConfigOverrides> = {};
    if (showAdvanced) {
      if (theme !== "auto") overrides.comic_theme = theme;
      if (imageModel !== "gemini-3-pro-image-preview") overrides.image_model = imageModel;
      if (imageWidth !== 1024) overrides.image_width = imageWidth;
      if (imageHeight !== 1024) overrides.image_height = imageHeight;
      if (imageSteps !== 28) overrides.image_steps = imageSteps;
      if (maxPanelsPerScene !== 8) overrides.max_panels_per_scene = maxPanelsPerScene;
      if (maxPanelsPerPage !== 6) overrides.max_panels_per_page = maxPanelsPerPage;
      if (styleTemplate.trim()) overrides.style_template = styleTemplate.trim();
    }
    onSubmit(file, name.trim(), Object.keys(overrides).length > 0 ? overrides : undefined);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <Card className="p-5 md:p-6">
        <SectionLabel tone="red">NEW PRODUCTION</SectionLabel>
        <h1 className="mt-4 display-headline">CREATE PROJECT</h1>
        <p className="mt-4 lead-pulp max-w-[52ch]">
          Upload your novel file and the pipeline will take it from there —
          extracting characters, drawing panels, and assembling pages.
        </p>

        <div className="mt-6 space-y-4">
          <div>
            <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
              PROJECT NAME
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Novel"
              className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm font-body focus:outline-none focus:ring-2 focus:ring-hero-red"
              required
            />
          </div>

          <div>
            <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
              NOVEL FILE
            </label>
            <div
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const dropped = e.dataTransfer.files[0];
                if (dropped) setFile(dropped);
              }}
              className="flex min-h-[120px] cursor-pointer flex-col items-center justify-center border-[2px] border-dashed border-ink-black bg-pulp-paper px-4 py-6 hover:bg-ghost-shadow/30 transition-colors"
            >
              {file ? (
                <>
                  <div className="font-display text-[1rem] font-bold tracking-[-0.04em]">
                    {file.name}
                  </div>
                  <div className="mt-1 font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/50">
                    {(file.size / 1024 / 1024).toFixed(1)} MB
                  </div>
                  {!extOk && (
                    <div className="mt-2 text-[0.78rem] text-hero-red">
                      Unsupported file type. Accepted: {ACCEPTED.join(", ")}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <Icon name="plus" size={22} className="text-ink-black/40" />
                  <div className="mt-2 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50">
                    DROP FILE OR CLICK TO BROWSE
                  </div>
                  <div className="mt-1 text-[0.72rem] text-ink-black/40">
                    .txt, .epub, .pdf
                  </div>
                </>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.epub,.pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) setFile(f);
              }}
            />
          </div>
        </div>

        {/* Advanced config toggle */}
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="mt-4 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/50 hover:text-ink-black transition-colors"
        >
          {showAdvanced ? "▼" : "▶"} ADVANCED CONFIGURATION
        </button>

        {showAdvanced && (
          <div className="mt-4 space-y-3 border-t-[2px] border-ink-black pt-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  COMIC THEME
                </label>
                <select
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
                  IMAGE MODEL
                </label>
                <select
                  value={imageModel}
                  onChange={(e) => setImageModel(e.target.value)}
                  className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm"
                >
                  <option value="gemini-3-pro-image-preview">Gemini 3 Pro Image</option>
                  <option value="gemini-3.1-flash-image-preview">Gemini 3.1 Flash Image</option>
                </select>
              </div>
            </div>
            <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  WIDTH
                </label>
                <input type="number" value={imageWidth} onChange={(e) => setImageWidth(Number(e.target.value))} min={256} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  HEIGHT
                </label>
                <input type="number" value={imageHeight} onChange={(e) => setImageHeight(Number(e.target.value))} min={256} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  STEPS
                </label>
                <input type="number" value={imageSteps} onChange={(e) => setImageSteps(Number(e.target.value))} min={1} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  PANELS/SCENE
                </label>
                <input type="number" value={maxPanelsPerScene} onChange={(e) => setMaxPanelsPerScene(Number(e.target.value))} min={1} max={20} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
              </div>
            </div>
            <div className="grid gap-3 grid-cols-2">
              <div>
                <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                  PANELS/PAGE
                </label>
                <input type="number" value={maxPanelsPerPage} onChange={(e) => setMaxPanelsPerPage(Number(e.target.value))} min={1} max={12} className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm" />
              </div>
            </div>
            <div>
              <label className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/60 block mb-1">
                STYLE TEMPLATE
              </label>
              <textarea
                value={styleTemplate}
                onChange={(e) => setStyleTemplate(e.target.value)}
                placeholder="Leave empty for default style. Override to set visual identity of the comic."
                rows={3}
                className="w-full border-[2px] border-ink-black bg-bristol px-3 py-2 text-sm resize-y"
              />
            </div>
          </div>
        )}

        {error && (
          <div className="mt-4 text-[0.82rem] text-hero-red">{error}</div>
        )}

        <div className="mt-6">
          <Button
            type="submit"
            size="lg"
            disabled={!file || !name.trim() || !extOk || isPending}
          >
            {isPending ? "CREATING…" : "CREATE PROJECT"}
          </Button>
        </div>
      </Card>
    </form>
  );
}
