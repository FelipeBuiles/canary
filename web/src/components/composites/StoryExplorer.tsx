import { useId, useState } from "react";
import { MapPin, Users } from "lucide-react";
import { useI18n } from "../../i18n";
import { readableAnchor } from "../../lib/visualAnchor";
import { castCharacters } from "../../lib/castRoster";
import type { Scene, StoryDecision } from "../../types/api";
import { RoomTabs } from "./RoomTabs";

interface StoryExplorerProps {
  story: StoryDecision["story_bible"];
}

/** Extract writes beats and affects as free-form snake_case or lowercase phrases. */
function readablePhrase(value: string | null | undefined): string {
  const text = (value ?? "").replaceAll("_", " ").trim();
  return text ? `${text.charAt(0).toLocaleUpperCase()}${text.slice(1)}` : "";
}

function known(value: string | null | undefined): value is string {
  return !!value && value.trim().toLocaleLowerCase() !== "unknown";
}

/** Source facts stay distinct from the editable adaptation brief. */
export function StoryExplorer({ story }: StoryExplorerProps) {
  const { t } = useI18n();
  const headingId = useId();
  const [view, setView] = useState<"scenes" | "characters" | "places">("scenes");
  const narrativeScenes = story.scenes.filter((scene) => scene.scene_type !== "non_narrative");
  const excludedSourceMatter = narrativeScenes.length < story.scenes.length;
  const recurring = castCharacters(story);
  const characters = new Map(story.characters.map((character) => [character.id, character.name]));
  const locations = new Map(story.locations.map((location) => [location.id, location.name]));
  const sceneNumbers = new Map(narrativeScenes.map((scene, index) => [scene.id, String(index + 1).padStart(2, "0")]));
  const multipleChapters = new Set(narrativeScenes.map((scene) => scene.chapter)).size > 1;
  const tabs = [
    { key: "scenes" as const, label: t("Scenes"), count: narrativeScenes.length },
    { key: "characters" as const, label: t("Characters"), count: recurring.length },
    { key: "places" as const, label: t("Places"), count: story.locations.length },
  ];

  // Sequences group the scene list in reading order; any scene a sequence
  // does not claim still appears, after them. Non-story source ranges remain
  // in the citation index but aren't story action to display or adapt.
  const byId = new Map(narrativeScenes.map((scene) => [scene.id, scene]));
  const claimed = new Set<string>();
  const groups = (story.sequences ?? []).map((sequence) => {
    const scenes = sequence.scenes.flatMap((id) => {
      const scene = byId.get(id);
      if (!scene || claimed.has(id)) return [];
      claimed.add(id);
      return [scene];
    });
    return { key: `${sequence.part_id}-${sequence.number}`, number: sequence.number, title: sequence.title, turn: sequence.turn, scenes };
  }).filter((group) => group.scenes.length > 0);
  const unclaimed = narrativeScenes.filter((scene) => !claimed.has(scene.id));
  const grouped = groups.length > 0;
  if (unclaimed.length) groups.push({ key: "more", number: 0, title: grouped ? t("More scenes") : "", turn: null, scenes: unclaimed });

  function sceneRow(scene: Scene, index: number, scenes: Scene[]) {
    const number = sceneNumbers.get(scene.id) ?? "";
    const location = scene.location_id === null ? undefined : locations.get(scene.location_id);
    const cast = scene.character_ids.flatMap((id) => characters.get(id) ?? []);
    // A beat marks where the story moves; repeating it on every scene is noise.
    const beat = scene.narrative_beat === scenes[index - 1]?.narrative_beat ? "" : readablePhrase(scene.narrative_beat);
    const Heading = grouped ? "h4" : "h3";
    return (
      <li key={scene.id} className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-3 gap-y-4 py-6 md:grid-cols-[4rem_minmax(0,1fr)] md:gap-x-6 md:py-8 xl:grid-cols-[4rem_minmax(0,1fr)_15rem]">
        <span aria-label={`${t("SCENE")} ${Number(number)}`} className="row-span-2 pt-1 font-display text-3xl font-black tabular-nums text-hero-red md:text-5xl xl:row-span-1">
          {number}
        </span>
        <article className="min-w-0">
          {beat && <p className="mb-1.5 font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{beat}</p>}
          <Heading className="font-display text-lg font-bold leading-tight md:text-xl">{scene.title}</Heading>
          <p className="mt-3 whitespace-pre-line text-sm leading-7 text-ink-black">{scene.summary}</p>
        </article>
        {(location || cast.length > 0 || multipleChapters) && (
          <div className="col-start-2 flex min-w-0 flex-wrap gap-x-5 gap-y-2 text-xs leading-5 text-ink-muted xl:col-start-3 xl:flex-col xl:border-l xl:border-ink-black/15 xl:pl-5 xl:pt-1">
            {multipleChapters && <span className="font-meta">{t("Chapter")} {scene.chapter}</span>}
            {location && <span className="inline-flex items-start gap-1.5"><MapPin className="mt-0.5 shrink-0" size={14} aria-hidden="true" />{location}</span>}
            {cast.length > 0 && <span className="inline-flex items-start gap-1.5"><Users className="mt-0.5 shrink-0" size={14} aria-hidden="true" />{cast.join(", ")}</span>}
          </div>
        )}
      </li>
    );
  }

  return (
    <section id="story-source" tabIndex={-1} aria-labelledby={headingId} className="min-w-0 border-t-2 border-ink-black pt-8">
      <div className="mb-6">
        <h2 id={headingId} className="font-display text-2xl font-black uppercase tracking-tight md:text-3xl">
          {t("Inside your story")}
        </h2>
        <p className="mt-2 text-sm leading-6 text-ink-muted">
          {t("Explore the scenes, characters and places extracted from your manuscript. These source details are read-only; shape the adaptation in the brief above.")}
        </p>
      </div>

      <RoomTabs
        ariaLabel={t("Explore extracted story")}
        className="mb-6 max-w-full"
        tabs={tabs.map((tab) => ({ ...tab, active: view === tab.key, onClick: () => setView(tab.key) }))}
      />

      {view === "scenes" ? (
        narrativeScenes.length ? (
          <div className="space-y-10">
            {excludedSourceMatter && <p className="text-sm text-ink-muted">{t("Author notes and other non-story material are excluded from adaptation.")}</p>}
            {groups.map((group) => (
              <section key={group.key} aria-label={group.title || undefined}>
                {group.title && (
                  <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b-2 border-ink-black pb-3">
                    {group.number > 0 && <span className="bg-narrator-gold px-2 py-1 font-meta text-[0.6rem] font-bold uppercase tracking-[0.12em] text-ink-black">{t("Sequence {number}", { number: group.number })}</span>}
                    <h3 className="font-display text-xl font-black uppercase leading-tight tracking-[-0.02em] md:text-2xl">{group.title}</h3>
                  </header>
                )}
                <ol className="divide-y divide-ink-black/15 border-b border-ink-black/15">
                  {group.scenes.map(sceneRow)}
                </ol>
                {group.turn && (
                  <p className="mt-4 border-l-4 border-narrator-gold py-1 pl-4 text-sm leading-6 text-ink-black md:ml-[5.5rem]">
                    <span className="mr-2 font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("Turn")}</span>
                    {group.turn}
                  </p>
                )}
              </section>
            ))}
          </div>
        ) : <p className="py-8 text-sm text-ink-muted">{t("No scenes were extracted from this manuscript.")}</p>
      ) : view === "characters" ? (
        recurring.length ? (
          <div className="grid gap-x-10 md:grid-cols-2">
            {recurring.map((character) => {
              const meta = [character.age_range, character.gender].filter(known);
              const affect = readablePhrase(character.baseline_affect);
              const firstScene = byId.get(character.first_appearance_scene);
              const relationships = (character.relationships ?? []).flatMap((relationship) => {
                const name = characters.get(relationship.character_id);
                return name && relationship.relationship ? [{ name, relationship: relationship.relationship }] : [];
              });
              return (
                <article key={character.id} className="min-w-0 border-b border-ink-black/15 py-6 md:[&:nth-child(-n+2)]:pt-2">
                  <h3 className="font-display text-xl font-bold leading-tight">{character.name}</h3>
                  {meta.length > 0 && <p className="mt-1.5 font-meta text-xs text-ink-muted">{meta.join(" · ")}</p>}
                  {affect && <p className="mt-3 font-body text-sm italic leading-6 text-ink-black/80">{affect}</p>}
                  <p className="mt-3 whitespace-pre-line text-sm leading-7 text-ink-black">{readableAnchor(character.visual_anchor)}</p>
                  {(relationships.length > 0 || firstScene) && (
                    <dl className="mt-4 space-y-1.5 text-xs leading-5 text-ink-muted">
                      {relationships.map((relationship) => (
                        <div key={relationship.name} className="flex flex-wrap gap-x-1.5">
                          <dt className="font-bold text-ink-black">{relationship.name}</dt>
                          <dd className="min-w-0">· {relationship.relationship}</dd>
                        </div>
                      ))}
                      {firstScene && (
                        <div className="flex gap-1.5">
                          <dt className="shrink-0">{t("First appears")}</dt>
                          <dd className="min-w-0 text-ink-black">{sceneNumbers.get(firstScene.id)} · {firstScene.title}</dd>
                        </div>
                      )}
                    </dl>
                  )}
                </article>
              );
            })}
          </div>
        ) : <p className="py-8 text-sm text-ink-muted">{t("No characters were extracted from this manuscript.")}</p>
      ) : (
        story.locations.length ? (
          <div className="grid gap-x-10 md:grid-cols-2">
            {story.locations.map((location) => {
              const meta = [readablePhrase(location.time_of_day), readablePhrase(location.mood)].filter(known);
              const appearances = story.scenes.filter((scene) => scene.location_id === location.id).map((scene) => sceneNumbers.get(scene.id));
              return (
                <article key={location.id} className="min-w-0 border-b border-ink-black/15 py-6 md:[&:nth-child(-n+2)]:pt-2">
                  <h3 className="font-display text-xl font-bold leading-tight">{location.name}</h3>
                  {meta.length > 0 && <p className="mt-1.5 font-meta text-xs text-ink-muted">{meta.join(" · ")}</p>}
                  <p className="mt-3 whitespace-pre-line text-sm leading-7 text-ink-black">{readableAnchor(location.visual_anchor)}</p>
                  {appearances.length > 0 && (
                    <p className="mt-4 text-xs leading-5 text-ink-muted">
                      {t("{count, plural, one {Scene} other {Scenes}}", { count: appearances.length })} <span className="font-meta tabular-nums text-ink-black">{appearances.join(", ")}</span>
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        ) : <p className="py-8 text-sm text-ink-muted">{t("No places were extracted from this manuscript.")}</p>
      )}
    </section>
  );
}
