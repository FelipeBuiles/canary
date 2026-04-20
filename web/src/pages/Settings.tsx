import { useParams } from "react-router-dom";
import { useProjectConfig, useUpdateProjectConfig } from "../api/queries";
import { SectionLabel } from "../components/SectionLabel";
import { SectionDivider } from "../components/SectionDivider";
import { Card } from "../components/ui/Card";
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

function Select<T extends string>({
  value,
  onChange,
  options,
  disabled,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      disabled={disabled}
      className="w-full max-w-sm border-[2px] border-ink-black bg-bristol px-3 py-2 font-meta text-[0.72rem] tracking-[0.1em] disabled:opacity-60"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function Toggle({ value, onChange, disabled }: { value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      disabled={disabled}
      className={`relative inline-flex h-7 w-12 items-center border-[2px] border-ink-black transition-colors ${
        value ? "bg-hero-red" : "bg-bristol"
      } disabled:opacity-60`}
    >
      <span
        className={`block h-4 w-4 border border-ink-black transition-transform ${
          value ? "translate-x-[24px] bg-bristol" : "translate-x-[2px] bg-ink-black"
        }`}
      />
    </button>
  );
}

function TextInput({
  value,
  onChange,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="w-full max-w-sm border-[2px] border-ink-black bg-bristol px-3 py-2 font-body text-[0.82rem] disabled:opacity-60"
    />
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
            <Select
              value={language}
              onChange={(v) => setLanguage(v as LanguageCode)}
              options={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
            />
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
              <Select
                value={config?.target_language ?? "en"}
                onChange={(v) => patch({ target_language: v as LanguageCode })}
                options={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
                disabled={!config || updating}
              />
            </Row>

            <Row
              label={t("DEV / DEMO MODE")}
              hint={t("Uses the faster image model, fewer steps, and smaller generated files for quick testing.")}
            >
              <Toggle
                value={!!config?.dev_mode}
                onChange={(v) => patch({ dev_mode: v })}
                disabled={!config || updating}
              />
            </Row>

            <Row
              label={t("COMIC THEME")}
              hint={t("Leave empty for default style. Override to set visual identity of the comic.")}
            >
              <TextInput
                value={config?.comic_theme ?? ""}
                onChange={(v) => patch({ comic_theme: v })}
                placeholder="golden-age noir"
                disabled={!config || updating}
              />
            </Row>

            <Row label={t("STYLE TEMPLATE")}>
              <TextInput
                value={config?.style_template ?? ""}
                onChange={(v) => patch({ style_template: v })}
                placeholder="pulp-comic"
                disabled={!config || updating}
              />
            </Row>

            <Row label={t("IMAGE MODEL")}>
              <TextInput
                value={config?.image_model ?? ""}
                onChange={(v) => patch({ image_model: v })}
                placeholder="flux-1.1-pro"
                disabled={!config || updating}
              />
            </Row>
          </Card>
        </section>
      )}
    </div>
  );
}
