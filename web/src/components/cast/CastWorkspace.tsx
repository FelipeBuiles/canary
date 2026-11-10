import { useContext, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ChevronRight, Plus } from "lucide-react";
import { useImageGenerationMeta, useProjectStatus } from "../../api/queries";
import { useCastFreshness, useKeepReference } from "../../api/seriesQueries";
import { useCastReference } from "../../hooks/useCastReference";
import { useGenerationTracking } from "../../hooks/useGenerationTracking";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { useImageTokens } from "../../lib/imageRefresh";
import type { AppearanceState, CastReferenceInput, GenerationJob } from "../../types/api";
import { CastRegenAction } from "../composites/CastRegenAction";
import { ErrorNotice } from "../composites/ErrorNotice";
import { ImageGenerationPreview } from "../composites/ImageGenerationPreview";
import { Button } from "../ui/Button";
import { GenerationDetailsPanel } from "../ui/GenerationDetailsModal";
import { InspectButton } from "../ui/InspectButton";
import {
  ASPECT, CastUpdatingContext, STORY_KIND, castFailureFor, lookImageUrl, lookThumbUrl, looksOf, mainImagePath, portraitUrl,
  thumbnailUrl, updatingKey, useCastSuggestion, type CastEntry, type CastKind,
} from "./castAssets";
import { AnchorSection, InspectorSection, OVERLINE, RefVersionHistory, ReferenceViews } from "./CastInspectorParts";
import { useCastEntryImage } from "./useCastEntryImage";
import { ScrollStripControls } from "../ui/ScrollStrip";
import { useScrollStrip } from "../ui/useScrollStrip";
import { versionedUrl } from "../../lib/assetVersions";

const KIND_LABEL: Record<CastKind, string> = { character: "Character", location: "Place", prop: "Prop" };

/** The looks a main-image job redraws after it (its ``with_looks`` payload). */
function redrawnLooks(job: GenerationJob | null | undefined): readonly string[] | undefined {
  const looks = job?.payload.with_looks;
  return Array.isArray(looks) ? looks.filter((look): look is string => typeof look === "string") : undefined;
}

/**
 * Each look's generation state. A look is unknown only while its own file is
 * absent; every poll changes its URL, so a failed thumbnail re-tests rather
 * than latching.
 */
function useLooks(project: string, entry: CastEntry, stageRegenerating: boolean, refreshToken: string, redrawing: readonly string[] | undefined) {
  const looks = looksOf(entry);
  const kind = entry.kind;
  const id = entry.entity.id;
  const tracking = useGenerationTracking(project, looks.length > 0);
  const { data: status } = useProjectStatus(project);
  const updating = useContext(CastUpdatingContext);
  const { data: freshness } = useCastFreshness(project, looks.length > 0);
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  // A look's own token renews when it is redrawn or restored, so its tile follows.
  const lookToken = useImageTokens();
  const identity = kind === "character" ? "char_id" : kind === "location" ? "loc_id" : "prop_id";
  const outdated = new Set((freshness?.references ?? [])
    .filter((ref) => ref.entity_id === id && ref.state_id && ref.status === "outdated" && ref.kind === STORY_KIND[kind])
    .map((ref) => ref.state_id));
  const job = (stateId: string) => tracking.status({ identity: kind === "character" ? "char_id" : "loc_id", value: `${id}:${stateId}`, currentStyle: true });
  const isUpdating = (stateId: string) => updating.has(updatingKey(STORY_KIND[kind], id, stateId));
  const version = (stateId: string) => {
    const active = job(stateId);
    // The pending marker drops when the running Cast redraws this look, so the tile reloads then.
    return encodeURIComponent(`${refreshToken}-${lookToken(JSON.stringify([project, identity, `${id}:${stateId}`]))}${active ? `-${active.id}-${active.status}` : ""}${isUpdating(stateId) ? "-updating" : ""}`);
  };
  const thumb = (stateId: string) => `${lookThumbUrl(project, kind, id, stateId)}?t=${version(stateId)}`;
  const generating = (stateId: string) => {
    const active = job(stateId);
    // A missing look is drawn by any Cast run; an existing one only while it is still pending update.
    return (stageRegenerating && (!!failed[thumb(stateId)] || isUpdating(stateId))) || active?.status === "queued" || active?.status === "running"
      || !!redrawing?.includes(stateId);
  };
  return {
    looks,
    thumb,
    generating,
    missing: (stateId: string) => !!failed[thumb(stateId)],
    markMissing: (src: string) => setFailed((current) => ({ ...current, [src]: true })),
    failure: (stateId: string) => generating(stateId) ? undefined : castFailureFor(status?.stages?.cast?.failures, id, stateId),
    outdated: (stateId: string) => outdated.has(stateId),
  };
}

/** The image under the lamp, fitted to the stage whatever its shape. */
function StageFrame({ kind, status, children }: { kind: CastKind; status?: string; children: ReactNode }) {
  const ratio = ASPECT[kind];
  return (
    // Stacked layouts have no definite height for cqh to resolve against (it
    // computes to 0), so they fit the frame to the width and a share of the screen.
    <div className="relative flex min-w-0 flex-1 items-center justify-center px-5 pb-5 pt-1 [--stage-h:70svh] [container-type:inline-size] sm:px-10 studio-desktop:min-h-0 studio-desktop:[--stage-h:100cqh] studio-desktop:[container-type:size]">
      <div data-testid="cast-stage" aria-busy={!!status} className="relative bg-ink-black shadow-[0_30px_60px_-20px_rgb(0_0_0/0.75),0_0_0_1px_rgb(252_250_237/0.12)]"
        style={{ width: `min(100cqw, calc(var(--stage-h) * ${ratio}))`, aspectRatio: String(ratio) }}>
        {children}
        {status && (
          <span role="status" className="absolute left-2.5 top-2.5 z-10 flex items-center gap-2 border border-pulp-paper/25 bg-ink-black/80 px-2.5 py-1 font-meta text-xs font-medium text-pulp-paper">
            <span aria-hidden="true" className="size-2 bg-narrator-gold motion-safe:animate-pulse" />{status}
          </span>
        )}
      </div>
    </div>
  );
}

function StageEmpty({ title, hint, tone = "muted" }: { title: string; hint?: string; tone?: "muted" | "alert" }) {
  return (
    <div className="benday-ink flex h-full w-full flex-col items-center justify-center gap-2 p-6 text-center text-pulp-paper">
      <p className={cn("font-meta text-sm font-semibold", tone === "alert" ? "text-narrator-gold" : "text-on-chrome-muted")}>{title}</p>
      {hint && <p className="max-w-[22rem] font-body text-xs leading-5 text-pulp-paper/60">{hint}</p>}
    </div>
  );
}

/**
 * One reference on the stage with its looks, and everything about it in the
 * panel beside it: description, relationships, changes and versions.
 */
export function CastWorkspace({ project, entry, sub, toolbar, stageRegenerating, characterNames, firstSceneTitle, onShow }: {
  project: string;
  entry: CastEntry;
  sub: string;
  toolbar: ReactNode;
  stageRegenerating: boolean;
  /** Names relationships point at. */
  characterNames: Map<string, string>;
  firstSceneTitle?: string;
  onShow: (kind: CastKind, id: string) => void;
}) {
  const { t } = useI18n();
  const { kind, entity } = entry;
  const image = useCastEntryImage(project, entry, stageRegenerating, true);
  const { data: status } = useProjectStatus(project);
  const [lookId, setLookId] = useState<string | null>(null);
  const [instruction, setInstruction] = useState<string | null>(null);
  const [lookInstructions, setLookInstructions] = useState<Record<string, string>>({});
  useCastSuggestion(kind, entity.id, (text) => { setLookId(null); setInstruction(text); });
  useCastSuggestion(kind, entity.id, (text, stateId) => {
    if (!stateId) return;
    setLookId(stateId);
    setLookInstructions((current) => ({ ...current, [stateId]: text }));
  }, true);
  const redrawing = redrawnLooks(image.activeJob);
  const looks = useLooks(project, entry, stageRegenerating, String(image.timestamp), redrawing);
  const look = looks.looks.find((state) => state.id === lookId) ?? null;
  // A second job handle for the selected look; it follows the selection.
  const lookRef = useCastReference(project, kind, entity.id, look?.id, !!look);
  const { data: generationMeta, isLoading: isMetaLoading } = useImageGenerationMeta(project, mainImagePath(kind, entity.id, true), !look, image.timestamp);
  const keep = useKeepReference();
  const mainFailure = !image.isGenerating && !stageRegenerating ? castFailureFor(status?.stages?.cast?.failures, entity.id, null) : undefined;
  const mainBusy = image.isSubmitting || !!image.activeJob;
  const name = entity.name;

  const submitMain = (text: string, referenceAssets: CastReferenceInput[], withLooks: boolean) => {
    if (!text.trim()) return;
    setInstruction(text.trim());
    image.regenerate(text, referenceAssets, withLooks);
  };

  const mainStage = (
    <StageFrame kind={kind} status={image.isGenerating ? (image.isQueued ? t("Queued") : t("Drawing {name}…", { name })) : undefined}>
      {image.probe}
      <ImageGenerationPreview project={project} target={decodeURIComponent(image.imageSrc.split("/files/")[1]?.split("?")[0] ?? "")}
        active={image.isGenerating} keepChildren={!image.missing} finalSrc={!image.missing ? image.imageSrc : undefined} aspect={String(ASPECT[kind])} surface="ink" className="h-full"
        label={image.isQueued ? t("Queued") : t("Drawing {name}…", { name })}>
        {image.missing ? (
          <StageEmpty
            title={mainFailure ? t("This reference didn't finish") : t("No image yet")}
            hint={t("Draw it from the panel. Pages use this image to keep {name} consistent.", { name })}
            tone={mainFailure ? "alert" : "muted"} />
        ) : (
          <>
            <img key={image.imageSrc} src={image.imageSrc} alt={name} onError={() => image.imageFailed()} className="h-full w-full object-contain" />
            <InspectButton images={{ src: image.imageSrc, alt: name }} placement="right-2.5 top-2.5" />
          </>
        )}
      </ImageGenerationPreview>
    </StageFrame>
  );

  const lookSrc = look ? versionedUrl(`${lookImageUrl(project, kind, entity.id, look.id)}?t=${encodeURIComponent(lookRef.timestamp)}`) : "";
  const lookBusy = lookRef.isSubmitting || !!lookRef.activeJob;
  const lookGenerating = !!look && (looks.generating(look.id) || lookBusy);
  const lookFailure = look ? looks.failure(look.id) : undefined;
  const lookStage = look && (
    <StageFrame kind={kind} status={lookGenerating ? (lookRef.activeJob?.status === "queued" ? t("Queued") : t("Drawing {name}…", { name: look.label })) : undefined}>
      <ImageGenerationPreview project={project} target={decodeURIComponent(lookSrc.split("/files/")[1]?.split("?")[0] ?? "")}
        active={lookGenerating} keepChildren={!lookRef.imgFailed} finalSrc={!lookRef.imgFailed ? lookSrc : undefined} aspect={String(ASPECT[kind])} surface="ink" className="h-full"
        label={lookRef.activeJob?.status === "queued" ? t("Queued") : t("Drawing {name}…", { name: look.label })}>
        {lookRef.imgFailed ? (
          <StageEmpty title={lookFailure ? t("This look didn't finish") : t("No image yet")} hint={t("Draw it from the panel.")}
            tone={lookFailure ? "alert" : "muted"} />
        ) : (
          <>
            <img key={lookSrc} src={lookSrc} alt={`${name} · ${look.label}`} onError={() => lookRef.imageFailed()} className="h-full w-full object-contain" />
            <InspectButton images={{ src: lookSrc, alt: `${name} · ${look.label}` }} placement="right-2.5 top-2.5" />
          </>
        )}
      </ImageGenerationPreview>
    </StageFrame>
  );

  const editLink = (
    <Link to={{ pathname: "../story", search: `?edit=${STORY_KIND[kind]}:${encodeURIComponent(entity.id)}` }} relative="path"
      className="inline-flex min-h-9 items-center gap-1.5 font-meta text-[0.8125rem] font-medium text-ink-black underline-offset-4 hover:underline">
      {t("Edit details")}<ArrowRight size={14} aria-hidden="true" />
    </Link>
  );

  return (
    <>
      <section aria-label={t("References")} className="benday-ink flex min-w-0 flex-1 flex-col text-pulp-paper">
        {toolbar}
        {look ? lookStage : mainStage}
        {kind !== "prop" && (
          <LooksStrip
            entry={entry}
            mainSrc={kind === "character" ? versionedUrl(`${portraitUrl(project, entity.id)}?t=${encodeURIComponent(image.timestamp)}`) : image.imageSrc}
            mainFallback={image.imageSrc}
            mainMissing={image.missing}
            mainDrawing={image.isGenerating}
            looks={looks}
            selected={lookId}
            onSelect={setLookId}
          />
        )}
      </section>

      <aside aria-label={look ? `${name} · ${look.label}` : name}
        className="flex shrink-0 flex-col border-t border-ink-black/12 bg-bristol text-ink-black studio-desktop:w-[22rem] studio-desktop:border-l studio-desktop:border-t-0">
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6 pt-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="border border-ink-black bg-pulp-paper px-1.5 py-0.5 font-meta text-[0.6875rem] font-bold uppercase tracking-[0.08em]">
              {look ? t("Look") : t(KIND_LABEL[kind])}
            </span>
            <span className="font-meta text-xs text-ink-muted">{look ? name : sub}</span>
          </div>
          <h2 className="mt-3 text-balance break-words font-display text-[1.5625rem] font-black uppercase leading-[0.98] tracking-[-0.03em]">
            {look ? look.label : name}
          </h2>

          {look ? (
            <LookDetails
              entry={entry}
              look={look}
              outdated={looks.outdated(look.id)}
              failure={lookFailure}
              busy={lookBusy}
              keeping={keep.isPending}
              onKeep={() => keep.mutate({ project, kind: STORY_KIND[kind], entityId: entity.id, stateId: look.id })}
              keepError={keep.error}
            />
          ) : (
            <>
              <AnchorSection anchor={entity.visual_anchor} />
              <EntityFacts entry={entry} firstSceneTitle={firstSceneTitle} />
              {kind === "character" && entry.entity.relationships.length > 0 && (
                <InspectorSection label={t("Relationships")}>
                  <ul className="mt-2 space-y-1.5">
                    {entry.entity.relationships.map((relationship) => {
                      const related = characterNames.get(relationship.character_id);
                      return (
                        <li key={relationship.character_id} className="font-body text-sm leading-5">
                          {related ? (
                            <button type="button" onClick={() => onShow("character", relationship.character_id)}
                              className="font-semibold text-ink-black underline decoration-ink-black/25 underline-offset-4 hover:decoration-ink-black focus-visible:outline-2 focus-visible:outline-hero-red">
                              {related}
                            </button>
                          ) : <span className="font-semibold capitalize">{relationship.character_id.replace(/_/g, " ")}</span>}
                          <span className="text-ink-muted"> · {relationship.relationship}</span>
                        </li>
                      );
                    })}
                  </ul>
                </InspectorSection>
              )}
              {mainFailure && !mainBusy && <div className="mt-4"><ErrorNotice error={mainFailure.message} operation="generate" title="This reference could not be completed." /></div>}
            </>
          )}

          <div className="mt-5 border-t border-ink-black/10 pt-4">
            {look ? (
              <CastRegenAction projectName={project} assetType={kind} assetId={entity.id} stateId={look.id}
                key={look.id}
                assetLabel={look.label} cost={lookRef.estimate} hasImage={!lookRef.imgFailed} busy={lookBusy}
                busyLabel={lookRef.activeJob?.status === "queued" ? t("Queued") : t("Drawing…")}
                instruction={lookInstructions[look.id] ?? lookRef.instructionDraft}
                onInstructionChange={(text) => setLookInstructions((current) => ({ ...current, [look.id]: text }))}
                error={lookRef.regenError} onRegenerate={() => lookRef.regenerate()} onRegenerateWithInstruction={lookRef.regenerate} />
            ) : (
              <CastRegenAction
                projectName={project} assetType={kind} assetId={entity.id}
                assetLabel={name}
                cost={image.estimate}
                instructionCost={image.estimate?.instruction_estimate}
                hasImage={!image.missing}
                busy={mainBusy}
                busyLabel={image.isQueued ? t("Queued") : t("Drawing…")}
                error={image.regenError}
                instruction={instruction ?? image.instructionDraft}
                onInstructionChange={setInstruction}
                onRegenerate={(withLooks) => image.regenerate(undefined, undefined, withLooks)}
                onRegenerateWithInstruction={submitMain}
              />
            )}
          </div>

          {!look && kind === "character" && <ReferenceViews projectName={project} charId={entity.id} timestamp={image.timestamp} />}
          {kind !== "prop" && (look ? (
            <RefVersionHistory projectName={project} assetType={kind} assetId={entity.id} stateId={look.id}
              busy={lookBusy || stageRegenerating} refreshKey={lookRef.timestamp}
              onRestored={() => lookRef.refreshImage()} />
          ) : (
            <RefVersionHistory projectName={project} assetType={kind} assetId={entity.id}
              refreshKey={image.timestamp} busy={stageRegenerating || image.isGenerating}
              onRestored={() => image.refreshImage()} />
          ))}
          {!look && (
            <details className="group mt-5 border-t border-ink-black/10 pt-3">
              <summary className="flex min-h-8 cursor-pointer list-none items-center gap-1.5 font-meta text-xs font-medium text-ink-muted hover:text-ink-black [&::-webkit-details-marker]:hidden">
                <ChevronRight size={14} aria-hidden="true" className="transition-transform group-open:rotate-90" />{t("Generation details")}
              </summary>
              <div className="pt-2"><GenerationDetailsPanel metadata={generationMeta} isLoading={isMetaLoading} /></div>
            </details>
          )}
        </div>
        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-ink-black/10 bg-pulp-paper px-5 py-1.5">
          {look ? (
            <button type="button" onClick={() => setLookId(null)}
              className="inline-flex min-h-9 items-center font-meta text-[0.8125rem] font-medium text-ink-muted hover:text-ink-black focus-visible:outline-2 focus-visible:outline-hero-red">
              {t("Back to {name}", { name })}
            </button>
          ) : <span />}
          {editLink}
        </div>
      </aside>
    </>
  );
}

function EntityFacts({ entry, firstSceneTitle }: { entry: CastEntry; firstSceneTitle?: string }) {
  const { t } = useI18n();
  const chips = entry.kind === "character"
    ? entry.entity.distinguishing_features
    : entry.kind === "location"
      ? [entry.entity.time_of_day, entry.entity.mood].filter((chip): chip is string => !!chip)
      : [];
  const facts: [string, string][] = entry.kind === "character"
    ? [[t("Outfit"), entry.entity.default_outfit]]
    : entry.kind === "prop" && firstSceneTitle ? [[t("First seen"), firstSceneTitle]] : [];
  const shown = facts.filter(([, value]) => !!value?.trim());
  return (
    <>
      {chips.length > 0 && (
        <ul aria-label={entry.kind === "character" ? t("Distinguishing features") : t("Time and mood")} className="mt-3 flex flex-wrap gap-1.5">
          {chips.map((chip) => (
            <li key={chip} className="border border-ink-black/20 bg-pulp-paper px-2 py-0.5 font-meta text-xs text-ink-black">{chip}</li>
          ))}
        </ul>
      )}
      {shown.length > 0 && (
        <dl className="mt-4 space-y-2">
          {shown.map(([label, value]) => (
            <div key={label}>
              <dt className={OVERLINE}>{label}</dt>
              <dd className="mt-0.5 break-words font-body text-sm leading-5">{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </>
  );
}

function LookDetails({ entry, look, outdated, failure, busy, keeping, onKeep, keepError }: {
  entry: CastEntry;
  look: AppearanceState;
  outdated: boolean;
  failure?: { message: string };
  busy: boolean;
  keeping: boolean;
  onKeep: () => void;
  keepError: Error | null;
}) {
  const { t } = useI18n();
  return (
    <>
      <AnchorSection anchor={look.visual_anchor} />
      {outdated && !busy && (
        <div className="mt-4 border border-ink-black bg-narrator-gold p-3 shadow-[3px_3px_0_0_var(--color-ink-black)]">
          <p className="font-meta text-[0.8125rem] font-semibold">{t("Drawn from an older {name}", { name: entry.entity.name })}</p>
          <p className="mt-0.5 font-body text-xs leading-[1.0625rem]">{t("Pages keep using this image until you redraw it below or keep it.")}</p>
          <Button variant="outline" size="xs" className="mt-2 border-ink-black! bg-transparent" disabled={keeping} onClick={onKeep}>{t("Keep current image")}</Button>
          {keepError && <ErrorNotice error={keepError} operation="save" />}
        </div>
      )}
      {failure && !busy && <div className="mt-4"><ErrorNotice error={failure.message} operation="generate" title="This reference could not be completed." /></div>}
    </>
  );
}

type Looks = ReturnType<typeof useLooks>;

/** Main plus every look, under the stage. Picking one puts it on the stage and in the panel. */
function LooksStrip({ entry, mainSrc, mainFallback, mainMissing, mainDrawing, looks, selected, onSelect }: {
  entry: CastEntry;
  mainSrc: string;
  mainFallback: string;
  mainMissing: boolean;
  mainDrawing: boolean;
  looks: Looks;
  selected: string | null;
  onSelect: (stateId: string | null) => void;
}) {
  const { t } = useI18n();
  // Sources that failed to load; keyed by URL so a redraw (new timestamp) tries again.
  const [failedMain, setFailedMain] = useState<ReadonlySet<string>>(() => new Set());
  const mainShown = mainMissing ? null : [mainSrc, mainFallback].find((src) => !failedMain.has(src)) ?? null;
  const art = entry.kind === "character" ? "h-16 w-16" : "h-[3.9375rem] w-28";
  const tile = cn(
    "group flex shrink-0 flex-col gap-1.5 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold",
    entry.kind === "character" ? "w-24" : "w-28",
  );
  const frame = (on: boolean) => cn("relative block overflow-hidden bg-ink-black transition-[outline-color,opacity]", art,
    on ? "outline-2 outline-offset-2 outline-narrator-gold" : "opacity-80 outline outline-1 outline-pulp-paper/20 group-hover:opacity-100 group-hover:outline-pulp-paper/50");
  const caption = (on: boolean) => cn("line-clamp-2 font-meta text-xs leading-4", on ? "font-semibold text-pulp-paper" : "text-on-chrome-muted group-hover:text-pulp-paper");
  const { attach: stripRef, ...strip } = useScrollStrip<HTMLDivElement>();

  return (
    <div className="relative shrink-0 border-t border-pulp-paper/8 bg-ink-black/60">
    <ScrollStripControls strip={strip} />
    <div ref={stripRef} role="group" aria-label={t("Looks")}
      className="flex items-start gap-4 overflow-x-auto px-5 pb-4 pt-3.5 [scrollbar-width:none]">
      <span className="w-12 shrink-0 pt-1 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-on-chrome-muted">
        {t("Looks")}<span className="mt-0.5 block font-display text-lg font-black tracking-normal text-pulp-paper">{looks.looks.length + 1}</span>
      </span>
      <button type="button" aria-pressed={selected === null} onClick={() => onSelect(null)} className={tile}>
        <span className={frame(selected === null)}>
          {mainShown && (
            <img key={mainShown} src={thumbnailUrl(mainShown)} alt="" onError={() => setFailedMain((prev) => new Set(prev).add(mainShown))}
              className={cn("h-full w-full object-cover", mainDrawing && "opacity-40")} />
          )}
          {(!mainShown || mainDrawing) && (
            <span aria-hidden="true" className="benday-ink absolute inset-0 flex items-center justify-center bg-ink-black/60">
              {mainDrawing ? <span className="size-2 bg-narrator-gold motion-safe:animate-pulse" /> : <Plus size={16} className="text-pulp-paper/60" />}
            </span>
          )}
        </span>
        <span className={caption(selected === null)}>{t("Main")}</span>
      </button>
      {looks.looks.map((look) => {
        const on = selected === look.id;
        const src = looks.thumb(look.id);
        const generating = looks.generating(look.id);
        const failure = looks.failure(look.id);
        const outdated = !generating && looks.outdated(look.id);
        const missing = looks.missing(look.id);
        const state = generating ? t("Drawing…") : failure ? t("Didn't finish") : missing ? t("Not drawn yet") : outdated ? t("Out of date") : null;
        return (
          <button key={look.id} type="button" aria-pressed={on} aria-label={look.label} aria-describedby={state ? `look-state-${look.id}` : undefined}
            title={look.label} onClick={() => onSelect(look.id)} className={tile}>
            <span className={frame(on)}>
              {!missing && (
                <img src={thumbnailUrl(src)} alt="" loading="lazy" onError={() => looks.markMissing(src)}
                  className={cn("h-full w-full object-cover", generating && "opacity-35")} />
              )}
              {(missing || generating) && (
                <span aria-hidden="true" className="benday-ink absolute inset-0 flex items-center justify-center bg-ink-black/60">
                  {generating ? <span className="size-2 bg-narrator-gold motion-safe:animate-pulse" /> : <Plus size={16} className="text-pulp-paper/60" />}
                </span>
              )}
              {(outdated || (failure && !missing)) && (
                <span className={cn("absolute inset-x-0 bottom-0 truncate border-t px-0.5 text-center font-meta text-[0.625rem] font-bold leading-4",
                  failure ? "border-hero-red bg-hero-red text-bristol" : "border-ink-black bg-narrator-gold text-ink-black")}>
                  {failure ? t("Failed") : t("Out of date")}
                </span>
              )}
            </span>
            <span className={caption(on)}>{look.label}</span>
            {state && <span id={`look-state-${look.id}`} className={cn("-mt-1 font-meta text-[0.6875rem] text-narrator-gold", outdated && !generating && !missing && !failure && "sr-only")}>{state}</span>}
          </button>
        );
      })}
      <Link to={{ pathname: "../story", search: `?edit=${STORY_KIND[entry.kind]}:${encodeURIComponent(entry.entity.id)}` }} relative="path"
        className={tile} title={t("Looks are added to the entry in Story")}>
        <span className={cn(art, "flex items-center justify-center border border-dashed border-pulp-paper/35 text-pulp-paper/70 transition-colors group-hover:border-pulp-paper/70 group-hover:text-pulp-paper")}>
          <Plus size={18} aria-hidden="true" />
        </span>
        <span className={caption(false)}>{t("Add a look")}</span>
      </Link>
    </div>
    </div>
  );
}
