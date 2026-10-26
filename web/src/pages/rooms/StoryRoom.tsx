import { ErrorNotice } from "../../components/composites/ErrorNotice";
import { accountIdentity } from "../../lib/accountEpoch";
import { castCharacters } from "../../lib/castRoster";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
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
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { FieldLabel, TextAreaField, TextField } from "../../components/ui/Field";
import { BriefSection } from "../../components/composites/BriefSection";
import { StoryBibleEditor, type EntityFocus } from "../../components/story/StoryBibleEditor";
import { BookStrip, BookStripPanel } from "../../components/parts/BookStrip";
import { partStartDescription } from "../../lib/partProgress";
import { splitProjectKey } from "../../api/projectScope";
import { Check } from "lucide-react";
import { CharacterTurns, ExactWords, MustHappen } from "../../components/story/BriefMustKeep";
import { dominantScript, groupEventsBySequence, strayWords } from "../../components/story/briefGrouping";
import { narrativeScenes } from "../../components/story/storyPhrases";
import { useI18n } from "../../i18n";
import type { AdaptationBrief, PartSummary, StoryBible, StoryDecision } from "../../types/api";

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

const BRIEF_FIELD_LABELS: Partial<Record<keyof AdaptationBrief, string>> = {
  story_promises: "STORY PROMISES", themes: "THEMES", point_of_view: "POINT OF VIEW",
  narrator_treatment: "NARRATOR TREATMENT", tone: "TONE", ambiguities: "AMBIGUITIES TO PRESERVE",
  motifs: "MOTIFS", protected_language: "PROTECTED LANGUAGE", essential_events: "ESSENTIAL EVENTS",
  character_turns: "CHARACTER TURNS", desired_emphasis: "DESIRED EMPHASIS",
  target_page_min: "Page target: from", target_page_max: "Page target: to",
};

type DirectionKey = "tone" | "story_promises" | "themes" | "desired_emphasis" | "point_of_view" | "narrator_treatment" | "ambiguities" | "motifs";

/** Guidance Adapt reads but never checks, in reading order. */
const DIRECTION: [DirectionKey, string][] = [
  ["tone", "Tone"], ["story_promises", "Story promises"], ["themes", "Themes"], ["desired_emphasis", "Emphasis"],
  ["point_of_view", "Point of view"], ["narrator_treatment", "Narrator"], ["ambiguities", "Keep ambiguous"], ["motifs", "Motifs"],
];

/** [section id, label, count, items needing a look]. */
type OutlineItem = [string, string, number?, number?];

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
  const [params, setParams] = useSearchParams();
  // Cast's "Edit details" and old #story-bible links land on the Story Bible.
  const view = params.get("view") ?? (focus || window.location.hash === "#story-bible" ? "bible" : "brief");
  function showView(next: "brief" | "bible") {
    const search = new URLSearchParams(params);
    search.set("view", next);
    setParams(search, { replace: true });
  }
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
  const [directionOpen, setDirectionOpen] = useState<DirectionKey | null>("tone");
  const [skippedCount, setSkippedCount] = useState(0);
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

  const bible = data.story_bible;
  const scenes = narrativeScenes(bible.scenes);
  const cast = castCharacters(bible);
  const facts = [
    t("{count, plural, one {# scene} other {# scenes}}", { count: scenes.length }),
    t("{count, plural, one {# character} other {# characters}}", { count: cast.length }),
    t("{count, plural, one {# place} other {# places}}", { count: bible.locations.length }),
    bible.props.length > 0 ? t("{count, plural, one {# prop} other {# props}}", { count: bible.props.length }) : undefined,
  ].filter(Boolean).join(" · ");
  const unmatched = savedBrief.unmatched_protected_language ?? [];
  const script = dominantScript([...draft.essential_events, ...draft.character_turns, ...draft.story_promises, draft.tone]);
  const strayEvents = draft.essential_events.filter((event) => strayWords(event, script).length > 0).length
    + draft.character_turns.filter((turn) => strayWords(turn, script).length > 0).length;
  const mustKeep: OutlineItem[] = [
    ["essential-events", t("What must happen"), count(draft.essential_events), strayEvents],
    ["character-turns", t("How characters change"), count(draft.character_turns)],
    ["protected-language", t("Exact words"), count(draft.protected_language), unmatched.length],
  ];
  const direction = DIRECTION.map(([key, label]): OutlineItem => [key.replaceAll("_", "-"), t(label), count(draft[key])]);
  const keptEvents = groupEventsBySequence(draft.essential_events.filter((event) => event.trim()), bible);
  const saveState = busy ? t("Saving brief…") : dirty ? restored ? t("Restored unsaved draft") : t("Unsaved changes") : t("All changes saved");

  return (
    <RoomShell project={id} bleed>
      <RoomHeader title={t("Story")} lead={facts} />

      <div className="flex min-h-13 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-ink-black/12 px-4 py-2 sm:px-6 studio-desktop:px-5">
        <div role="group" aria-label={t("Story view")} className="inline-flex border border-ink-black/25 bg-bristol">
          {(["brief", "bible"] as const).map((key) => (
            <button key={key} type="button" aria-pressed={view === key} onClick={() => showView(key)}
              className={`min-h-8 px-3.5 font-meta text-[0.8125rem] font-medium ${view === key ? "bg-ink-black text-pulp-paper" : "text-ink-soft hover:bg-surface-container hover:text-ink-black"}`}>
              {key === "brief" ? t("Brief") : t("Story Bible")}
            </button>
          ))}
        </div>
        {multipart && currentPart && <span className="font-meta text-xs text-ink-muted">
          {t("Part {number} of {count}", { number: currentPart.ordinal, count: parts.length })} · {currentPart.title}
        </span>}
        {view === "brief" && <div className="ml-auto flex items-center gap-3">
          <p role="status" className="inline-flex items-center gap-1.5 font-meta text-xs text-ink-muted">
            {!dirty && !busy && <Check size={13} strokeWidth={2.6} aria-hidden="true" className="text-ready" />}
            {saveState}
          </p>
          <Button type="submit" form="adaptation-brief" size="sm" variant="outline" disabled={busy || !dirty || invalidRange || conflict}>{t("Save brief")}</Button>
        </div>}
      </div>

      {view === "bible" ? (
        <div className="flex min-h-[36rem] flex-1 flex-col studio-desktop:min-h-0">
          <StoryBibleEditor project={id} story={bible} focus={focus} onFocusClosed={onFocusClosed} />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <nav aria-label={t("Brief sections")} className="hidden w-52 shrink-0 overflow-y-auto border-r border-ink-black/10 py-5 pl-2 studio-desktop:block">
            <OutlineGroup label={t("Must keep")} items={mustKeep} />
            <OutlineGroup label={t("Direction")} items={direction} onPick={(key) => setDirectionOpen(key.replaceAll("-", "_") as DirectionKey)} />
          </nav>

          <div className="benday-paper min-w-0 flex-1 overflow-y-auto px-3 py-5 sm:px-6 sm:py-7">
            <div className="mx-auto flex max-w-[76rem] flex-col gap-5 xl:flex-row xl:items-start">
              <article className="min-w-0 flex-1 border border-ink-black/14 bg-bristol px-5 pb-12 pt-8 shadow-[0_18px_40px_-24px_rgba(27,28,21,0.35)] sm:px-10 sm:pt-10 xl:max-w-[48rem]">
                <section aria-label={t("SOURCE MANUSCRIPT")}>
                  <p className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("Adaptation brief")}</p>
                  <h2 className="mt-2.5 break-words font-display text-[2.25rem] font-black uppercase leading-[0.92] tracking-[-0.035em] text-ink-black sm:text-[2.875rem]">{bible.title}</h2>
                  <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1 font-meta text-[0.8125rem] text-ink-soft">
                    {bible.author && <span>{t("BY")} {bible.author}</span>}
                    <span aria-hidden="true" className="h-0.5 w-6 bg-hero-red" />
                    <button type="button" onClick={() => showView("bible")} aria-label={t("Explore extracted story")}
                      className="text-ink-muted underline decoration-ink-black/25 underline-offset-4 hover:text-hero-red">
                      {t("{count, plural, one {# scene} other {# scenes}}", { count: scenes.length })} · {t("Story Bible")}
                    </button>
                  </div>
                  {multipart && currentPart && <p className="mt-4 font-body text-sm text-ink-muted">
                    {t("This brief covers Part {number}: {title}. Review its direction, then edit anything you want your comic to keep.", { number: currentPart.ordinal, title: currentPart.title })}
                  </p>}
                  {multipart && <div className="mt-4"><BookStrip project={id} parts={parts} tone="paper" /></div>}
                </section>

                {earlierDrafts.length > 0 && (
                  <section className="mt-6 space-y-3" aria-label={t("Earlier unsaved drafts")}>
                    <p className="font-body text-sm text-ink-muted">{t("An earlier draft was preserved. Review or copy it below; it has not been applied to the current brief.")}</p>
                    {earlierDrafts.map((entry) => {
                      const label = t("Unsaved draft from revision {revision}", { revision: String(entry.revision) });
                      const text = Object.entries(entry.changes).map(([key, value]) =>
                        `${t(BRIEF_FIELD_LABELS[key as keyof AdaptationBrief] ?? key)}\n${Array.isArray(value) ? value.join("\n") : String(value)}`,
                      ).join("\n\n");
                      return <details key={`${entry.revision}:${entry.contentSha}`} className="border border-ink-black/14 bg-surface-container px-4">
                        <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm font-semibold">{label}</summary>
                        <TextAreaField aria-label={label} value={text} readOnly rows={10} onFocus={(event) => event.currentTarget.select()} />
                        <div className="my-4 flex flex-wrap gap-2">
                          <Button size="sm" variant="outline" onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(text);
                              setCopyMessage(t("Draft copied"));
                            } catch {
                              setCopyMessage(t("Select the preserved text above and copy it with your keyboard or device menu."));
                            }
                          }}>{t("Copy draft")}</Button>
                          <Button size="sm" variant="outline" onClick={() => setDiscardCandidate(entry)}>{t("Discard draft")}</Button>
                        </div>
                      </details>;
                    })}
                    {copyMessage && <p role="status" className="font-body text-sm text-ink-muted">{copyMessage}</p>}
                  </section>
                )}

                <form id="adaptation-brief" onSubmit={save} className="mt-8">
                  <h2 className="sr-only">{t("ADAPTATION BRIEF")}</h2>
                  <div className="space-y-3 empty:hidden">
                    {saveError && <ErrorNotice error={saveError} operation="save" />}
                    {storageError && <p role="alert" className="font-body text-sm text-hero-red">{t("Draft recovery is unavailable in this browser. Save before leaving.")}</p>}
                    {conflict && <p role="alert" className="font-body text-sm text-hero-red">{t("This brief changed elsewhere. Your draft is preserved; reload to review the latest revision before saving.")}</p>}
                    {invalidRange && <p role="alert" className="font-body text-sm text-hero-red">{t("Choose a minimum of at least 1 page and a maximum no smaller than the minimum.")}</p>}
                  </div>
                  <fieldset disabled={busy} className="space-y-8">
                    <legend className="sr-only">{t("ADAPTATION BRIEF")}</legend>
                    <MustHappen events={draft.essential_events} onChange={(value) => change("essential_events", value)} story={bible} script={script} onSkippedChange={setSkippedCount} />
                    <CharacterTurns turns={draft.character_turns} onChange={(value) => change("character_turns", value)} characters={cast} script={script} />
                    <ExactWords lines={draft.protected_language} unmatched={unmatched} onChange={(value) => change("protected_language", value)} />
                    <section id="brief-direction" aria-labelledby="direction-title" className="scroll-mt-6 border-t border-ink-black/12 pt-8">
                      <div className="flex items-baseline gap-2.5">
                        <h3 id="direction-title" className="font-display text-[1.5rem] font-black uppercase leading-none tracking-[-0.025em]">{t("Direction")}</h3>
                        <span className="font-meta text-[0.8125rem] text-ink-muted">{t("Guidance, not rules")}</span>
                      </div>
                      <p className="mb-4 mt-2 font-body text-sm leading-[1.5] text-ink-soft">{t("Shapes the tone and staging. Nothing checks the comic against it.")}</p>
                      <div className="border border-ink-black/14 bg-pulp-paper">
                        {DIRECTION.map(([key, label]) => <BriefSection key={key} collapsible id={key.replaceAll("_", "-")} title={t(BRIEF_FIELD_LABELS[key]!)} heading={t(label)}
                          open={directionOpen === key} onOpenChange={(open) => setDirectionOpen(open ? key : null)}
                          value={draft[key]} onChange={(value) => change(key, Array.isArray(draft[key]) ? splitLines(value) : value)} />)}
                      </div>
                    </section>
                  </fieldset>
                </form>
              </article>

              <aside aria-label={t("Shape of the book")} className="flex shrink-0 flex-col gap-4 xl:sticky xl:top-0 xl:w-72">
                <section aria-labelledby="before-approve" className="border border-ink-black/14 bg-bristol px-4 pb-2 pt-3.5">
                  <h3 id="before-approve" className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("Before you approve")}</h3>
                  <ul className="mt-2">
                    {strayEvents > 0 && <ApproveCheck warn target="essential-events" action={t("Review")}>
                      <b className="font-semibold">{t("{count, plural, one {# must-have has a stray word.} other {# must-haves have a stray word.}}", { count: strayEvents })}</b>
                    </ApproveCheck>}
                    {unmatched.length > 0 && <ApproveCheck warn target="protected-language" action={t("Review")}>
                      <b className="font-semibold">{t("{count, plural, one {# line isn't in the book.} other {# lines aren't in the book.}}", { count: unmatched.length })}</b> {t("It won't be kept word for word.")}
                    </ApproveCheck>}
                    <ApproveCheck>{t("Adapt will hold to {events} events, {turns} turns and {lines} exact lines.", {
                      events: count(draft.essential_events) ?? 0, turns: count(draft.character_turns) ?? 0, lines: count(draft.protected_language) ?? 0,
                    })}</ApproveCheck>
                    {skippedCount > 0 && <ApproveCheck>{t("{count, plural, one {# event can be skipped.} other {# events can be skipped.}}", { count: skippedCount })}</ApproveCheck>}
                  </ul>
                </section>
                <section className="border border-ink-black/14 bg-bristol px-4 pb-4 pt-3.5">
                  <h3 className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("Target length")}</h3>
                  <p className="mt-2 font-display text-[1.75rem] font-black uppercase leading-none tracking-[-0.03em]">
                    {invalidRange ? "—" : draft.target_page_min === draft.target_page_max
                      ? t("{count, plural, one {# page} other {# pages}}", { count: draft.target_page_min })
                      : `${draft.target_page_min}–${t("{count, plural, one {# page} other {# pages}}", { count: draft.target_page_max })}`}
                  </p>
                  <p className="mb-3 mt-1.5 font-body text-xs leading-[1.5] text-ink-muted">{t("A guide. The book can run shorter or longer to keep the story's pacing.")}</p>
                  <fieldset disabled={busy} className="flex items-end gap-2">
                    <div className="min-w-0 flex-1"><FieldLabel htmlFor="minimum-pages" className="text-xs"><span className="sr-only">{t("Page target")}: </span>{t("from")}</FieldLabel><TextField id="minimum-pages" type="number" min={1} value={draft.target_page_min} onChange={(event) => change("target_page_min", Number(event.target.value))} /></div>
                    <span aria-hidden="true" className="pb-2.5 text-ink-muted">–</span>
                    <div className="min-w-0 flex-1"><FieldLabel htmlFor="maximum-pages" className="text-xs"><span className="sr-only">{t("Page target")}: </span>{t("to")}</FieldLabel><TextField id="maximum-pages" type="number" min={draft.target_page_min} value={draft.target_page_max} onChange={(event) => change("target_page_max", Number(event.target.value))} /></div>
                  </fieldset>
                </section>
                <StoryShape story={bible} onOpen={() => showView("bible")}
                  mustHaves={keptEvents.length > 1 ? new Map(keptEvents.map((group) => [group.sequence!.number, group.items.length])) : undefined} />
              </aside>
            </div>
          </div>
        </div>
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

      <ApprovalBar
        next={t("Choose the look for every page")}
        primaryLabel={dirty ? t("Save & approve brief") : t("Approve brief")}
        onPrimary={approve}
        primaryDisabled={busy || invalidRange || conflict || stageStatus !== "awaiting_review"}
        busy={busy}
        note={dirty ? t("Your visible draft will be saved before approval.") : draft.status === "approved" ? t("Brief approved") : t("All changes saved")}
      />
    </RoomShell>
  );
}

function count(value: string | string[]): number | undefined {
  return Array.isArray(value) ? value.filter((item) => item.trim()).length : undefined;
}

function OutlineGroup({ label, items, onPick }: { label: string; items: OutlineItem[]; onPick?: (id: string) => void }) {
  const { t } = useI18n();
  return (
    <div className="mb-5">
      <p className="px-3.5 pb-2 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{label}</p>
      <ul>
        {items.map(([id, name, n, warn]) => (
          <li key={id}>
            <a href={`#brief-${id}`} onClick={(event) => {
              event.preventDefault();
              onPick?.(id);
              // Let an opened direction row render before scrolling to it.
              requestAnimationFrame(() => document.getElementById(`brief-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
            }}
              className="flex min-h-8 items-center justify-between gap-2 border-l-2 border-transparent pl-3.5 pr-3 font-meta text-[0.8125rem] text-ink-soft hover:border-hero-red hover:bg-surface-container hover:text-ink-black">
              <span>{name}</span>
              <span className="flex items-center gap-1.5">
                {!!warn && <span title={t("{count, plural, one {# to check} other {# to check}}", { count: warn })}
                  className="inline-flex h-[1.125rem] min-w-[1.125rem] items-center justify-center border border-ink-black bg-narrator-gold px-1 text-[0.65625rem] font-bold text-ink-black">{warn}</span>}
                {n !== undefined && <span className="text-[0.6875rem] tabular-nums text-ink-muted">{n}</span>}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One line of the approval checklist; `target` scrolls to the section to fix. */
function ApproveCheck({ warn = false, target, action, children }: { warn?: boolean; target?: string; action?: string; children: ReactNode }) {
  return (
    <li className="flex gap-2.5 border-t border-ink-black/9 py-2.5 font-body text-[0.8125rem] leading-[1.45] first:border-t-0">
      <span aria-hidden="true" className={warn
        ? "mt-px flex h-[1.125rem] w-[1.125rem] shrink-0 items-center justify-center border border-ink-black bg-narrator-gold font-meta text-[0.6875rem] font-bold"
        : "mt-px flex h-[1.125rem] w-[1.125rem] shrink-0 items-center justify-center bg-ready/15 text-ready"}>
        {warn ? "!" : <Check size={12} strokeWidth={3} />}
      </span>
      <span className="min-w-0">
        {children}
        {target && action && <> <a href={`#brief-${target}`} onClick={(event) => {
          event.preventDefault();
          document.getElementById(`brief-${target}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
        }} className="underline underline-offset-2 hover:text-hero-red">{action}</a></>}
      </span>
    </li>
  );
}

/** The part's sequences at a glance, sized by how many scenes each holds. */
function StoryShape({ story, onOpen, mustHaves }: { story: StoryBible; onOpen: () => void; mustHaves?: Map<number, number> }) {
  const { t } = useI18n();
  const scenes = narrativeScenes(story.scenes);
  const ids = new Set(scenes.map((scene) => scene.id));
  const sequences = (story.sequences ?? [])
    .map((sequence) => ({ ...sequence, size: sequence.scenes.filter((id) => ids.has(id)).length }))
    .filter((sequence) => sequence.size > 0);
  const largest = Math.max(1, ...sequences.map((sequence) => sequence.size));
  const characters = castCharacters(story);
  return (
    <section className="border border-ink-black/14 bg-bristol px-4 pb-2 pt-3.5">
      <div className="flex items-baseline justify-between">
        <h3 className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("The story's shape")}</h3>
        <span className="font-meta text-[0.6875rem] text-ink-muted">{t("{count, plural, one {# scene} other {# scenes}}", { count: scenes.length })}</span>
      </div>
      {sequences.length > 0 && <ol className="mt-2.5">
        {sequences.map((sequence) => (
          <li key={`${sequence.part_id}-${sequence.number}`}>
            <button type="button" onClick={onOpen} className="group grid w-full grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-2.5 border-t border-ink-black/10 py-2.5 text-left">
              <span className="inline-flex h-[1.375rem] items-center justify-center border border-ink-black bg-pulp-paper font-meta text-[0.6875rem] font-bold">{sequence.number}</span>
              <span className="min-w-0">
                <span className="block font-meta text-[0.8125rem] font-semibold leading-[1.3] group-hover:text-hero-red">{sequence.title}</span>
                <span className="mt-0.5 block font-body text-[0.6875rem] text-ink-muted">
                  {t("{count, plural, one {# scene} other {# scenes}}", { count: sequence.size })}
                  {mustHaves && ` · ${t("{count, plural, one {# must-have} other {# must-haves}}", { count: mustHaves.get(sequence.number) ?? 0 })}`}
                </span>
                <span aria-hidden="true" className="mt-1.5 block h-1 bg-surface-variant"><span className="block h-full bg-ink-black" style={{ width: `${Math.round((sequence.size / largest) * 100)}%` }} /></span>
              </span>
            </button>
          </li>
        ))}
      </ol>}
      <div className="border-t border-ink-black/10 py-3">
        <p className="font-body text-xs leading-[1.5] text-ink-soft">
          {[
            t("{count, plural, one {# character} other {# characters}}", { count: characters.length }),
            t("{count, plural, one {# place} other {# places}}", { count: story.locations.length }),
            t("{count, plural, one {# prop} other {# props}}", { count: story.props.length }),
          ].join(" · ")}
        </p>
        <Button size="sm" variant="outline" fullWidth className="mt-2.5" onClick={onOpen}>{t("Open Story Bible")}</Button>
      </div>
    </section>
  );
}
