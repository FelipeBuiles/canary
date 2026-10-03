"""Select recurring Cast work without deleting source participants or their IDs."""

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.models.story_bible import StoryBible

MIN_RECURRING_SCENES = 3


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
