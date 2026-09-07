import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useStory,
  useUpdateBrief,
} from "../../api/queries";
import {
  ApprovalBar,
  ConfirmModal,
  EntityCard,
  RoomHeader,
  RoomShell,
  SectionHeader,
  StagePlaceholder,
} from "../../components/composites";
import { Button } from "../../components/ui/Button";
import { FieldLabel, TextAreaField, TextField } from "../../components/ui/Field";
import { Surface } from "../../components/ui/Surface";
import { useI18n } from "../../i18n";
import type { AdaptationBrief, StoryDecision } from "../../types/api";

function lines(value: string[]): string {
  return value.join("\n");
}

function splitLines(value: string): string[] {
  return value.split("\n");
}

export function StoryRoom() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const { data: status, isLoading: statusLoading, error: statusError } = useProjectStatus(id);
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

  if (isLoading) {
    // Keep the status observer in StagePlaceholder mounted when loading ends.
    // Remounting it on a status error starts retryOnMount and hides the error.
    if (stageStatus === "pending" || stageStatus === "running" || stageStatus === "failed") {
      return (
        <RoomShell project={id ?? ""}>
          <StagePlaceholder project={id ?? ""} stage="brief" status={stageStatus} />
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
        <StagePlaceholder
          project={id ?? ""}
          stage={stage}
          status={status}
          error={stageInfo?.error}
          errorDetail={stageInfo?.error_detail}
          loadError={errorMessage}
          allowPendingStart
        />
      </RoomShell>
    );
  }
  return <StoryEditor key={id} id={id} data={data} brief={brief} stageStatus={stageStatus} />;
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
  target_page_min: "Minimum pages", target_page_max: "Maximum pages",
};

function StoryEditor({ id, data, brief, stageStatus }: {
  id: string;
  data: StoryDecision;
  brief: AdaptationBrief;
  stageStatus: string;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const updateBrief = useUpdateBrief();
  const approveBrief = useApproveStage();
  const [savedBrief, setSavedBrief] = useState(brief);
  const storageKey = `scenewright:brief-drafts:v1:${encodeURIComponent(id)}`;
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
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const operation = useRef(false);
  const draft = { ...savedBrief, ...changes };
  const dirty = Object.entries(changes).some(([key, value]) => JSON.stringify(value) !== JSON.stringify(savedBrief[key as keyof AdaptationBrief]));
  const conflict = brief.revision > savedBrief.revision || (brief.revision === savedBrief.revision && brief.content_sha256 !== savedBrief.content_sha256);
  const invalidRange = !Number.isInteger(draft.target_page_min) || !Number.isInteger(draft.target_page_max) || draft.target_page_min < 1 || draft.target_page_max < draft.target_page_min;
  const busy = saving || approveBrief.isPending;
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
        setSaveError(error.message);
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
          onError: (error) => { operation.current = false; setSaveError(error.message); },
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

      <Surface border="soft" shadow="none" padding="md">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="font-meta text-[0.62rem] font-bold tracking-[0.1em] text-ink-muted">
              {t("SOURCE MANUSCRIPT")}
            </div>
            <h2 className="mt-2 font-display text-[2rem] font-black uppercase leading-none tracking-[-0.035em]">
              {data.story_bible.title}
            </h2>
            <p className="mt-2 font-body text-sm font-semibold text-ink-muted">
              {t("BY")} {data.story_bible.author}
            </p>
          </div>
          <p className="max-w-[34rem] text-pretty font-body text-sm leading-6 text-ink-black/70">
            {data.story_bible.total_scenes} {t("scenes")} · {data.story_bible.characters.length} {t("characters")} ·{" "}
            {data.story_bible.locations.length} {t("places")}
          </p>
        </div>
      </Surface>
      {earlierDrafts.length > 0 && (
        <section className="space-y-4" aria-label={t("Earlier unsaved drafts")}>
          <p className="font-body text-sm text-ink-muted">{t("An earlier draft was preserved. Review or copy it below; it has not been applied to the current brief.")}</p>
          {earlierDrafts.map((entry) => {
            const label = t("Unsaved draft from revision {revision}").replace("{revision}", String(entry.revision));
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
          description={t("This is the approved editorial contract for the whole book. One item per line.")}
        />
        <p role="status" className="font-meta text-sm text-ink-muted">
          {busy ? t("Saving brief…") : dirty ? restored ? t("Restored unsaved draft") : t("Unsaved changes") : t("All changes saved")}
        </p>
        {saveError && <p role="alert" className="font-body text-sm text-hero-red">{saveError}</p>}
        {storageError && <p role="alert" className="font-body text-sm text-hero-red">{t("Draft recovery is unavailable in this browser. Save before leaving.")}</p>}
        {conflict && <p role="alert" className="font-body text-sm text-hero-red">{t("This brief changed elsewhere. Your draft is preserved; reload to review the latest revision before saving.")}</p>}
        {invalidRange && <p role="alert" className="font-body text-sm text-hero-red">{t("Choose a minimum of at least 1 page and a maximum no smaller than the minimum.")}</p>}
        <fieldset disabled={busy} className="space-y-8">
          <legend className="sr-only">{t("ADAPTATION BRIEF")}</legend>
        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <FieldLabel htmlFor="minimum-pages">{t("Minimum pages")}</FieldLabel>
            <TextField id="minimum-pages" type="number" min={1} value={draft.target_page_min} onChange={(event) => change("target_page_min", Number(event.target.value))} />
          </div>
          <div>
            <FieldLabel htmlFor="maximum-pages">{t("Maximum pages")}</FieldLabel>
            <TextField id="maximum-pages" type="number" min={draft.target_page_min} value={draft.target_page_max} onChange={(event) => change("target_page_max", Number(event.target.value))} />
          </div>
        </div>

        <div className="grid gap-5 lg:grid-cols-2">
          <EntityCard>
            <FieldLabel htmlFor="story-promises">{t("STORY PROMISES")}</FieldLabel>
            <TextAreaField
              id="story-promises"
              value={lines(draft.story_promises)}
              onChange={(event) => change("story_promises", splitLines(event.target.value))}
            />
          </EntityCard>
          <EntityCard>
            <FieldLabel htmlFor="essential-events">{t("ESSENTIAL EVENTS")}</FieldLabel>
            <TextAreaField
              id="essential-events"
              value={lines(draft.essential_events)}
              onChange={(event) => change("essential_events", splitLines(event.target.value))}
            />
            <FieldLabel htmlFor="character-turns" className="mt-5 block">{t("CHARACTER TURNS")}</FieldLabel>
            <TextAreaField
              id="character-turns"
              value={lines(draft.character_turns)}
              onChange={(event) => change("character_turns", splitLines(event.target.value))}
            />
          </EntityCard>
          <EntityCard>
            <FieldLabel htmlFor="tone">{t("TONE")}</FieldLabel>
            <TextAreaField
              id="tone"
              value={draft.tone}
              onChange={(event) => change("tone", event.target.value)}
            />
            <FieldLabel htmlFor="emphasis" className="mt-5 block">{t("DESIRED EMPHASIS")}</FieldLabel>
            <TextAreaField
              id="emphasis"
              value={lines(draft.desired_emphasis)}
              onChange={(event) => change("desired_emphasis", splitLines(event.target.value))}
            />
          </EntityCard>
        </div>
        <details>
          <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm font-bold">{t("More editorial details")}</summary>
          <div className="grid gap-5 lg:grid-cols-2">
          <EntityCard>
            <FieldLabel htmlFor="themes">{t("THEMES")}</FieldLabel>
            <TextAreaField
              id="themes"
              value={lines(draft.themes)}
              onChange={(event) => change("themes", splitLines(event.target.value))}
            />
          </EntityCard>
          <EntityCard>
            <FieldLabel htmlFor="point-of-view">{t("POINT OF VIEW")}</FieldLabel>
            <TextAreaField
              id="point-of-view"
              value={draft.point_of_view}
              onChange={(event) => change("point_of_view", event.target.value)}
            />
            <FieldLabel htmlFor="narrator-treatment" className="mt-5 block">
              {t("NARRATOR TREATMENT")}
            </FieldLabel>
            <TextAreaField
              id="narrator-treatment"
              value={draft.narrator_treatment}
              onChange={(event) => change("narrator_treatment", event.target.value)}
            />
          </EntityCard>
          <EntityCard>
            <FieldLabel htmlFor="motifs">{t("MOTIFS")}</FieldLabel>
            <TextAreaField
              id="motifs"
              value={lines(draft.motifs)}
              onChange={(event) => change("motifs", splitLines(event.target.value))}
            />
            <FieldLabel htmlFor="protected-language" className="mt-5 block">{t("PROTECTED LANGUAGE")}</FieldLabel>
            <TextAreaField
              id="protected-language"
              value={lines(draft.protected_language)}
              onChange={(event) => change("protected_language", splitLines(event.target.value))}
            />
          </EntityCard>
          <EntityCard>
            <FieldLabel htmlFor="ambiguities">{t("AMBIGUITIES TO PRESERVE")}</FieldLabel>
            <TextAreaField
              id="ambiguities"
              value={lines(draft.ambiguities)}
              onChange={(event) => change("ambiguities", splitLines(event.target.value))}
            />
          </EntityCard>
        </div>

        </details>
        <Button type="submit" variant="outline" disabled={busy || !dirty || invalidRange || conflict}>
          {t("SAVE BRIEF")}
        </Button>
        </fieldset>
      </form>
      <details>
        <summary className="min-h-11 cursor-pointer py-3 font-meta text-sm font-bold">{t("Review extracted characters, places & story order")}</summary>
        <div className="space-y-8 pt-4">
      <section>
        <SectionHeader
          variant="underline"
          title={t("CHARACTERS & PLACES")}
          description={t("The visual facts Scenewright carries into the Look and every complete page.")}
        />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.story_bible.characters.map((character) => (
            <EntityCard key={character.id} padding="cozy">
              <h3 className="font-display text-xl font-black uppercase">{character.name}</h3>
              <p className="mt-2 font-body text-sm leading-6 text-ink-black/70">
                {character.visual_anchor}
              </p>
            </EntityCard>
          ))}
          {data.story_bible.locations.map((location) => (
            <EntityCard key={location.id} padding="cozy">
              <h3 className="font-display text-xl font-black uppercase">{location.name}</h3>
              <p className="mt-2 font-body text-sm leading-6 text-ink-black/70">
                {location.visual_anchor}
              </p>
            </EntityCard>
          ))}
        </div>
      </section>

      <section>
        <SectionHeader
          variant="underline"
          title={t("STORY ORDER")}
          description={t("A readable outline of the source before it becomes a page plan.")}
        />
        <ol className="grid gap-3 lg:grid-cols-2">
          {data.story_bible.scenes.map((scene, index) => (
            <li key={scene.id}>
              <Surface border="soft" shadow="none" padding="md">
                <p className="font-meta text-[0.62rem] font-bold tracking-[0.1em] text-hero-red">
                  {t("SCENE")} {String(index + 1).padStart(2, "0")}
                </p>
                <h3 className="mt-2 font-display text-lg font-black uppercase">{scene.title}</h3>
                <p className="mt-2 font-body text-sm leading-6 text-ink-black/70">{scene.summary}</p>
              </Surface>
            </li>
          ))}
        </ol>
      </section>
        </div>
      </details>

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
