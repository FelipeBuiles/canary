import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useProjectConfig, useUpdateProjectConfig, useDeleteProject } from "../api/queries";
import { SettingsLayout } from "../components/ui/SettingsLayout";
import { ConfirmModal } from "../components/ui/ConfirmModal";
import { Card } from "../components/ui/Card";
import { SelectField, SwitchField, TextField } from "../components/ui/Field";
import { Button } from "../components/ui/Button";
import { LANGUAGES, useI18n } from "../i18n";
import type { LanguageCode } from "../i18n";
import { useShowDevContent } from "../lib/devContent";
import type { ConfigOverrides } from "../types/api";

type ImageProvider = NonNullable<ConfigOverrides["image_provider"]>;
type QualityPreset = NonNullable<ConfigOverrides["quality_preset"]>;

const IMAGE_PROVIDER_OPTIONS: Array<{ value: ImageProvider; label: string }> = [
  { value: "gemini", label: "Gemini" },
  { value: "openai", label: "OpenAI" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "together", label: "Together AI" },
];

const QUALITY_PRESET_OPTIONS: Array<{ value: string; label: string; desc: string }> = [
  { value: "", label: "Custom", desc: "Use individual model fields" },
  { value: "fast", label: "Fast", desc: "Gemini Flash Lite for all stages" },
  { value: "balanced", label: "Balanced", desc: "Gemini Pro + Claude Sonnet + GPT-5.4-mini" },
  { value: "quality", label: "Quality", desc: "GPT-5.4 + Claude Opus + Sonnet" },
];

const TEXT_MODEL_FIELDS: Array<{ key: keyof ConfigOverrides; label: string; hint: string }> = [
  { key: "extraction_model", label: "EXTRACT MODEL", hint: "Stage 1 — full-novel extraction (needs large context)" },
  { key: "screenplay_model", label: "ADAPT MODEL", hint: "Stage 3 — screenplay adaptation" },
  { key: "panel_model", label: "PLAN MODEL", hint: "Stage 4 — layout planning" },
  { key: "prompt_model", label: "PROMPT MODEL", hint: "Style suggestions, lettering, translation" },
];

const TABS = [
  { id: "language", label: "Language" },
  { id: "dev", label: "Dev Content" },
  { id: "models", label: "Model Config" },
  { id: "delete", label: "Delete Project" },
];

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-3 border-b border-ink-black/10 py-4 last:border-b-0 md:grid-cols-[220px_1fr] md:items-start md:gap-6">
      <div>
        <div className="font-meta text-[0.56rem] tracking-[0.18em] text-ink-black/55">{label}</div>
        {hint && (
          <p className="mt-1.5 text-[0.72rem] leading-5 text-ink-black/55">{hint}</p>
        )}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function ImageModelField({
  disabled,
  onCommit,
  value,
}: {
  disabled: boolean;
  onCommit: (value: string) => void;
  value: string;
}) {
  const [draft, setDraft] = useState(value);
  const commit = () => {
    const nextModel = draft.trim();
    if (nextModel && nextModel !== value) onCommit(nextModel);
  };

  return (
    <TextField
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          commit();
          e.currentTarget.blur();
        }
      }}
      placeholder="flux-1.1-pro"
      disabled={disabled}
      className="max-w-sm bg-bristol"
    />
  );
}

export function ProjectSettingsPage() {
  const { name } = useParams();
  const navigate = useNavigate();
  const { language, setLanguage, t } = useI18n();
  const { data: config } = useProjectConfig(name);
  const updateConfig = useUpdateProjectConfig();
  const deleteMutation = useDeleteProject();
  const [showDevContent, setShowDevContent] = useShowDevContent();
  const [activeTab, setActiveTab] = useState("language");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const updating = updateConfig.isPending;
  const patch = (data: Parameters<typeof updateConfig.mutate>[0]["data"]) => {
    if (!name) return;
    updateConfig.mutate({ project: name, data });
  };

  function handleDelete() {
    if (!name) return;
    deleteMutation.mutate(
      { name },
      { onSuccess: () => navigate("/") },
    );
  }

  return (
    <>
      <SettingsLayout
        kicker={`PROJECT SETTINGS // ${name?.toUpperCase() ?? ""}`}
        title="Settings"
        subtitle="Project pipeline configuration and preferences."
        tabs={TABS}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      >
        {activeTab === "language" && (
          <Card className="px-5">
            <Row label={t("UI LANGUAGE")} hint={t("Controls the studio interface language. Stored locally.")}>
              <SelectField
                value={language}
                onChange={(e) => setLanguage(e.target.value as LanguageCode)}
                className="max-w-sm bg-bristol font-meta text-[0.72rem] tracking-[0.1em]"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </SelectField>
            </Row>

            <Row
              label={t("OUTPUT LANGUAGE")}
              hint={t("Controls generated dialogue, narration, style suggestions, and prompt artifacts for this project.")}
            >
              <SelectField
                value={config?.target_language ?? "en"}
                onChange={(e) => patch({ target_language: e.target.value as LanguageCode })}
                disabled={!config || updating}
                className="max-w-sm bg-bristol font-meta text-[0.72rem] tracking-[0.1em]"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </SelectField>
            </Row>
          </Card>
        )}

        {activeTab === "dev" && (
          <Card className="px-5">
            <Row
              label={t("SHOW DEV CONTENT")}
              hint={t("Shows raw file paths, model names, SHA hashes, and generation parameters for debugging.")}
            >
              <SwitchField
                checked={showDevContent}
                onCheckedChange={setShowDevContent}
                label={t("SHOW DEV CONTENT")}
              />
            </Row>

            <Row
              label={t("DEV / DEMO MODE")}
              hint={t("Uses the faster image model, fewer steps, and smaller generated files for quick testing.")}
            >
              <SwitchField
                checked={!!config?.dev_mode}
                onCheckedChange={(v) => patch({ dev_mode: v })}
                disabled={!config || updating}
                label={t("DEV / DEMO MODE")}
              />
            </Row>
          </Card>
        )}

        {activeTab === "models" && (
          <Card className="px-5">
            <Row
              label={t("QUALITY PRESET")}
              hint={t("Overrides all four text model fields at once. DEV mode forces Fast regardless.")}
            >
              <SelectField
                value={config?.quality_preset ?? ""}
                onChange={(e) => {
                  const val = e.target.value;
                  patch({ quality_preset: (val || null) as QualityPreset | null });
                }}
                disabled={!config || updating || !!config?.dev_mode}
                className="max-w-sm bg-bristol font-meta text-[0.72rem] tracking-[0.1em]"
              >
                {QUALITY_PRESET_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label} — {option.desc}</option>
                ))}
              </SelectField>
            </Row>

            {TEXT_MODEL_FIELDS.map((field) => (
              <Row key={field.key} label={field.label} hint={field.hint}>
                <ImageModelField
                  key={`${name}:${field.key}:${(config as unknown as Record<string, unknown>)?.[field.key] ?? ""}`}
                  value={((config as unknown as Record<string, unknown>)?.[field.key] as string) ?? ""}
                  onCommit={(v) => patch({ [field.key]: v })}
                  disabled={!config || updating || !!config?.quality_preset || !!config?.dev_mode}
                />
              </Row>
            ))}

            <Row
              label={t("COMIC THEME")}
              hint={t("Leave empty for default style. Override to set visual identity of the comic.")}
            >
              <TextField
                value={config?.comic_theme ?? ""}
                onChange={(e) => patch({ comic_theme: e.target.value })}
                placeholder="golden-age noir"
                disabled={!config || updating}
                className="max-w-sm bg-bristol"
              />
            </Row>

            <Row label={t("STYLE TEMPLATE")}>
              <TextField
                value={config?.style_template ?? ""}
                onChange={(e) => patch({ style_template: e.target.value })}
                placeholder="pulp-comic"
                disabled={!config || updating}
                className="max-w-sm bg-bristol"
              />
            </Row>

            <Row
              label="IMAGE PROVIDER"
              hint="Routes image generation through the selected provider instead of inferring it from the model name."
            >
              <SelectField
                value={config?.image_provider ?? "gemini"}
                onChange={(e) => patch({ image_provider: e.target.value as ImageProvider })}
                disabled={!config || updating}
                className="max-w-sm bg-bristol font-meta text-[0.72rem] tracking-[0.1em]"
              >
                {IMAGE_PROVIDER_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </SelectField>
            </Row>

            <Row label={t("IMAGE MODEL")}>
              <ImageModelField
                key={`${name}:${config?.image_model ?? ""}`}
                value={config?.image_model ?? ""}
                onCommit={(image_model) => patch({ image_model })}
                disabled={!config}
              />
            </Row>
          </Card>
        )}

        {activeTab === "delete" && (
          <Card className="px-5" tone="bristol">
            <div className="py-4">
              <div className="font-display text-[1.1rem] leading-tight tracking-[-0.02em] uppercase">
                Delete this project
              </div>
              <p className="mt-3 text-[0.88rem] leading-6 text-ink-black/65">
                This will permanently delete the project{" "}
                <span className="font-bold font-meta text-[0.72rem] tracking-[0.08em]">{name}</span>{" "}
                and all associated pipeline data, assets, and generated files. This action cannot be undone.
              </p>
              <div className="mt-5">
                <Button
                  variant="outline"
                  size="md"
                  onClick={() => setShowDeleteConfirm(true)}
                  className="border-hero-red text-hero-red hover:bg-chip-red/40 hover:text-hero-red"
                >
                  Delete Project
                </Button>
              </div>
            </div>
          </Card>
        )}
      </SettingsLayout>

      <ConfirmModal
        open={showDeleteConfirm}
        title="Delete Project"
        body={`This will permanently delete "${name}" and all its data. This cannot be undone.`}
        confirmInput={name}
        confirmLabel="Delete Project"
        busy={deleteMutation.isPending}
        destructive
        onConfirm={handleDelete}
        onClose={() => setShowDeleteConfirm(false)}
      />
    </>
  );
}
