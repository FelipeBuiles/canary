import { useQuery } from "@tanstack/react-query";
import { getAccountModelSettings } from "../../api/modelSettings";
import { ApiError } from "../../api/client";
import { useI18n } from "../../i18n";
import { SelectField } from "../ui/Field";
import { SettingsRow } from "../ui/SettingsLayout";
import { Button } from "../ui/Button";

/** Lazy mounted inside the development-only creation controls. */
export default function ProjectModelControls({ selections, onChange, disabled }: {
  selections: Record<string, string>;
  onChange: (selections: Record<string, string>) => void;
  disabled: boolean;
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
  const mixed = (settings.funding_groups ?? []).filter((group) => new Set(group.stages.map((stage) => settings.models.find((model) => model.id === effective[stage])?.funding ?? "api")).size > 1);
  return <div className="space-y-3 pb-4">
    <p className="font-body text-sm leading-6 text-ink-muted">{t("Leave a step on account settings, or pin a model for this project. Your account settings will not change.")}</p>
    <p className="font-body text-sm leading-6 text-ink-muted">{t("API models use provider billing; Codex models use your local Codex subscription.")}</p>
    {mixed.length > 0 && <p role="status" className="text-sm leading-6">{t("These linked steps must use the same billing source before you can run them:")} {mixed.map((group) => t(group.label)).join("; ")}. {t("You can use different models within the same billing source.")}</p>}
    {settings.stages.map((stage) => {
      const inherited = settings.models.find((model) => model.id === settings.selections[stage.id]);
      const selected = settings.models.find((model) => model.id === effective[stage.id]);
      return <SettingsRow key={stage.id} label={t(stage.label)}>
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
  </div>;
}
