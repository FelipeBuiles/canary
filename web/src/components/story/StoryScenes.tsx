import { useState } from "react";
import { MapPin, Users } from "lucide-react";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import type { Scene, StoryBible } from "../../types/api";
import { narrativeScenes, readablePhrase, sceneNumbers } from "./storyPhrases";

/**
 * This part's extracted scenes as a board, read-only: one column per
 * sequence, in reading order. `isMatch` dims the scenes an entry isn't in;
 * `imageFor` returns a place's Cast plate when one exists.
 */
export function StoryScenes({ story, isMatch, imageFor }: {
  story: StoryBible;
  isMatch?: (scene: Scene) => boolean;
  imageFor?: (locationId: string) => string | undefined;
}) {
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

  function sceneCard(scene: Scene, index: number, group: Scene[]) {
    const number = numbers.get(scene.id) ?? "";
    const location = scene.location_id === null ? undefined : locations.get(scene.location_id);
    const cast = scene.character_ids.flatMap((id) => characters.get(id) ?? []);
    // A beat marks where the story moves; repeating it on every scene is noise.
    const beat = scene.narrative_beat === group[index - 1]?.narrative_beat ? "" : readablePhrase(scene.narrative_beat);
    const image = scene.location_id ? imageFor?.(scene.location_id) : undefined;
    const Heading = grouped ? "h4" : "h3";
    const dimmed = isMatch ? !isMatch(scene) : false;
    return (
      <li key={scene.id} className={cn("border border-ink-black/16 bg-bristol transition-opacity duration-150", dimmed && "opacity-30")}>
        <div className={cn("relative", image ? "h-12 overflow-hidden bg-ink-black" : "px-2.5 pt-2.5")}>
          {image && <PlateBand src={image} />}
          <span aria-label={`${t("SCENE")} ${Number(number)}`}
            className={cn("inline-flex h-[1.375rem] min-w-[1.625rem] items-center justify-center border border-ink-black bg-pulp-paper px-1 font-meta text-[0.6875rem] font-bold tabular-nums", image && "absolute left-1.5 top-1.5")}>
            {number}
          </span>
        </div>
        <article className="min-w-0 px-2.5 pb-3 pt-2">
          {beat && <p className="mb-1 font-meta text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{beat}</p>}
          <Heading className="font-meta text-[0.8125rem] font-semibold leading-[1.3] text-ink-black">{scene.title}</Heading>
          <p className="mt-1.5 line-clamp-3 whitespace-pre-line font-body text-xs leading-[1.5] text-ink-soft" title={scene.summary}>{scene.summary}</p>
          {(location || cast.length > 0 || multipleChapters) && (
            <div className="mt-2 space-y-0.5 font-body text-[0.6875rem] leading-[1.45] text-ink-muted">
              {multipleChapters && <p className="font-meta">{t("Chapter")} {scene.chapter}</p>}
              {location && <p className="flex items-start gap-1"><MapPin className="mt-px shrink-0" size={11} aria-hidden="true" /><span className="min-w-0">{location}</span></p>}
              {cast.length > 0 && <p className="flex items-start gap-1"><Users className="mt-px shrink-0" size={11} aria-hidden="true" /><span className="min-w-0">{cast.join(", ")}</span></p>}
            </div>
          )}
        </article>
      </li>
    );
  }

  return (
    <div className="space-y-4">
      {excludedSourceMatter && <p className="text-sm text-ink-muted">{t("Author notes and other non-story material are excluded from adaptation.")}</p>}
      {/* Sequences stack top to bottom and their scenes wrap, so the whole story reads with one vertical scroll. */}
      <div className={grouped ? "divide-y divide-ink-black/12" : ""}>
        {groups.map((group) => (
          <section key={group.key} aria-label={group.title || undefined}
            className={cn("min-w-0", group.title && "py-4 first:pt-0 @min-[44rem]:grid @min-[44rem]:grid-cols-[13rem_minmax(0,1fr)] @min-[44rem]:gap-5")}>
            {group.title && (
              <header className="px-0.5 pb-3 pt-1 @min-[44rem]:sticky @min-[44rem]:top-0 @min-[44rem]:self-start @min-[44rem]:pb-0">
                <div className="flex items-center gap-2">
                  {group.number > 0 && <span className="inline-flex h-[1.375rem] items-center border border-ink-black bg-narrator-gold px-1.5 font-meta text-[0.625rem] font-bold uppercase tracking-[0.1em] text-ink-black">{t("Sequence {number}", { number: group.number })}</span>}
                  <span className="font-meta text-[0.6875rem] text-ink-muted">{t("{count, plural, one {# scene} other {# scenes}}", { count: group.scenes.length })}</span>
                </div>
                <h3 className="mt-2 font-display text-base font-black uppercase leading-[1.02] tracking-[-0.02em]">{group.title}</h3>
                {group.turn && <p className="mt-1.5 line-clamp-3 font-body text-xs leading-[1.45] text-ink-soft" title={group.turn}>
                  <span className="sr-only">{t("Turn")}: </span>{group.turn}
                </p>}
              </header>
            )}
            <ol className="grid grid-cols-[repeat(auto-fill,minmax(13.5rem,1fr))] gap-2.5">
              {group.scenes.map(sceneCard)}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}

/** A place's plate as the scene card's header strip; absent or broken plates leave the ink band. */
function PlateBand({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} className="absolute inset-0 h-full w-full object-cover" />;
}
