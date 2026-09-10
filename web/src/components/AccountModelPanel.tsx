import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getAccountModelSettings, updateAccountModelSettings } from "../api/modelSettings";
import { ApiError } from "../api/client";
import { useI18n } from "../i18n";
import { Surface } from "./ui/Surface";
import { SelectField } from "./ui/Field";
import { SettingsRow } from "./ui/SettingsLayout";
import { Button } from "./ui/Button";

const QUERY_KEY = ["account-model-settings"];
const STAGE_HINTS: Record<string, string> = {
  extract: "Read the source and build the Story Bible.",
  brief: "Propose the adaptation brief.",
  adapt: "Write the adaptation and exact dialogue.",
  plan: "Allocate the adaptation and lettering to pages.",
  prompt: "Suggest styles and rewrite asset instructions.",
  image: "Generate style proofs, cast references, and covers.",
  draw: "Generate complete, lettered comic pages.",
  ocr: "Read rendered lettering for exact text checks.",
  visual_review: "Compare artwork against approved references.",
};

/** Mounted only in a development build. The API independently enforces its gate. */
export function AccountModelPanel() {
  const { t } = useI18n();
  const client = useQueryClient();
  const query = useQuery({ queryKey: QUERY_KEY, queryFn: getAccountModelSettings, retry: false });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: updateAccountModelSettings,
    onSuccess: (settings) => {
      client.setQueryData(QUERY_KEY, settings);
      setDraft({});
      // Estimates and project status depend on account model choices.
      void client.invalidateQueries({ predicate: (item) => item.queryKey[0] !== QUERY_KEY[0] });
    },
  });

  if (query.isPending) return <p role="status">{t("Loading model settings…")}</p>;
  if (query.isError) {
    const unavailable = query.error instanceof ApiError && [403, 404].includes(query.error.status);
    return <Surface padding="lg" border="soft" shadow="none">
      <p role={unavailable ? "status" : "alert"} className="font-body text-sm leading-6">
        {unavailable ? t("Model controls are available only on a development server.") : query.error.message}
      </p>
      {!unavailable && <Button className="mt-4" variant="outline" onClick={() => { void query.refetch(); }} disabled={query.isFetching}>{t("Try again")}</Button>}
    </Surface>;
  }
  if (!query.data.enabled) return <p role="status">{t("Model controls are available only on a development server.")}</p>;

  const settings = query.data;
  const changes = Object.fromEntries(Object.entries(draft).filter(([stage, model]) => settings.selections[stage] !== model));
  const changed = Object.keys(changes).length > 0;
  const selections = { ...settings.selections, ...draft };
  const mixedGroups = (settings.funding_groups ?? []).filter((group) => new Set(group.stages.map((stage) => settings.models.find((model) => model.id === selections[stage])?.funding ?? "api")).size > 1);
  return <form aria-label={t("Account model settings")} onSubmit={(event) => {
    event.preventDefault();
    if (changed && !save.isPending) save.mutate(changes);
  }} className="space-y-5">
    <header>
      <h2 className="font-display text-2xl font-black tracking-tight">{t("Models for your account")}</h2>
      <p className="mt-2 max-w-prose font-body text-sm leading-6 text-ink-muted">{t("Choose account defaults for each part of production. New work uses these defaults unless a project has its own model choice.")}</p>
      <p className="mt-2 max-w-prose font-body text-sm leading-6 text-ink-muted">{t("Changing the Draw model requires a new edition or project. Existing pages are never switched automatically.")}</p>
      <p className="mt-2 max-w-prose font-body text-sm leading-6 text-ink-muted">{t("Saving settings does not start generation. API models use provider billing; Codex models use your local Codex subscription.")}</p>
      {settings.codex_enabled === false && <p className="mt-2 max-w-prose font-body text-sm leading-6 text-ink-muted">{t("Codex is disabled on this server. Start local development with --codex to enable its model choices.")}</p>}
      {mixedGroups.length > 0 && <p role="status" className="mt-3 max-w-prose font-body text-sm leading-6">{t("These linked steps must use the same billing source before you can run them:")} {mixedGroups.map((group) => t(group.label)).join("; ")}. {t("You can use different models within the same billing source.")}</p>}
    </header>
    <Surface border="soft" shadow="none">
      {settings.stages.map((stage) => {
        const selected = settings.models.find((model) => model.id === selections[stage.id]);
        return <SettingsRow key={stage.id} label={t(stage.label)} hint={t(STAGE_HINTS[stage.id] ?? "")}>
        <SelectField
          name={stage.id}
          aria-label={t(stage.label)}
          value={draft[stage.id] ?? settings.selections[stage.id]}
          disabled={save.isPending}
          onChange={(event) => {
            setDraft((previous) => ({ ...previous, [stage.id]: event.target.value }));
            save.reset();
          }}
          className="w-full bg-bristol font-body text-sm"
        >
          {(["api", "codex_subscription"] as const).map((funding) => {
            const choices = stage.model_ids.filter((id) => (settings.models.find((model) => model.id === id)?.funding ?? "api") === funding);
            return choices.length > 0 && <optgroup key={funding} label={t(funding === "api" ? "API billing" : "Codex subscription")}>
              {choices.map((id) => {
                const model = settings.models.find((option) => option.id === id);
                return <option key={id} value={id} disabled={model?.available === false}>{model?.label ?? id}</option>;
              })}
            </optgroup>;
          })}
        </SelectField>
        <p className="mt-2 font-body text-xs leading-5 text-ink-muted">{selected?.provider} · {t(selected?.funding === "codex_subscription" ? "Codex subscription" : "API billing")}</p>
        {selected?.description && <p className="mt-1 font-body text-xs leading-5 text-ink-muted">{t(selected.description)}</p>}
      </SettingsRow>;
      })}
    </Surface>
    {save.isError && <p role="alert" className="font-body text-sm text-hero-red">{save.error.message}</p>}
    {save.isSuccess && <p role="status" className="font-body text-sm">{t("Account models saved. New jobs will use these choices.")}</p>}
    <div className="flex flex-wrap items-center gap-3">
      <Button type="submit" disabled={!changed || save.isPending}>{t(save.isPending ? "Saving…" : "Save models")}</Button>
      {changed && <Button variant="outline" type="button" disabled={save.isPending} onClick={() => { setDraft({}); save.reset(); }}>{t("Discard changes")}</Button>}
    </div>
  </form>;
}
