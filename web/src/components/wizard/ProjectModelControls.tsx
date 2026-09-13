import { useQuery } from "@tanstack/react-query";
import { getAccountModelSettings } from "../../api/modelSettings";
import { ApiError } from "../../api/client";
import { useI18n } from "../../i18n";
import { SelectField } from "../ui/Field";
import { SettingsRow } from "../ui/SettingsLayout";
import { Button } from "../ui/Button";

/** Shared development-only controls for project creation and settings. */
export default function ProjectModelControls({ selections, onChange, disabled, stageIds }: {
  selections: Record<string, string>;
  onChange: (selections: Record<string, string>) => void;
  disabled: boolean;
  stageIds?: string[];
}) {
  const { t } = useI18n();
  const query = useQuery({ queryKey: ["account-model-settings"], queryFn: getAccountModelSettings, retry: false });
  if (query.isPending) return <p role="status">{t("Loading model settings…")}</p>;
  if (query.isError) {
    if (query.error instanceof ApiError && [403, 404].includes(query.error.status)) return null;
    return <div className="pb-4"><p role="status">{t("Model choices could not load. You can still create the project using account models.")}</p><Button type="button" variant="outline" onClick={() => void query.refetch()} disabled={query.isFetching}>{t("Try again")}</Button></div>;
  }
  if (!query.data.enabled) return null;
  const settings = query.data;
  const effective = { ...settings.selections, ...selections };
  return <div className="space-y-3 pb-4">
    <p className="font-body text-sm leading-6 text-ink-muted">{t("Leave a step on account settings, or pin a model for this project. Your account settings will not change.")}</p>
    <p className="font-body text-sm leading-6 text-ink-muted">{t("Mix API and Codex models freely. Only API calls use credits.")}</p>
    {settings.stages.filter((stage) => !stageIds || stageIds.includes(stage.id)).map((stage) => {
      const inherited = settings.models.find((model) => model.id === settings.selections[stage.id]);
      const selected = settings.models.find((model) => model.id === effective[stage.id]);
      return <SettingsRow key={stage.id} label={t(stage.label)} hint={t(stage.description ?? "")} stacked={!!stageIds}>
        <SelectField aria-label={t(stage.label)} value={selections[stage.id] ?? ""} disabled={disabled} className="w-full bg-bristol font-body text-sm" onChange={(event) => {
          const next = { ...selections };
          if (event.target.value) next[stage.id] = event.target.value;
          else delete next[stage.id];
          onChange(next);
        }}>
          <option value="">{t("Account setting")}: {inherited?.label ?? settings.selections[stage.id]}</option>
          {(["api", "codex_subscription"] as const).map((funding) => {
            const choices = settings.models.filter((model) => stage.model_ids.includes(model.id) && (model.funding ?? "api") === funding);
            return choices.length > 0 && <optgroup key={funding} label={t(funding === "api" ? "API billing" : "Codex subscription")}>
              {choices.map((model) => <option key={model.id} value={model.id} disabled={model.available === false}>{model.label}</option>)}
            </optgroup>;
          })}
        </SelectField>
        <p className="mt-2 text-xs leading-5 text-ink-muted">{selected?.provider} · {t(selected?.funding === "codex_subscription" ? "Codex subscription" : "API billing")}</p>
        {selected?.description && <p className="mt-1 text-xs leading-5 text-ink-muted">{t(selected.description)}</p>}
      </SettingsRow>;
    })}
    {!stageIds && <p className="font-body text-sm leading-6 text-ink-muted">{t("8. Finish packages your comic for export. It has no separate model to choose.")}</p>}
  </div>;
}
