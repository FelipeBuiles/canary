"""Select recurring Cast work without deleting source participants or their IDs."""

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.story_bible import StoryBible

MIN_RECURRING_SCENES = 3
#: The most source words one comic page adapts (Brief's densest calibration).
#: A character whose scenes hold more text than this lands on several pages.
DENSEST_PAGE_WORDS = 400


def character_scene_counts(bible: StoryBible) -> Counter[str]:
    return Counter(character_id for scene in bible.scenes if scene.scene_type != "non_narrative"
                   for character_id in set(scene.character_ids))


def cast_character_ids(bible: StoryBible, project_dir: Path | None = None) -> frozenset[str]:
    """Recurring identities, explicit author additions and retained Cast assets.

    Tiny stories cannot establish three appearances, so their participants stay
    eligible. Established reference authorities are never demoted automatically.
    Counts use the series registry, allowing later parts to promote a newcomer
    without assigning another ID or losing earlier appearances.
    """
    scenes = [scene for scene in bible.scenes if scene.scene_type != "non_narrative"]
    counts = character_scene_counts(bible)
    return frozenset(character.id for character in bible.characters if (
        len(scenes) < MIN_RECURRING_SCENES
        or counts[character.id] >= MIN_RECURRING_SCENES
        or character.origin == "author"
        or character.cast_required
        or (project_dir is not None
            and artifacts.character_ref_sheet_path(project_dir, character.id).exists())
    ))


def promote_multi_page_cast(bible: StoryBible, source: SourceDocument, part_id: str | None) -> list[str]:
    """Require Cast references for this part's people whose scenes span several pages.

    Scene counts miss a one-scene visitor who speaks across a long scene: drawn
    from words alone, each page reinvents (or borrows) their look. Pages do
    not exist before Cast, so the scenes' source length stands in for them.
    Nothing is ever demoted.
    """
    units = {unit.id: unit for unit in source.units}
    words = {scene.id: len(source.text[units[scene.first_unit_id].start_offset:
                                       units[scene.last_unit_id].end_offset].split())
             for scene in source.scenes}
    footprint: Counter[str] = Counter()
    for scene in bible.scenes:
        if scene.scene_type != "non_narrative" and (part_id is None or scene.part_id == part_id):
            for character_id in set(scene.character_ids):
                footprint[character_id] += words.get(scene.id, 0)
    cast = cast_character_ids(bible)
    promoted = []
    for character in bible.characters:
        if character.id not in cast and footprint[character.id] > DENSEST_PAGE_WORDS:
            character.cast_required = True
            promoted.append(character.name)
    return promoted


def cast_story_bible(
    bible: StoryBible, project_dir: Path | None = None, *, character_ids: Iterable[str] = (),
) -> StoryBible:
    """A derived Cast view; canonical source rosters and facts stay untouched."""
    selected = cast_character_ids(bible, project_dir) | frozenset(character_ids)
    view = bible.model_copy(deep=True)
    view.characters = [character for character in view.characters if character.id in selected]
    for scene in view.scenes:
        scene.character_ids = [character_id for character_id in scene.character_ids if character_id in selected]
    for character in view.characters:
        character.relationships = [link for link in character.relationships if link.character_id in selected]
    return view


def read_cast_story_bible(
    project_dir: Path, *, safe: bool = False, character_ids: Iterable[str] = (),
) -> StoryBible | None:
    bible = (artifacts.read_story_bible_safe(project_dir) if safe
             else artifacts.read_story_bible(project_dir))
    return cast_story_bible(bible, project_dir, character_ids=character_ids) if bible is not None else None


def story_bible_api_view(bible: StoryBible, project_dir: Path) -> dict:
    """Keep all source identities available; mark the smaller recurring roster."""
    return {**bible.model_dump(mode="json"),
            "cast_character_ids": sorted(cast_character_ids(bible, project_dir))}
