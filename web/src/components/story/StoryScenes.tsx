import { MapPin, Users } from "lucide-react";
import { useI18n } from "../../i18n";
import type { Scene, StoryBible } from "../../types/api";
import { narrativeScenes, readablePhrase, sceneNumbers } from "./storyPhrases";

/** This part's extracted scenes, read-only: shape the adaptation in the brief. */
export function StoryScenes({ story }: { story: StoryBible }) {
  const { t } = useI18n();
  const scenes = narrativeScenes(story.scenes);
  const excludedSourceMatter = scenes.length < story.scenes.length;
  const characters = new Map(story.characters.map((character) => [character.id, character.name]));
  const locations = new Map(story.locations.map((location) => [location.id, location.name]));
  const numbers = sceneNumbers(story.scenes);
  const multipleChapters = new Set(scenes.map((scene) => scene.chapter)).size > 1;

  // Sequences group the scene list in reading order; any scene a sequence
  // does not claim still appears, after them.
  const byId = new Map(scenes.map((scene) => [scene.id, scene]));
  const claimed = new Set<string>();
  const groups = (story.sequences ?? []).map((sequence) => {
    const members = sequence.scenes.flatMap((id) => {
      const scene = byId.get(id);
      if (!scene || claimed.has(id)) return [];
      claimed.add(id);
      return [scene];
    });
    return { key: `${sequence.part_id}-${sequence.number}`, number: sequence.number, title: sequence.title, turn: sequence.turn, scenes: members };
  }).filter((group) => group.scenes.length > 0);
  const unclaimed = scenes.filter((scene) => !claimed.has(scene.id));
  const grouped = groups.length > 0;
  if (unclaimed.length) groups.push({ key: "more", number: 0, title: grouped ? t("More scenes") : "", turn: null, scenes: unclaimed });

  if (!scenes.length) return <p className="py-8 text-sm text-ink-muted">{t("No scenes were extracted from this manuscript.")}</p>;

  function sceneRow(scene: Scene, index: number, group: Scene[]) {
    const number = numbers.get(scene.id) ?? "";
    const location = scene.location_id === null ? undefined : locations.get(scene.location_id);
    const cast = scene.character_ids.flatMap((id) => characters.get(id) ?? []);
    // A beat marks where the story moves; repeating it on every scene is noise.
    const beat = scene.narrative_beat === group[index - 1]?.narrative_beat ? "" : readablePhrase(scene.narrative_beat);
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
  );
}
