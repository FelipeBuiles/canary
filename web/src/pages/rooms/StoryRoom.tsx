import { ErrorNotice } from "../../components/composites/ErrorNotice";
import { accountIdentity } from "../../lib/accountEpoch";
import { castCharacters } from "../../lib/castRoster";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useStory,
  useUpdateBrief,
} from "../../api/queries";
import {
  ApprovalBar,
  ConfirmModal,
  RoomHeader,
  RoomShell,
  SectionHeader,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { FieldLabel, TextAreaField, TextField } from "../../components/ui/Field";
import { BriefSection } from "../../components/composites/BriefSection";
import { StoryBibleEditor, type EntityFocus } from "../../components/story/StoryBibleEditor";
import { BookStrip, BookStripPanel } from "../../components/parts/BookStrip";
import { partStartDescription } from "../../lib/partProgress";
import { splitProjectKey } from "../../api/projectScope";
import { ArrowDownRight, ChevronRight } from "lucide-react";
import { useI18n } from "../../i18n";
import type { AdaptationBrief, PartSummary, StoryDecision } from "../../types/api";

function splitLines(value: string): string[] {
  return value.split("\n");
}

/** `?edit=characters:char_001` opens that entry's editor (Cast's "Edit details"). */
function useEntityFocus(): [EntityFocus | null, () => void] {
  const [params, setParams] = useSearchParams();
  const [kind, id] = (params.get("edit") ?? "").split(":");
  const focus: EntityFocus | null = (kind === "characters" || kind === "locations" || kind === "props") && id
    ? { kind, id } : null;
  return [focus, () => {
    const next = new URLSearchParams(params);
    next.delete("edit");
    setParams(next, { replace: true });
  }];
}

export function StoryRoom() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const [focus, clearFocus] = useEntityFocus();
  const { data: status, isLoading: statusLoading, error: statusError } = useProjectStatus(id);
  const activeJobs = status?.active_jobs;
  const extract = status?.stages.extract;
  const briefStage = status?.stages.brief;
  const stageStatus = briefStage?.status ?? "pending";
  // The story artifact only exists once Extract is complete and Brief is
  // ready — a 404 before that is the normal pre-stage state, not a failure.
  const storyReady =
    extract?.status === "complete" && (stageStatus === "awaiting_review" || stageStatus === "complete");
  const { data, isLoading: storyLoading, error: storyQueryError } = useStory(id, storyReady);
  // Ignore a disabled query's stale error while the artifact isn't ready yet,
  // but never hide a genuine status failure behind the gate.
  const error = storyReady ? storyQueryError : (statusError ?? null);
  const isLoading = statusLoading || (storyReady && storyLoading);
  const brief = data?.brief;
  const parts = status?.parts ?? [];
  const contents = parts.length > 1 && id ? <BookStripPanel project={id} parts={parts} /> : null;
  const startDescription = id ? partStartDescription(id, parts, t) : undefined;

  if (isLoading) {
    // Keep the status observer in StagePlaceholder mounted when loading ends.
    // Remounting it on a status error starts retryOnMount and hides the error.
    if (stageStatus === "pending" || stageStatus === "running" || stageStatus === "failed") {
      return (
        <RoomShell project={id ?? ""}>
          {contents}
          <StagePlaceholder project={id ?? ""} stage="brief" status={stageStatus} activeJobs={status?.active_jobs} firstPhase={extract} />
        </RoomShell>
      );
    }
    return (
      <RoomShell
        project={id ?? ""}
        isLoading
        loadingText={t("PREPARING YOUR STORY…")}
      />
    );
  }

  // !storyReady gates the placeholder so cached data from a previous run never
  // leaks into the editor while a rerun is in flight.
  if (!id || error || !storyReady || !data || !brief) {
    const stage = extract?.status === "complete" ? "brief" : "extract";
    const status = extract?.status === "complete" ? stageStatus : (extract?.status ?? "pending");
    const errorMessage = !id
      ? t("Project id is missing from the route.")
      : error instanceof Error
        ? error.message
        : error
          ? t("The development server returned an error while loading this stage.")
          : status === "complete" || status === "awaiting_review"
            ? t("The development server reported this stage ready, but its data was missing from the response.")
            : null;
    const stageInfo = status === "failed"
      ? (stage === "extract" ? extract : briefStage)
      : undefined;
    return (
      <RoomShell project={id ?? ""}>
        {contents}
        <StagePlaceholder
          activeJobs={activeJobs}
          project={id ?? ""}
          stage={stage}
          status={status}
          startedAt={(stage === "extract" ? extract : briefStage)?.started_at}
          firstPhase={stage === "brief" ? extract : undefined}
          error={stageInfo?.error}
          errorDetail={stageInfo?.error_detail}
          errorCode={stageInfo?.error_code}
          loadError={errorMessage}
          allowPendingStart
          startDescription={startDescription}
        />
        {/* The shared Story Bible stays editable while this part waits for extraction. */}
        {id && <StoryBibleEditor project={id} focus={focus} onFocusClosed={clearFocus} />}
      </RoomShell>
    );
  }
  return <StoryEditor key={id} id={id} data={data} brief={brief} parts={parts} stageStatus={stageStatus} focus={focus} onFocusClosed={clearFocus} />;
}

interface StoredBriefDraft {
  revision: number;
  contentSha: string;
  changes: Partial<AdaptationBrief>;
}

/** Phrases the Brief offered as protected language that the book does not contain. */
function UnmatchedProtectedLanguage({ phrases }: { phrases: string[] }) {
  const { t } = useI18n();
  if (phrases.length === 0) return null;
  return (
    <section aria-label={t("Not found in the book")} className="border-l-4 border-hero-red/60 bg-surface-container px-4 py-3">
      <h4 className="font-body text-sm font-semibold leading-6">{t("Not found in the book")}</h4>
      <p className="mt-1 font-body text-xs leading-5 text-ink-muted">
        {t("These lines are not protected because the book does not contain them word for word. To keep one exactly, add the book’s wording to Protected language.")}
      </p>
      <ul className="mt-3 space-y-2">
        {phrases.map((phrase, index) => <li key={index} className="whitespace-pre-wrap break-words font-body text-sm leading-6">{phrase}</li>)}
      </ul>
    </section>
  );
}

const BRIEF_FIELD_LABELS: Partial<Record<keyof AdaptationBrief, string>> = {
  story_promises: "STORY PROMISES", themes: "THEMES", point_of_view: "POINT OF VIEW",
  narrator_treatment: "NARRATOR TREATMENT", tone: "TONE", ambiguities: "AMBIGUITIES TO PRESERVE",
  motifs: "MOTIFS", protected_language: "PROTECTED LANGUAGE", essential_events: "ESSENTIAL EVENTS",
  character_turns: "CHARACTER TURNS", desired_emphasis: "DESIRED EMPHASIS",
  target_page_min: "Page target: from", target_page_max: "Page target: to",
};

function StoryEditor({ id, data, brief, parts, stageStatus, focus, onFocusClosed }: {
  id: string;
  data: StoryDecision;
  brief: AdaptationBrief;
  parts: PartSummary[];
  stageStatus: string;
  focus: EntityFocus | null;
  onFocusClosed: () => void;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const currentPart = parts.find((part) => part.id === splitProjectKey(id).part);
  const multipart = parts.length > 1;
  const updateBrief = useUpdateBrief();
  const approveBrief = useApproveStage();
  const [savedBrief, setSavedBrief] = useState(brief);
  const storageKey = `scenewright:brief-drafts:v2:${accountIdentity ?? "signed-out"}:${encodeURIComponent(id)}`;
  const [{ drafts: storedDrafts, error: storageError }, setDraftStorage] = useState<{ drafts: StoredBriefDraft[]; error: boolean }>(() => {
    try {
      const stored = sessionStorage.getItem(storageKey);
      const parsed: unknown = stored ? JSON.parse(stored) : [];
      if (!Array.isArray(parsed)) return { drafts: [], error: false };
      const recovered: StoredBriefDraft[] = [];
      for (const entry of parsed) {
        if (!entry || typeof entry !== "object" || !Number.isInteger(entry.revision) || typeof entry.contentSha !== "string" || !entry.changes || typeof entry.changes !== "object" || Array.isArray(entry.changes)) continue;
        const recoveredChanges: Partial<AdaptationBrief> = {};
        for (const [key, value] of Object.entries(entry.changes)) {
          if (!Object.hasOwn(BRIEF_FIELD_LABELS, key)) continue;
          const original = brief[key as keyof AdaptationBrief];
          if (Array.isArray(original) ? Array.isArray(value) && value.every((item) => typeof item === "string") : typeof original === typeof value && original !== undefined) {
            Object.assign(recoveredChanges, { [key]: value });
          }
        }
        if (Object.keys(recoveredChanges).length) recovered.push({ revision: entry.revision, contentSha: entry.contentSha, changes: recoveredChanges });
      }
      return { drafts: recovered, error: false };
    } catch { return { drafts: [], error: true }; }
  });
  const [changes, setChanges] = useState<Partial<AdaptationBrief>>(() =>
    storedDrafts.find((entry) => entry.revision === brief.revision && entry.contentSha === brief.content_sha256)?.changes ?? {},
  );
  const [discardCandidate, setDiscardCandidate] = useState<StoredBriefDraft | null>(null);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const earlierDrafts = storedDrafts.filter((entry) => entry.revision !== savedBrief.revision || entry.contentSha !== savedBrief.content_sha256);
  const [restored, setRestored] = useState(() => Object.keys(changes).length > 0);
  const [saveError, setSaveError] = useState<Error | string | null>(null);
  const [saving, setSaving] = useState(false);
  const operation = useRef(false);
  const draft = { ...savedBrief, ...changes };
  const dirty = Object.entries(changes).some(([key, value]) => JSON.stringify(value) !== JSON.stringify(savedBrief[key as keyof AdaptationBrief]));
  const conflict = brief.revision > savedBrief.revision || (brief.revision === savedBrief.revision && brief.content_sha256 !== savedBrief.content_sha256);
  const invalidRange = !Number.isInteger(draft.target_page_min) || !Number.isInteger(draft.target_page_max) || draft.target_page_min < 1 || draft.target_page_max < draft.target_page_min;
  const busy = saving || approveBrief.isPending;
  if (conflict && !dirty && !busy) {
    setSavedBrief(brief);
    // Reverted fields may still be present in changes; do not overlay the fresh brief.
    setChanges({});
    setRestored(false);
  }
  useEffect(() => {
    if (!dirty) return;
    function beforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  function storeDrafts(drafts: StoredBriefDraft[]) {
    try {
      if (drafts.length) sessionStorage.setItem(storageKey, JSON.stringify(drafts));
      else sessionStorage.removeItem(storageKey);
      setDraftStorage({ drafts, error: false });
    } catch {
      // Keep the complete recovery set in memory even when browser storage fails.
      setDraftStorage({ drafts, error: true });
    }
  }

  function change<K extends keyof AdaptationBrief>(key: K, value: AdaptationBrief[K]) {
    const nextChanges = { ...changes, [key]: value };
    const drafts = storedDrafts.filter((entry) => entry.revision !== savedBrief.revision || entry.contentSha !== savedBrief.content_sha256);
    if (Object.entries(nextChanges).some(([field, nextValue]) => JSON.stringify(nextValue) !== JSON.stringify(savedBrief[field as keyof AdaptationBrief]))) {
      drafts.push({ revision: savedBrief.revision, contentSha: savedBrief.content_sha256, changes: nextChanges });
    }
    setChanges(nextChanges);
    storeDrafts(drafts);
  }

  function persist(then?: () => void) {
    if (operation.current || invalidRange || conflict) return;
    if (!dirty) { then?.(); return; }
    operation.current = true;
    setSaving(true);
    setSaveError(null);
    const normalized = { ...changes };
    for (const key of Object.keys(normalized) as (keyof AdaptationBrief)[]) {
      const value = normalized[key];
      if (Array.isArray(value)) Object.assign(normalized, { [key]: value.map((item) => item.trim()).filter(Boolean) });
    }
    updateBrief.mutate({
      project: id,
      expectedRevision: savedBrief.revision,
      changes: normalized,
    }, {
      onSuccess: (saved) => {
        const remainingDrafts = storedDrafts.filter((entry) => entry.revision !== savedBrief.revision || entry.contentSha !== savedBrief.content_sha256);
        storeDrafts(remainingDrafts);
        setSavedBrief(saved);
        setChanges({});
        setRestored(false);
        operation.current = false;
        setSaving(false);
        then?.();
      },
      onError: (error) => {
        operation.current = false;
        setSaving(false);
        setSaveError(error);
      },
    });
  }

  function save(event: FormEvent) {
    event.preventDefault();
    persist();
  }

  function approve() {
    if (busy || stageStatus !== "awaiting_review") return;
    persist(() => {
      operation.current = true;
      approveBrief.mutate(
        { project: id, stage: "brief" },
        {
          onSuccess: () => navigate(`/project/${encodeURIComponent(id)}/styles`),
          onError: (error) => { operation.current = false; setSaveError(error); },
        },
      );
    });
  }

  return (
    <RoomShell project={id}>
      <RoomHeader
        kicker={t("STORY")}
        title={t("CONFIRM THE STORY & BRIEF")}
        lead={t("Review what Scenewright found and set the promises that every page must keep.")}
      />

      <section className={`relative overflow-hidden bg-ink-black p-6 text-pulp-paper shadow-paper ${multipart ? "md:px-8 md:py-7" : "md:p-10"}`} aria-label={t("SOURCE MANUSCRIPT")}>
        {multipart && currentPart && <p className="font-meta text-xs font-bold uppercase tracking-[0.12em] text-narrator-gold">
          {t("Part {number} of {count}", { number: currentPart.ordinal, count: parts.length })} · {currentPart.title}
        </p>}
        <h2 className={`break-words font-display font-black uppercase leading-[1.02] tracking-[-0.035em] ${multipart ? "mt-2 text-3xl sm:text-4xl" : "max-w-[20ch] text-4xl sm:text-5xl xl:text-6xl"}`}>{data.story_bible.title}</h2>
        <div className={`flex flex-wrap items-end justify-between gap-x-6 ${multipart ? "mt-3 gap-y-2" : "mt-7 gap-y-6"}`}>
          <p className="font-body text-sm">{t("BY")} {data.story_bible.author}</p>
          <a href="#story-bible" className="inline-flex min-h-11 items-center gap-3 font-meta text-xs leading-6 text-pulp-paper underline decoration-narrator-gold underline-offset-8 hover:text-narrator-gold" aria-label={t("Explore extracted story")}>{data.story_bible.total_scenes} {t("scenes")} · {castCharacters(data.story_bible).length} {t("characters")} · {data.story_bible.locations.length} {t("places")}<ArrowDownRight size={18} aria-hidden="true" /></a>
        </div>
        {multipart && <div className="mt-6"><BookStrip project={id} parts={parts} tone="ink" /></div>}
      </section>
      {earlierDrafts.length > 0 && (
        <section className="space-y-4" aria-label={t("Earlier unsaved drafts")}>
          <p className="font-body text-sm text-ink-muted">{t("An earlier draft was preserved. Review or copy it below; it has not been applied to the current brief.")}</p>
          {earlierDrafts.map((entry) => {
            const label = t("Unsaved draft from revision {revision}", { revision: String(entry.revision) });
            const text = Object.entries(entry.changes).map(([key, value]) =>
              `${t(BRIEF_FIELD_LABELS[key as keyof AdaptationBrief] ?? key)}\n${Array.isArray(value) ? value.join("\n") : String(value)}`,
            ).join("\n\n");
            return <details key={`${entry.revision}:${entry.contentSha}`} className="bg-surface-container p-4">
              <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm font-bold">{label}</summary>
              <TextAreaField aria-label={label} value={text} readOnly rows={10} onFocus={(event) => event.currentTarget.select()} />
              <div className="mt-4 flex flex-wrap gap-3">
                <Button variant="outline" onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(text);
                    setCopyMessage(t("Draft copied"));
                  } catch {
                    setCopyMessage(t("Select the preserved text above and copy it with your keyboard or device menu."));
                  }
                }}>{t("Copy draft")}</Button>
                <Button variant="outline" onClick={() => setDiscardCandidate(entry)}>{t("Discard draft")}</Button>
              </div>
            </details>;
          })}
          {copyMessage && <p role="status" className="font-body text-sm text-ink-muted">{copyMessage}</p>}
        </section>
      )}
      <ConfirmModal
        open={!!discardCandidate}
        title={t("Discard earlier draft?")}
        body={t("This removes only the preserved local draft. The current brief will not change.")}
        confirmLabel={t("Discard draft")}
        destructive
        onClose={() => setDiscardCandidate(null)}
        onConfirm={() => {
          storeDrafts(storedDrafts.filter((entry) => entry !== discardCandidate));
          setDiscardCandidate(null);
        }}
      />


      <form onSubmit={save} className="space-y-8">
        <SectionHeader
          variant="underline"
          title={t("ADAPTATION BRIEF")}
          description={multipart && currentPart
            ? t("This brief covers Part {number}: {title}. Review its direction, then edit anything you want your comic to keep.", { number: currentPart.ordinal, title: currentPart.title })
            : t("Make this story yours. Review the direction below, then edit anything you want your comic to keep.")}
          actions={<>
            <p role="status" className="font-meta text-xs text-ink-muted">
              {busy ? t("Saving brief…") : dirty ? restored ? t("Restored unsaved draft") : t("Unsaved changes") : t("All changes saved")}
            </p>
            <Button type="submit" size="sm" variant="outline" disabled={busy || !dirty || invalidRange || conflict}>{t("SAVE BRIEF")}</Button>
          </>}
        />
        {saveError && <ErrorNotice error={saveError} operation="save" />}
        {storageError && <p role="alert" className="font-body text-sm text-hero-red">{t("Draft recovery is unavailable in this browser. Save before leaving.")}</p>}
        {conflict && <p role="alert" className="font-body text-sm text-hero-red">{t("This brief changed elsewhere. Your draft is preserved; reload to review the latest revision before saving.")}</p>}
        {invalidRange && <p role="alert" className="font-body text-sm text-hero-red">{t("Choose a minimum of at least 1 page and a maximum no smaller than the minimum.")}</p>}
        <fieldset disabled={busy} className="space-y-8">
          <legend className="sr-only">{t("ADAPTATION BRIEF")}</legend>
          {/* Two independent stacks, not a row grid: short sections never leave
              holes beside long ones. What must happen reads in the wide column;
              how it should feel sits beside it. */}
          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-6">
              <BriefSection id="story-promises" title={t("STORY PROMISES")} value={draft.story_promises} onChange={(value) => change("story_promises", splitLines(value))} featured />
              <BriefSection id="essential-events" title={t("ESSENTIAL EVENTS")} value={draft.essential_events} onChange={(value) => change("essential_events", splitLines(value))} numbered />
              <BriefSection id="character-turns" title={t("CHARACTER TURNS")} value={draft.character_turns} onChange={(value) => change("character_turns", splitLines(value))} />
            </div>
            <div className="min-w-0 space-y-6">
              <BriefSection id="tone" title={t("TONE")} value={draft.tone} onChange={(value) => change("tone", value)} />
              <div className="bg-surface-container p-5">
                <h3 className="font-display text-xl font-black uppercase">{t("Target length")}</h3>
                <p className="mb-5 mt-2 font-body text-sm text-ink-muted">{t("A flexible guide. The finished book may be shorter or longer to preserve the story and its pacing.")}</p>
                <div className="grid grid-cols-2 gap-4">
                  <div><FieldLabel htmlFor="minimum-pages">{t("Page target: from")}</FieldLabel><TextField id="minimum-pages" type="number" min={1} value={draft.target_page_min} onChange={(event) => change("target_page_min", Number(event.target.value))} /></div>
                  <div><FieldLabel htmlFor="maximum-pages">{t("Page target: to")}</FieldLabel><TextField id="maximum-pages" type="number" min={draft.target_page_min} value={draft.target_page_max} onChange={(event) => change("target_page_max", Number(event.target.value))} /></div>
                </div>
              </div>
              <BriefSection id="themes" title={t("THEMES")} value={draft.themes} onChange={(value) => change("themes", splitLines(value))} />
              <BriefSection id="desired-emphasis" title={t("DESIRED EMPHASIS")} value={draft.desired_emphasis} onChange={(value) => change("desired_emphasis", splitLines(value))} />
            </div>
          </div>
          {/* Open when a protected phrase was set aside, so the author sees why. */}
          <details open={(savedBrief.unmatched_protected_language?.length ?? 0) > 0 || undefined} className="group border-t-2 border-ink-black/15 pt-2">
            <summary className="flex min-h-11 cursor-pointer list-none flex-wrap items-baseline gap-x-4 gap-y-1 py-3 [&::-webkit-details-marker]:hidden">
              <span className="inline-flex items-center gap-2 font-display text-xl font-black uppercase">
                <ChevronRight size={20} aria-hidden="true" className="text-hero-red transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                {t("More editorial details")}
              </span>
              <span className="font-body text-sm text-ink-muted">{t("Point of view, narrator, motifs, protected language and ambiguities.")}</span>
            </summary>
            <div className="mt-4 grid items-start gap-6 lg:grid-cols-2">
              <div className="min-w-0 space-y-6">
                {(["point_of_view", "narrator_treatment", "ambiguities"] as const).map((key) => <BriefSection key={key} id={key.replaceAll("_", "-")} title={t(BRIEF_FIELD_LABELS[key]!)} value={draft[key]} onChange={(value) => change(key, Array.isArray(draft[key]) ? splitLines(value) : value)} />)}
              </div>
              <div className="min-w-0 space-y-6">
                {(["motifs", "protected_language"] as const).map((key) => <BriefSection key={key} id={key.replaceAll("_", "-")} title={t(BRIEF_FIELD_LABELS[key]!)} value={draft[key]} onChange={(value) => change(key, splitLines(value))} />)}
                <UnmatchedProtectedLanguage phrases={savedBrief.unmatched_protected_language ?? []} />
              </div>
            </div>
          </details>
        </fieldset>
      </form>
      <StoryBibleEditor project={id} story={data.story_bible} focus={focus} onFocusClosed={onFocusClosed} />

      <ApprovalBar
        next={t("Choose the visual direction for every complete page")}
        primaryLabel={dirty ? t("SAVE & APPROVE BRIEF — CONTINUE") : t("APPROVE BRIEF — CONTINUE")}
        onPrimary={approve}
        primaryDisabled={busy || invalidRange || conflict || stageStatus !== "awaiting_review"}
        busy={busy}
        note={dirty ? t("Your visible draft will be saved before approval.") : draft.status === "approved" ? t("Brief approved") : t("All changes saved")}
      />
    </RoomShell>
  );
}
