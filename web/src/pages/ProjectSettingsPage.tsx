import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useProjectConfig, useProjectStatus, useUpdateProjectConfig, useDeleteProject } from "../api/queries";
import { SettingsLayout, SettingsRow } from "../components/ui/SettingsLayout";
import { ConfirmModal, SectionHeader } from "../components/composites";
import { Surface } from "../components/ui/Surface";
import { SelectField, SwitchField } from "../components/ui/Field";
import { Button } from "../components/ui/Button";
import { LANGUAGES, useI18n } from "../i18n";
import type { LanguageCode } from "../i18n";
import { useShowDevContent } from "../lib/devContent";

const TABS = [
  { id: "language", label: "Language" },
  { id: "dev", label: "Advanced" },
  { id: "delete", label: "Delete Project" },
];

export function ProjectSettingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { language, setLanguage, t } = useI18n();
  const { data: config, error: configError } = useProjectConfig(id);
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
      { onSuccess: () => navigate("/", { state: { projectDeleted: projectTitle } }) },
    );
  }

  return (
    <>
      <SettingsLayout
        kicker={`PROJECT SETTINGS // ${projectTitle.toUpperCase()}`}
        title="Project settings"
        subtitle={projectTitle}
        tabs={TABS}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      >
        {configError && <p role="alert" className="text-sm text-hero-red">{configError.message}</p>}
        {activeTab !== "delete" && (
          <div aria-live="polite" aria-atomic="true">
            {updateConfig.isPending && <p className="text-sm">{t("Saving…")}</p>}
            {updateConfig.isError && <p role="alert" className="text-sm text-hero-red">{updateConfig.error.message}</p>}
            {updateConfig.isSuccess && <p role="status" className="text-sm">{t("Settings saved.")}</p>}
          </div>
        )}
        {activeTab === "language" && (<div>
          <SectionHeader title="Language" description="Choose the language you work in and the language your comic speaks." />
          <Surface border="soft" shadow="none">
            <SettingsRow label={t("UI LANGUAGE")} hint={t("Controls the studio interface language. Stored locally.")}>
              <SelectField
                aria-label={t("UI LANGUAGE")}
                name="ui_language"
                value={language}
                onChange={(e) => setLanguage(e.target.value as LanguageCode)}
                className="max-w-sm bg-bristol font-body text-base"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </SelectField>
            </SettingsRow>

            <SettingsRow
              label={t("OUTPUT LANGUAGE")}
              hint={t("The language used for this project’s generated story and dialogue.")}
            >
              <SelectField
                aria-label={t("OUTPUT LANGUAGE")}
                name="target_language"
                value={config?.target_language ?? "en"}
                onChange={(e) => patch({ target_language: e.target.value as LanguageCode })}
                disabled={!config || updating}
                className="max-w-sm bg-bristol font-body text-base"
              >
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
              </SelectField>
            </SettingsRow>
          </Surface></div>
        )}

        {activeTab === "dev" && (<div>
          <SectionHeader title="Advanced" description="Development tools and smaller test runs." />
          <Surface border="soft" shadow="none">
            <SettingsRow
              label={t("SHOW DEV CONTENT")}
              hint={t("Shows raw file paths, model names, SHA hashes, and generation parameters for debugging.")}
            >
              <SwitchField
                checked={showDevContent}
                onCheckedChange={setShowDevContent}
                label={t("SHOW DEV CONTENT")}
              />
            </SettingsRow>

            <SettingsRow
              label={t("DEV / DEMO MODE")}
              hint={t("Runs a smaller, faster generation path for quick testing.")}
            >
              <SwitchField
                checked={!!config?.dev_mode}
                onCheckedChange={(v) => patch({ dev_mode: v })}
                disabled={!config || updating}
                label={t("DEV / DEMO MODE")}
              />
            </SettingsRow>
          </Surface></div>
        )}

        {activeTab === "delete" && (
          <Surface padding="lg" border="soft" shadow="none">
            <div className="py-4">
              <div className="font-display text-[1.1rem] leading-tight tracking-[-0.02em] uppercase">
                Delete this project
              </div>
              <p className="mt-3 text-[0.88rem] leading-6 text-ink-black/65">
                This will permanently delete the project{" "}
                <span className="font-bold font-meta text-sm tracking-[0.04em]">{projectTitle}</span>{" "}
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
          </Surface>
        )}
      </SettingsLayout>

      <ConfirmModal
        open={showDeleteConfirm}
        title="Delete Project"
        body={`This will permanently delete "${projectTitle}" and all its data. This cannot be undone.`}
        confirmInput={projectTitle}
        confirmLabel="Delete Project"
        busy={deleteMutation.isPending}
        error={deleteMutation.error?.message}
        destructive
        onConfirm={handleDelete}
        onClose={() => setShowDeleteConfirm(false)}
      />
    </>
  );
}
