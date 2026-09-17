import { useCallback, useEffect, useId, useRef, startTransition, useState } from "react";
import { useMutation, useMutationState, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, isInsufficientCreditsError } from "../../api/client";
import { getLetteringTranslationEstimate, translateProjectLettering, type LetteringLocale, type LetteringTranslationEstimate, type LetteringTranslationRequest } from "../../api/lettering";
import { useCreditBalance, useGenerationJobs } from "../../api/queries";
import type { GenerationJob } from "../../types/api";
import { LANGUAGES, useI18n } from "../../i18n";
import { maybeShowInsufficientCredits } from "../../store/insufficientCredits";
import { ConfirmDrawer } from "../composites/ConfirmDrawer";
import { Button } from "../ui/Button";
import { CreditAmount } from "../ui/CreditAmount";
import { FieldLabel, SelectField } from "../ui/Field";

interface ProjectLetteringLanguageProps {
  project: string;
  disabled: boolean;
  onApplied: () => Promise<void>;
  onBusyChange?: (busy: boolean) => void;
}

function isUnknownSubmission(error: unknown) {
  return !!error && !isInsufficientCreditsError(error)
    && (!(error instanceof ApiError) || error.status === 409 || error.status >= 500);
}

export function ProjectLetteringLanguage(props: ProjectLetteringLanguageProps) {
  return <LanguageControl key={props.project} {...props} />;
}

function LanguageControl({ project, disabled, onApplied, onBusyChange }: ProjectLetteringLanguageProps) {
  const { t, language } = useI18n();
  const qc = useQueryClient();
  const selectId = useId();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<LetteringLocale | "">("");
  const [confirmation, setConfirmation] = useState<LetteringTranslationEstimate | null>(null);
  const [refresh, setRefresh] = useState<{ id: string; status: "pending" | "complete" | "failed" } | null>(null);
  const observedTerminal = useRef<string | null>(null);
  const jobs = useGenerationJobs(project, [], true);
  const balance = useCreditBalance();
  const mutation = useMutation({
    mutationKey: ["lettering-translation", project],
    mutationFn: (request: LetteringTranslationRequest) => translateProjectLettering(project, request),
    retry: false,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["project", project, "generation-jobs"] });
      void qc.invalidateQueries({ queryKey: ["project", project, "status"] });
      void qc.invalidateQueries({ queryKey: ["credits"] });
    },
    onError: (error) => {
      maybeShowInsufficientCredits(error, { actionLabel: t("Translate project") });
      if (!isUnknownSubmission(error)) {
        void qc.invalidateQueries({ queryKey: ["project", project, "lettering-translation-estimate"] });
      }
    },
  });
  // Mutation state survives leaving the page; apiFetch retains the same paid-action
  // receipt when the result is unknown. A check replays exactly that request.
  const submissions = useMutationState({
    filters: { mutationKey: ["lettering-translation", project], exact: true },
    select: (entry) => ({
      status: entry.state.status,
      submittedAt: entry.state.submittedAt,
      error: entry.state.error,
      variables: entry.state.variables as LetteringTranslationRequest | undefined,
      data: entry.state.data as { job: GenerationJob } | undefined,
    }),
  });
  const submission = submissions.at(-1);
  let latest = submission?.data?.job ?? null;
  for (const job of jobs.data?.jobs ?? []) {
    if (job.kind !== "lettering_translation") continue;
    if (!latest || Date.parse(job.queued_at) >= Date.parse(latest.queued_at)) latest = job;
  }
  const active = latest?.status === "queued" || latest?.status === "running";
  const submissionIsLatest = !!submission && (!latest || submission.submittedAt > Date.parse(latest.queued_at));
  const submitting = mutation.isPending || (submissionIsLatest && submission?.status === "pending");
  const submissionError = submissionIsLatest && submission?.status === "error" ? submission.error : null;
  const unknown = isUnknownSubmission(submissionError);
  const refreshing = !!latest && latest.status === "complete" && (refresh?.id !== latest.id || refresh.status === "pending");
  const busy = !!active || submitting || unknown || refreshing;
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);

  const estimate = useQuery({
    queryKey: ["project", project, "lettering-translation-estimate", target],
    queryFn: () => getLetteringTranslationEstimate(project, target as LetteringLocale),
    enabled: open && !!target && !disabled && !busy && !confirmation,
    staleTime: 0,
  });
  const cost = confirmation ?? estimate.data;
  const required = cost?.reserved_credits ?? cost?.estimate_credits ?? 0;
  const insufficient = required > 0 && balance.data !== undefined && balance.data.balance_credits < required;
  const balanceUnavailable = required > 0 && (balance.isError || !balance.data);
  const unavailable = disabled || busy || !estimate.data || estimate.isError || estimate.isFetching
    || insufficient || balanceUnavailable || jobs.isPending || jobs.isError;

  const refreshProject = useCallback(async (job: GenerationJob) => {
    try {
      await qc.invalidateQueries({ predicate: (query) => query.queryKey.includes(project) || query.queryKey[0] === "credits" || query.queryKey[0] === "projects" });
      if (job.status === "complete") await onApplied();
      setRefresh({ id: job.id, status: "complete" });
    } catch {
      setRefresh({ id: job.id, status: "failed" });
    }
  }, [onApplied, project, qc]);
  useEffect(() => {
    if (!latest || (latest.status !== "complete" && latest.status !== "failed") || observedTerminal.current === latest.id) return;
    observedTerminal.current = latest.id;
    startTransition(() => { void refreshProject(latest); });
  }, [latest, refreshProject]);

  function confirmTranslation() {
    if (!confirmation || unavailable) return;
    onBusyChange?.(true);
    mutation.mutate({ target_locale: confirmation.target_locale, expected_snapshot_sha256: confirmation.snapshot_sha256 });
    setConfirmation(null);
  }

  const counts = cost ? t("{pages} pages, {elements} text elements; {count} to translate.")
    .replace("{pages}", cost.page_count.toLocaleString(language))
    .replace("{elements}", cost.element_count.toLocaleString(language))
    .replace("{count}", cost.translate_count.toLocaleString(language)) : null;
  const jobLocale = latest?.payload.target_locale;
  const jobLanguage = LANGUAGES.find((item) => item.code === jobLocale)?.label;
  const refreshFailed = !!latest && refresh?.id === latest.id && refresh.status === "failed";

  return (
    <section aria-label={t("Project language")} className="min-w-0">
      <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary className="min-h-11 cursor-pointer py-3 text-sm font-semibold text-ink-black">{t("Project language")}</summary>
        <div className="space-y-3 pb-3 text-sm leading-6">
          <p className="max-w-prose text-ink-muted">{t("Translate saved lettering across the whole project. Save drafts on every page first.")}</p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1">
              <FieldLabel htmlFor={selectId}>{t("Translate to")}</FieldLabel>
              <SelectField id={selectId} value={target} disabled={disabled || busy} onChange={(event) => {
                setTarget(event.target.value as LetteringLocale | "");
                setConfirmation(null);
              }}>
                <option value="">{t("Choose a language")}</option>
                {LANGUAGES.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
              </SelectField>
            </div>
            <Button size="sm" variant="outline" disabled={unavailable} onClick={() => setConfirmation(estimate.data ?? null)}>
              {t("Translate project")}
              {estimate.data && <CreditAmount value={estimate.data.estimate_credits} approximate label={t("credits")} />}
            </Button>
          </div>
          {disabled && !busy && <p>{t("Save your draft and wait for other project work to finish before translating.")}</p>}
          {target && !busy && estimate.isFetching && <p role="status">{t("Estimating translation…")}</p>}
          {!busy && counts && <p>{counts}</p>}
          {target && !busy && estimate.isError && <div role="alert">
            <p>{estimate.error.message}</p>
            <Button size="sm" variant="outline" disabled={disabled || estimate.isFetching} onClick={() => void estimate.refetch()}>{t("Retry estimate")}</Button>
          </div>}
          {!busy && insufficient && <p role="alert">{t("Not enough credits for the temporary hold.")} <a className="underline" href="/credits">{t("Get credits")}</a></p>}
          {!busy && balanceUnavailable && <div role="alert">
            <p>{t("Credit balance is unavailable. Check it before translating.")}</p>
            <Button size="sm" variant="outline" onClick={() => void balance.refetch()}>{t("Check balance")}</Button>
          </div>}
        </div>
      </details>
      <div className="space-y-2 text-sm leading-6" aria-live="polite">
        {submitting && <p role="status">{t("Submitting translation…")}</p>}
        {!submitting && active && <p role="status">{latest?.status === "queued" ? t("Project translation queued.") : t("Translating project…")} {jobLanguage}</p>}
        {!submitting && unknown && <div role="alert">
          <p>{t("The submission result is unknown. Check the same request before starting another translation.")}</p>
          <Button size="sm" variant="outline" onClick={() => {
            if (submission?.variables) mutation.mutate(submission.variables);
          }}>{t("Check submission")}</Button>
        </div>}
        {!submitting && submissionError && !unknown && <p role="alert">{submissionError.message}</p>}
        {latest?.status === "failed" && <div role="alert">
          <p>{t("Project translation failed.")}</p>
          <p className="break-words">{latest.error ?? t("The translation could not be completed. Request a new estimate before trying again.")}</p>
          <p>{t("Completed translation calls may still use credits. Check credit history for charges.")}</p>
        </div>}
        {refreshing && <p role="status">{t("Refreshing translated lettering…")}</p>}
        {refreshFailed && <div role="alert">
          <p>{t("The job finished, but the editor could not refresh. Save any draft, then refresh the lettering.")}</p>
          <Button size="sm" variant="outline" disabled={disabled} onClick={() => {
            if (!latest) return;
            setRefresh({ id: latest.id, status: "pending" });
            void refreshProject(latest);
          }}>{t("Refresh lettering")}</Button>
        </div>}
        {latest?.status === "complete" && refresh?.id === latest.id && refresh.status === "complete" && <p role="status">{t("Project language applied. Review lettering on every page before export.")} {jobLanguage}</p>}
        {jobs.isError && <div role="alert">
          <p>{t("Translation status is unavailable. Check again before starting another translation.")}</p>
          <Button size="sm" variant="outline" onClick={() => void jobs.refetch()}>{t("Check status")}</Button>
        </div>}
      </div>
      <ConfirmDrawer
        open={confirmation !== null}
        title={t("Translate project")}
        body={t("Translate saved wording into {language}. Existing target-language edits are kept; only missing translations are generated.")
          .replace("{language}", LANGUAGES.find((item) => item.code === confirmation?.target_locale)?.label ?? "")}
        extraBody={<div className="space-y-2 text-sm leading-6">
          <p>{counts}</p>
          <p>{t("{count} existing translations will be preserved.").replace("{count}", (confirmation?.preserved_target_count ?? 0).toLocaleString(language))}</p>
          <p>{t("Artwork and placement stay unchanged. Review the new language on every page before export.")}</p>
        </div>}
        cost={confirmation ?? undefined}
        confirmLabel={t("Translate project")}
        disabled={unavailable}
        busy={submitting}
        onConfirm={confirmTranslation}
        onClose={() => setConfirmation(null)}
      />
    </section>
  );
}
