import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useStory,
  useUpdateBrief,
} from "../../api/queries";
import {
  ApprovalBar,
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
import type { AdaptationBrief } from "../../types/api";

function lines(value: string[]): string {
  return value.join("\n");
}

function splitLines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function StoryRoom() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
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
  const updateBrief = useUpdateBrief();
  const approveBrief = useApproveStage();
  const brief = data?.brief;
  const [changes, setChanges] = useState<Partial<AdaptationBrief>>({});
  const draft = brief ? { ...brief, ...changes } : null;

  if (isLoading) {
    return (
      <RoomShell
        project={id ?? ""}
        isLoading
        loadingText={t("PREPARING YOUR STORY…")}
        loadingStage="brief"
        loadingStageStatus={stageStatus}
      />
    );
  }

  // !storyReady gates the placeholder so cached data from a previous run never
  // leaks into the editor while a rerun is in flight.
  if (!id || error || !storyReady || !data || !draft) {
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
        />
      </RoomShell>
    );
  }

  function change<K extends keyof AdaptationBrief>(key: K, value: AdaptationBrief[K]) {
    setChanges((current) => ({ ...current, [key]: value }));
  }

  function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || !id) return;
    updateBrief.mutate({
      project: id,
      expectedRevision: draft.revision,
      changes: {
        story_promises: draft.story_promises,
        themes: draft.themes,
        point_of_view: draft.point_of_view,
        narrator_treatment: draft.narrator_treatment,
        tone: draft.tone,
        ambiguities: draft.ambiguities,
        motifs: draft.motifs,
        protected_language: draft.protected_language,
        essential_events: draft.essential_events,
        character_turns: draft.character_turns,
        desired_emphasis: draft.desired_emphasis,
        target_page_min: draft.target_page_min,
        target_page_max: draft.target_page_max,
      },
    });
  }

  function approve() {
    if (!id) return;
    approveBrief.mutate(
      { project: id, stage: "brief" },
      { onSuccess: () => navigate(`/project/${encodeURIComponent(id)}/styles`) },
    );
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

      <form onSubmit={save} className="space-y-8">
        <SectionHeader
          variant="underline"
          title={t("ADAPTATION BRIEF")}
          description={t("This is the approved editorial contract for the whole book. One item per line.")}
        />

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

        <Surface border="hard" shadow="paper" padding="md">
          <div className="flex flex-wrap items-end gap-5">
            <div className="min-w-36 flex-1">
              <FieldLabel htmlFor="minimum-pages">{t("Minimum pages")}</FieldLabel>
              <TextField
                id="minimum-pages"
                aria-label={t("Minimum pages")}
                type="number"
                min={1}
                value={draft.target_page_min}
                onChange={(event) => change("target_page_min", Number(event.target.value))}
              />
            </div>
            <div className="min-w-36 flex-1">
              <FieldLabel htmlFor="maximum-pages">{t("Maximum pages")}</FieldLabel>
              <TextField
                id="maximum-pages"
                aria-label={t("Maximum pages")}
                type="number"
                min={draft.target_page_min}
                value={draft.target_page_max}
                onChange={(event) => change("target_page_max", Number(event.target.value))}
              />
            </div>
            <Button
              type="submit"
              variant="outline"
              disabled={updateBrief.isPending || draft.target_page_min > draft.target_page_max}
            >
              {t("SAVE BRIEF")}
            </Button>
          </div>
        </Surface>
      </form>

      <ApprovalBar
        next={t("Choose the visual direction for every complete page")}
        primaryLabel={t("APPROVE BRIEF — CONTINUE")}
        onPrimary={approve}
        primaryDisabled={approveBrief.isPending || stageStatus !== "awaiting_review"}
        busy={approveBrief.isPending}
        note={draft.status === "approved" ? t("Brief approved") : undefined}
      />
    </RoomShell>
  );
}
