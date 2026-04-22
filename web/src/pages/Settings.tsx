import { useParams } from "react-router-dom";
import { useProjectConfig, useUpdateProjectConfig } from "../api/queries";
import { SectionLabel } from "../components/SectionLabel";
import { SectionDivider } from "../components/SectionDivider";
import { Card } from "../components/ui/Card";
import { SelectField, SwitchField, TextField } from "../components/ui/Field";
import { LANGUAGES, useI18n } from "../i18n";
import type { LanguageCode } from "../i18n";

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

export function Settings() {
  const { name } = useParams();
  const { language, setLanguage, t } = useI18n();
  const { data: config } = useProjectConfig(name);
  const updateConfig = useUpdateProjectConfig();

  const updating = updateConfig.isPending;
  const patch = (data: Parameters<typeof updateConfig.mutate>[0]["data"]) => {
    if (!name) return;
    updateConfig.mutate({ project: name, data });
  };

  return (
    <div className="space-y-10">
      <section>
        <SectionLabel tone="red">{t("STUDIO CONFIG // PREFERENCES")}</SectionLabel>
        <h1 className="mt-4 max-w-[14ch] display-impact">{t("SETTINGS")}</h1>
        <p className="mt-5 lead-pulp max-w-[44rem]">
          {t("Studio-wide preferences and, when a project is active, its pipeline configuration.")}
        </p>
      </section>

      <section>
        <SectionDivider number={1} label="STUDIO" />
        <Card className="mt-5 px-5">
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
        </Card>
      </section>

      {name && (
        <section>
          <SectionDivider number={2} label={`PROJECT · ${name.toUpperCase()}`} />
          <Card className="mt-5 px-5">
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

            <Row label={t("IMAGE MODEL")}>
              <TextField
                value={config?.image_model ?? ""}
                onChange={(e) => patch({ image_model: e.target.value })}
                placeholder="flux-1.1-pro"
                disabled={!config || updating}
                className="max-w-sm bg-bristol"
              />
            </Row>
          </Card>
        </section>
      )}
    </div>
  );
}
