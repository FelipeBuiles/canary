import { ErrorNotice } from "../components/composites/ErrorNotice";
import { lazy, Suspense, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useProjectConfig, useProjectStatus, useUpdateProjectConfig, useDeleteProject, useRenameProject } from "../api/queries";
import { ApiError } from "../api/client";
import { SettingsLayout, SettingsRow } from "../components/ui/SettingsLayout";
import { ConfirmModal, SectionHeader } from "../components/composites";
import { Surface } from "../components/ui/Surface";
import { FieldLabel, SelectField, SwitchField, TextField } from "../components/ui/Field";
import { Button } from "../components/ui/Button";
import { LANGUAGES, useI18n } from "../i18n";
import type { LanguageCode } from "../i18n";
import { useShowDevContent } from "../lib/devContent";

const TABS = [
  { id: "general", label: "General" },
  { id: "language", label: "Language" },
  ...(import.meta.env.DEV ? [{ id: "models", label: "Models (dev)" }] : []),
  ...(import.meta.env.DEV ? [{ id: "dev", label: "Advanced" }] : []),
  { id: "delete", label: "Delete Project" },
];

const ProjectModelControls = import.meta.env.DEV ? lazy(() => import("../components/wizard/ProjectModelControls")) : null;

function ProjectNameForm({ project, projectName }: { project: string; projectName: string }) {
  const { t } = useI18n();
  const rename = useRenameProject();
  const [draft, setDraft] = useState(projectName);
  const [touched, setTouched] = useState(false);
  const name = draft.trim();
  const validationError = !name
    ? t("Enter a project name.")
    : Array.from(name).length > 200
      ? t("Use 200 characters or fewer.")
      : null;
  const serverFieldError = rename.error instanceof ApiError && rename.error.status === 422
    ? t("Enter a project name with 200 characters or fewer.")
    : null;
  const fieldError = (touched ? validationError : null) ?? serverFieldError;
  const unchanged = name === projectName;

  return (
    <form
      aria-label={t("Project name")}
      aria-busy={rename.isPending}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setTouched(true);
        if (rename.isPending || validationError || unchanged) return;
        rename.mutate({ id: project, name }, {
          onSuccess: (data) => {
            setDraft(data.project_name);
            setTouched(false);
          },
        });
      }}
    >
      <Surface border="soft" shadow="none">
        <SettingsRow
          label={t("Project name")}
          hint={t("Changes the name shown in your library and studio. Your story, artwork, and exports stay unchanged.")}
        >
          <div className="space-y-4">
            <div className="space-y-2">
              <FieldLabel htmlFor="project-name" className="sr-only">{t("Project name")}</FieldLabel>
              <TextField
                id="project-name"
                name="project_name"
                value={draft}
                required
                disabled={rename.isPending}
                aria-invalid={!!fieldError}
                aria-describedby={`project-name-hint${fieldError ? " project-name-error" : ""}`}
                onBlur={() => setTouched(true)}
                onChange={(event) => {
                  setDraft(event.target.value);
                  rename.reset();
                }}
                className="bg-bristol font-body text-base"
              />
              <p id="project-name-hint" className="font-body text-sm leading-6 text-ink-muted">{t("Up to 200 characters. Leading and trailing spaces are removed.")}</p>
              {fieldError && <p id="project-name-error" role="alert" className="text-sm text-hero-red">{fieldError}</p>}
            </div>
            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={rename.isPending || !!validationError || unchanged}>
                {rename.isPending ? t("Saving…") : t("Save name")}
              </Button>
              <Button
                variant="outline"
                disabled={rename.isPending}
                onClick={() => {
                  setDraft(projectName);
                  setTouched(false);
                  rename.reset();
                }}
              >
                {t("Cancel")}
              </Button>
            </div>
            <div aria-live="polite" aria-atomic="true">
              {rename.isPending && <p className="text-sm">{t("Saving…")}</p>}
              {rename.isError && !serverFieldError && <ErrorNotice error={rename.error} operation="save" />}
              {rename.isSuccess && <p role="status" className="text-sm">{t("Project name saved.")}</p>}
            </div>
          </div>
        </SettingsRow>
      </Surface>
    </form>
  );
}

export function ProjectSettingsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { language, setLanguage, t } = useI18n();
  const { data: config, error: configError, refetch: refetchConfig } = useProjectConfig(id);
  const { data: status, error: statusError, refetch: refetchStatus } = useProjectStatus(id);
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
        {configError && <ErrorNotice error={configError} operation="load" onRetry={() => void refetchConfig()} />}
        {activeTab !== "delete" && activeTab !== "general" && (
          <div aria-live="polite" aria-atomic="true">
            {updateConfig.isPending && <p className="text-sm">{t("Saving…")}</p>}
            {updateConfig.isError && <ErrorNotice error={updateConfig.error} operation="save" />}
            {updateConfig.isSuccess && <p role="status" className="text-sm">{t("Settings saved.")}</p>}
          </div>
        )}
        {activeTab === "general" && (<div>
          <SectionHeader title="General" />
          {config?.lettering_mode && <Surface border="soft" shadow="none" padding="md" className="mb-4">
            <p className="font-body text-sm font-bold">{t(config.lettering_mode === "integrated" ? "Integrated lettering" : "Editable lettering")}</p>
            <p className="mt-2 text-sm leading-relaxed text-ink-muted">{t("Switching later requires a new project and generating new pages. Neither mode guarantees a perfect first result.")}</p>
          </Surface>}
          {id && status ? (
            <ProjectNameForm key={id} project={id} projectName={status.project_name} />
          ) : statusError ? (
            <ErrorNotice error={statusError} operation="load" onRetry={() => void refetchStatus()} />
          ) : (
            <p role="status" className="text-sm">{t("Loading project…")}</p>
          )}
        </div>)}
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

        {activeTab === "models" && ProjectModelControls && (<div>
          <SectionHeader title="Models for this project (dev)" description="Model changes apply to new work. Saving does not start generation." />
          <p className="mb-4 font-body text-sm leading-6 text-ink-muted">{t("New Draw jobs use the selected model. Existing pages keep their artwork and lettering mode.")}</p>
          <Suspense fallback={<p role="status">{t("Loading model settings…")}</p>}>
            {config && <ProjectModelControls
              selections={config.dev_model_selections ?? {}}
              onChange={(selections) => patch({ dev_model_selections: selections })}
              disabled={updating}
            />}
          </Suspense>
        </div>)}

        {import.meta.env.DEV && activeTab === "dev" && (<div>
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
              hint={t("Uses the local development generation concurrency limit.")}
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
        error={deleteMutation.error}
        destructive
        onConfirm={handleDelete}
        onClose={() => setShowDeleteConfirm(false)}
      />
    </>
  );
}
