import { Button } from "../ui/Button";
import { useSetTheme, useApplyBubblePreset, useCharacterVoices, useDeleteCharacterVoice } from "../../api/queries";
import { usePages } from "../../api/queries";

interface StyleModeProps {
  project: string | undefined;
  isMatchingStyle: boolean;
  isTranslatingBubbles: boolean;
  outputLanguage: "en" | "es" | "fr";
  pageCount: number;
  onMatchStyle: () => void;
  onTranslateBubbles: (lang: "en" | "es" | "fr") => void;
  onOutputLanguageChange: (lang: "en" | "es" | "fr") => void;
}

const BUBBLE_PRESETS = [
  {
    id: "speech",
    label: "SPEECH",
    preview: "Where am I?",
    previewClass: "rounded-[10px] border-[2px] border-ink-black bg-white",
  },
  {
    id: "thought",
    label: "THOUGHT",
    preview: "Hmm...",
    previewClass: "rounded-[22px] border-[2px] border-dashed border-ink-black bg-white",
  },
  {
    id: "narration",
    label: "NARRATION",
    preview: "The city sleeps.",
    previewClass: "rounded-sm border-[2px] border-ink-black bg-surface-container font-mono",
  },
  {
    id: "whisper",
    label: "WHISPER",
    preview: "shhh...",
    previewClass:
      "rounded-[10px] border border-dashed border-ink-black/50 bg-white/80 text-[0.7rem] italic",
  },
  {
    id: "shout",
    label: "SHOUT",
    preview: "WATCH OUT!",
    previewClass:
      "rounded-sm border-[3px] border-ink-black bg-narrator-gold font-black tracking-wide",
  },
] as const;

const THEME_SWATCHES = [
  { id: "default", label: "Ethereal Ink", color: "#F8F1DE", active: true },
  { id: "noir", label: "Noir", color: "#1A1814" },
  { id: "manga", label: "Manga", color: "#FFFFFF" },
  { id: "vintage", label: "Vintage", color: "#E8D5B0" },
  { id: "painted", label: "Painted", color: "#D4C5A9" },
] as const;

const LANGUAGES = [
  { value: "en" as const, label: "English" },
  { value: "es" as const, label: "Español" },
  { value: "fr" as const, label: "Français" },
];

export function StyleMode({
  project,
  isMatchingStyle,
  isTranslatingBubbles,
  outputLanguage,
  pageCount,
  onMatchStyle,
  onTranslateBubbles,
  onOutputLanguageChange,
}: StyleModeProps) {
  const setThemeMut = useSetTheme();
  const applyPresetMut = useApplyBubblePreset();
  const { data: pageList } = usePages(project);
  const activeTheme = pageList?.[0]?.theme ?? "default";
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto grid w-full max-w-[1200px] grid-cols-1 gap-6 p-6 lg:grid-cols-[1fr_380px]">
        {/* Left column */}
        <div className="space-y-6">
          {/* Match Lettering hero — the #1 elevation in this redesign */}
          <div className="border-[2px] border-ink-black bg-pulp-paper p-6 shadow-ink">
            <div className="font-meta text-[0.52rem] tracking-[0.18em] text-hero-red">
              STYLE · PRIMARY ACTION
            </div>
            <h2 className="mt-2 font-display text-[clamp(1.5rem,3vw,2.2rem)] font-black uppercase leading-none tracking-[-0.04em] [font-stretch:75%]">
              MATCH LETTERING TO ART
            </h2>
            <p className="mt-3 max-w-[50ch] text-[0.88rem] leading-relaxed text-ink-black/60">
              Analyzes your panel art and sets bubble fonts, borders, and colors to match the
              visual style. Runs once — takes about 30 seconds.
            </p>
            <div className="mt-5 flex items-center gap-4">
              <Button size="lg" onClick={onMatchStyle} disabled={isMatchingStyle}>
                {isMatchingStyle ? "MATCHING..." : "Match now"}
                {!isMatchingStyle && (
                  <kbd className="ml-1 rounded bg-hero-red/20 px-1.5 py-0.5 text-[0.5rem]">
                    ⌘M
                  </kbd>
                )}
              </Button>
              <span className="font-meta text-[0.58rem] tracking-[0.1em] text-ink-black/40">
                ~{pageCount} page{pageCount !== 1 ? "s" : ""}
              </span>
            </div>
          </div>

          {/* Bubble presets grid */}
          <div className="border-[2px] border-ink-black bg-pulp-paper shadow-ink-sm">
            <div className="border-b-[2px] border-ink-black px-5 py-3">
              <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
                STYLE
              </div>
              <div className="font-display text-[1rem] font-bold tracking-[-0.02em]">
                BUBBLE PRESETS
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3">
              {BUBBLE_PRESETS.map((preset) => (
                <div key={preset.id} className="border-[2px] border-ink-black p-2.5">
                  <div className="mb-2 font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/50">
                    {preset.label}
                  </div>
                  <div className={`px-2.5 py-2 text-[0.75rem] leading-tight ${preset.previewClass}`}>
                    {preset.preview}
                  </div>
                  <div className="mt-2">
                    <button
                      onClick={() => {
                        if (project) applyPresetMut.mutate({ project, presetName: preset.id });
                      }}
                      disabled={!project || applyPresetMut.isPending}
                      className="font-meta text-[0.5rem] tracking-[0.08em] text-hero-red hover:underline disabled:opacity-40"
                    >
                      {applyPresetMut.isPending ? "Applying..." : "Apply all ↗"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Theme swatches */}
          <div className="border-[2px] border-ink-black bg-pulp-paper shadow-ink-sm">
            <div className="border-b-[2px] border-ink-black px-5 py-3">
              <div className="font-display text-[1rem] font-bold tracking-[-0.02em]">THEMES</div>
            </div>
            <div className="flex flex-wrap gap-4 p-4">
              {THEME_SWATCHES.map((swatch) => (
                <button
                  key={swatch.id}
                  onClick={() => {
                    if (project && swatch.id !== activeTheme) {
                      setThemeMut.mutate({ project, theme: swatch.id });
                    }
                  }}
                  disabled={setThemeMut.isPending}
                  className="flex flex-col items-center gap-1.5 transition-opacity hover:opacity-100 disabled:cursor-wait"
                  style={{ opacity: swatch.id === activeTheme ? 1 : 0.7 }}
                >
                  <div
                    className={`h-10 w-10 border-[2px] shadow-ink-sm ${
                      swatch.id === activeTheme ? "border-hero-red" : "border-ink-black"
                    }`}
                    style={{ background: swatch.color }}
                  />
                  <span className="font-meta text-[0.5rem] tracking-[0.1em] text-ink-black/60">
                    {swatch.label}
                  </span>
                  {swatch.id === activeTheme && (
                    <span className="font-meta text-[0.46rem] tracking-[0.1em] text-hero-red">
                      ACTIVE
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-6">
          {/* Translate card */}
          <div className="border-[2px] border-ink-black bg-pulp-paper shadow-ink-sm">
            <div className="border-b-[2px] border-ink-black px-5 py-3">
              <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
                LOCALIZATION
              </div>
              <div className="font-display text-[1rem] font-bold tracking-[-0.02em]">
                TRANSLATE PROJECT
              </div>
            </div>
            <div className="space-y-3 p-4">
              <p className="text-[0.82rem] leading-relaxed text-ink-black/60">
                Translate all bubble text project-wide into a target language.
              </p>
              <div className="grid grid-cols-3 gap-2">
                {LANGUAGES.map((lang) => (
                  <button
                    key={lang.value}
                    onClick={() => onOutputLanguageChange(lang.value)}
                    disabled={isTranslatingBubbles}
                    className={`border-[2px] border-ink-black px-3 py-2 font-meta text-[0.62rem] tracking-[0.1em] transition-colors hover:bg-surface-container disabled:opacity-50 ${
                      outputLanguage === lang.value
                        ? "bg-ink-black text-pulp-paper"
                        : "bg-pulp-paper"
                    }`}
                  >
                    {lang.label}
                  </button>
                ))}
              </div>
              <Button
                size="sm"
                variant="secondary"
                fullWidth
                onClick={() => onTranslateBubbles(outputLanguage)}
                disabled={isTranslatingBubbles}
              >
                {isTranslatingBubbles ? "TRANSLATING..." : "Translate project"}
              </Button>
            </div>
          </div>

          {/* Voice lock */}
          <StyleModeVoiceLock project={project} />

          {/* Explainer */}
          <div className="border-[2px] border-ink-black bg-surface-container p-4">
            <div className="mb-1 font-meta text-[0.52rem] tracking-[0.14em] text-ink-black/50">
              WHY STYLE MODE?
            </div>
            <p className="text-[0.78rem] leading-relaxed text-ink-black/60">
              Run once, maybe twice. Match Lettering analyzes your art and sets consistent fonts and
              borders across the whole comic. Translate handles localization globally so you don't
              repeat it per page.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StyleModeVoiceLock({ project }: { project: string | undefined }) {
  const { data: voices } = useCharacterVoices(project);
  const deleteVoiceMut = useDeleteCharacterVoice();
  const voiceList = voices ? Object.values(voices) : [];

  return (
    <div className="border-[2px] border-ink-black bg-pulp-paper shadow-ink-sm">
      <div className="border-b-[2px] border-ink-black px-5 py-3">
        <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
          CHARACTER
        </div>
        <div className="font-display text-[1rem] font-bold tracking-[-0.02em]">
          VOICE LOCK
        </div>
      </div>
      <div className="p-4">
        <p className="text-[0.82rem] leading-relaxed text-ink-black/60">
          Set a style per character — all their dialogue inherits it automatically.
        </p>
        {voiceList.length === 0 ? (
          <div className="mt-3 font-meta text-[0.55rem] tracking-[0.1em] text-ink-black/40">
            No voices configured yet. Use Script mode to set character voices.
          </div>
        ) : (
          <div className="mt-3 space-y-1.5">
            {voiceList.map((voice) => (
              <div key={voice.character_id} className="flex items-center justify-between border-[2px] border-ink-black/20 px-2.5 py-1.5">
                <div>
                  <span className="font-meta text-[0.58rem] tracking-[0.08em] font-bold">
                    {voice.character_name.toUpperCase()}
                  </span>
                  <div className="mt-0.5 flex gap-2">
                    {voice.font_family && (
                      <span className="font-meta text-[0.46rem] text-ink-black/40">{voice.font_family}</span>
                    )}
                    {voice.font_size != null && (
                      <span className="font-meta text-[0.46rem] text-ink-black/40">{voice.font_size}px</span>
                    )}
                    {voice.fill_color && (
                      <span className="inline-flex items-center gap-1 font-meta text-[0.46rem] text-ink-black/40">
                        <span className="inline-block h-2 w-2 border border-ink-black/20" style={{ background: voice.fill_color }} />
                      </span>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => {
                    if (project) deleteVoiceMut.mutate({ project, characterId: voice.character_id });
                  }}
                  disabled={deleteVoiceMut.isPending}
                  className="font-meta text-[0.5rem] tracking-[0.08em] text-ink-black/40 hover:text-hero-red"
                >
                  Clear
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
