import { useId, useState } from "react";
import { BookOpen, MapPin, Users } from "lucide-react";
import { useI18n } from "../../i18n";
import type { StoryDecision } from "../../types/api";
import { RoomTabs } from "./RoomTabs";

interface StoryExplorerProps {
  story: StoryDecision["story_bible"];
}

/** Source facts stay distinct from the editable adaptation brief. */
export function StoryExplorer({ story }: StoryExplorerProps) {
  const { t } = useI18n();
  const headingId = useId();
  const [view, setView] = useState<"scenes" | "characters" | "places">("scenes");
  const characters = new Map(story.characters.map((character) => [character.id, character.name]));
  const locations = new Map(story.locations.map((location) => [location.id, location.name]));
  const tabs = [
    { key: "scenes" as const, label: t("Scenes"), count: story.scenes.length },
    { key: "characters" as const, label: t("Characters"), count: story.characters.length },
    { key: "places" as const, label: t("Places"), count: story.locations.length },
  ];
  const entities = view === "characters" ? story.characters : story.locations;

  return (
    <section id="story-source" tabIndex={-1} aria-labelledby={headingId} className="min-w-0 border-t-2 border-ink-black pt-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-5">
        <div className="max-w-2xl">
          <h2 id={headingId} className="font-display text-2xl font-black uppercase tracking-tight md:text-3xl">
            {t("Inside your story")}
          </h2>
          <p className="mt-2 text-sm leading-6 text-ink-muted">
            {t("Explore the scenes, characters and places extracted from your manuscript. These source details are read-only; shape the adaptation in the brief above.")}
          </p>
        </div>
        <span className="inline-flex items-center gap-2 border border-ink-black/20 px-3 py-2 font-meta text-xs text-ink-muted">
          <BookOpen size={15} aria-hidden="true" />
          {t("Extracted from your manuscript")}
        </span>
      </div>

      <RoomTabs
        ariaLabel={t("Explore extracted story")}
        className="mb-6 max-w-full"
        tabs={tabs.map((tab) => ({ ...tab, active: view === tab.key, onClick: () => setView(tab.key) }))}
      />

      {view === "scenes" ? (
        story.scenes.length ? (
          <ol className="divide-y divide-ink-black/15 border-b border-ink-black/15">
            {story.scenes.map((scene, index) => {
              const location = locations.get(scene.location_id);
              const cast = scene.character_ids.flatMap((id) => characters.get(id) ?? []);
              return (
                <li key={scene.id} className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 py-6 first:pt-2 md:grid-cols-[4rem_minmax(0,1fr)] md:gap-6 md:py-8">
                  <span aria-label={`${t("SCENE")} ${index + 1}`} className="pt-1 font-display text-3xl font-black tabular-nums text-hero-red md:text-5xl">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <article className="min-w-0">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
                      <h3 className="font-display text-lg font-bold leading-tight md:text-xl">{scene.title}</h3>
                      <span className="font-meta text-xs text-ink-muted">{t("Chapter")} {scene.chapter}</span>
                    </div>
                    <p className="mt-3 max-w-[75ch] whitespace-pre-line text-sm leading-7 text-ink-black">{scene.summary}</p>
                    {(location || cast.length > 0) && (
                      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs leading-5 text-ink-muted">
                        {location && <span className="inline-flex items-start gap-1.5"><MapPin className="mt-0.5 shrink-0" size={14} aria-hidden="true" />{location}</span>}
                        {cast.length > 0 && <span className="inline-flex items-start gap-1.5"><Users className="mt-0.5 shrink-0" size={14} aria-hidden="true" />{cast.join(", ")}</span>}
                      </div>
                    )}
                  </article>
                </li>
              );
            })}
          </ol>
        ) : <p className="py-8 text-sm text-ink-muted">{t("No scenes were extracted from this manuscript.")}</p>
      ) : (
        entities.length ? (
          <div className="grid gap-x-8 md:grid-cols-2">
            {entities.map((entity) => (
              <article key={entity.id} className="border-b border-ink-black/15 py-6 first:pt-2 md:[&:nth-child(2)]:pt-2">
                <h3 className="font-display text-xl font-bold leading-tight">{entity.name}</h3>
                <p className="mt-3 whitespace-pre-line text-sm leading-7 text-ink-black">{entity.visual_anchor}</p>
              </article>
            ))}
          </div>
        ) : <p className="py-8 text-sm text-ink-muted">{view === "characters" ? t("No characters were extracted from this manuscript.") : t("No places were extracted from this manuscript.")}</p>
      )}
    </section>
  );
}
