import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useProjectConfig, useProjectStatus, useUpdateProjectConfig, useDeleteProject } from "../api/queries";
import { SettingsLayout } from "../components/ui/SettingsLayout";
import { ConfirmModal, RoomHeader } from "../components/composites";
import { Card } from "../components/ui/Card";
import { SelectField, SwitchField } from "../components/ui/Field";
import { Button } from "../components/ui/Button";
import { LANGUAGES, useI18n } from "../i18n";
import type { LanguageCode } from "../i18n";
import { useShowDevContent } from "../lib/devContent";
import type { ConfigOverrides } from "../types/api";

type QualityPreset = NonNullable<ConfigOverrides["quality_preset"]>;

const QUALITY_PRESET_OPTIONS: Array<{ value: string; label: string; desc: string }> = [
  { value: "fast", label: "Fast", desc: "Lower cost and faster drafts" },
  { value: "balanced", label: "Balanced", desc: "Default quality and runtime" },
  { value: "quality", label: "Quality", desc: "Higher fidelity, slower and more expensive" },
];

const TABS = [
  { id: "language", label: "Language" },
  { id: "dev", label: "Dev Content" },
  { id: "models", label: "Generation" },
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

export function ProjectSettingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { language, setLanguage, t } = useI18n();
  const { data: config } = useProjectConfig(id);
  const { data: status } = useProjectStatus(id);
  const updateConfig = useUpdateProjectConfig();
  const deleteMutation = useDeleteProject();
  const [showDevContent, setShowDevContent] = useShowDevContent();
  const [activeTab, setActiveTab] = useState("language");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const updating = updateConfig.isPending;
  const projectTitle = status?.project_name ?? id ?? "";
  const patch = (data: Parameters<typeof updateConfig.mutate>[0]["data"]) => {
    if (!id) return;
    updateConfig.mutate({ project: id, data });
  };

  function handleDelete() {
    if (!id) return;
    deleteMutation.mutate(
      { id },
      { onSuccess: () => navigate("/") },
    );
  }

  return (
    <>
      <RoomHeader
        kicker="SETTINGS"
        title="Project Settings"
        lead="Project pipeline configuration and preferences."
      />
      <SettingsLayout
        kicker={`PROJECT SETTINGS // ${projectTitle.toUpperCase()}`}
        title="Settings"
        subtitle="Project pipeline configuration and preferences."
        hero={false}
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
              hint={t("Runs a smaller, faster generation path for quick testing.")}
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
              label={t("GENERATION QUALITY")}
              hint={t("Controls speed, fidelity, and cost across the whole pipeline. DEV mode forces Fast.")}
            >
              <SelectField
                value={config?.quality_preset ?? "balanced"}
                onChange={(e) => {
                  patch({ quality_preset: e.target.value as QualityPreset });
                }}
                disabled={!config || updating || !!config?.dev_mode}
                className="max-w-sm bg-bristol font-meta text-[0.72rem] tracking-[0.1em]"
              >
                {QUALITY_PRESET_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label} — {option.desc}</option>
                ))}
              </SelectField>
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
                <span className="font-bold font-meta text-[0.72rem] tracking-[0.08em]">{projectTitle}</span>{" "}
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
        body={`This will permanently delete "${projectTitle}" and all its data. This cannot be undone.`}
        confirmInput={projectTitle}
        confirmLabel="Delete Project"
        busy={deleteMutation.isPending}
        destructive
        onConfirm={handleDelete}
        onClose={() => setShowDeleteConfirm(false)}
      />
    </>
  );
}
