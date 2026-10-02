"""Appending, splitting, replacing and deleting parts under the freeze rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_to_comic import artifacts
from novel_to_comic.extraction_delta import compute_delta, remove_delta, removal_conflicts
from novel_to_comic.models.story_bible import Character, Location, NarrativeArc, Scene, StoryBible
from novel_to_comic.series import (
    PartEditRejected,
    append_parts,
    delete_part,
    edit_blocker,
    initialize_series,
    rename_part,
    replace_part_text,
    split_part,
    write_extraction_delta,
)
from novel_to_comic.state import StageStatus, load_state, save_state
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import part_workspace, workspace_part_id

BODY = "The rain kept falling on the town. " * 10


def _series(tmp_path: Path, text: str = "Chapter 1\n" + BODY) -> Path:
    root = tmp_path / "book"
    root.mkdir()
    (root / "input").mkdir()
    novel = root / "input" / "novel.txt"
    novel.write_text(text)
    initialize_series(root, project_name="Rain", novel_path=novel, text=text, origin="novel.txt")
    return root


def _ids(root: Path) -> list[str]:
    return [part.id for part in TargetArtifacts(root).read_part_manifest().parts]


def _set_stage(root: Path, part: str, stage: str, status: StageStatus) -> None:
    workspace = part_workspace(root, part)
    state = load_state(workspace)
    state.stages[stage].status = status
    save_state(state, workspace)


def test_appended_parts_get_workspaces_text_and_default_titles(tmp_path) -> None:
    root = _series(tmp_path)
    created = append_parts(root, [(None, "Second. " * 5), ("Book Two", "Third. " * 5)], origin="paste")

    assert [record.id for record in created] == ["part_0002", "part_0003"]
    manifest = TargetArtifacts(root).read_part_manifest()
    assert [part.title for part in manifest.parts] == ["Part 1", "Part 2", "Book Two"]
    assert manifest.revision == 2
    assert workspace_part_id(part_workspace(root, "part_0003")) == "part_0003"
    assert TargetArtifacts(root).read_part_text("part_0002") == "Second. " * 5
    assert load_state(part_workspace(root, "part_0002")).project_name == "Rain"

    with pytest.raises(PartEditRejected):
        append_parts(root, [(None, "   ")])


def test_rename_is_always_allowed(tmp_path) -> None:
    root = _series(tmp_path)
    _set_stage(root, "part_0001", "adapt", StageStatus.COMPLETE)
    assert rename_part(root, "part_0001", "  Issue #1  ").title == "Issue #1"


def test_text_freezes_once_adapt_starts_or_a_later_part_is_extracted(tmp_path) -> None:
    root = _series(tmp_path)
    append_parts(root, [(None, "Second. " * 5)])
    assert edit_blocker(root, "part_0001") is None

    _set_stage(root, "part_0002", "extract", StageStatus.COMPLETE)
    assert "has been extracted" in edit_blocker(root, "part_0001")
    assert edit_blocker(root, "part_0002") is None

    _set_stage(root, "part_0002", "adapt", StageStatus.RUNNING)
    assert "adaptation has started" in edit_blocker(root, "part_0002")
    with pytest.raises(PartEditRejected):
        replace_part_text(root, "part_0002", "New. " * 5)


def test_split_renumbers_later_unstarted_parts(tmp_path) -> None:
    text = "Chapter 1\n" + BODY + "\nChapter 2\n" + BODY + "\nChapter 3\n" + BODY
    root = _series(tmp_path, text)
    append_parts(root, [("Sequel", "Later. " * 5)])
    second = text.index("Chapter 2")
    third = text.index("Chapter 3")

    pieces = split_part(root, "part_0001", [third, second], ["Opening", None, "Finale"])

    assert [piece.id for piece in pieces] == ["part_0001", "part_0002", "part_0003"]
    assert _ids(root) == ["part_0001", "part_0002", "part_0003", "part_0004"]
    manifest = TargetArtifacts(root).read_part_manifest()
    assert [part.title for part in manifest.parts] == ["Opening", "Part 2", "Finale", "Sequel"]
    target = TargetArtifacts(root)
    assert "".join(target.read_part_text(f"part_000{n}") for n in (1, 2, 3)) == text
    assert target.read_part_text("part_0004") == "Later. " * 5
    assert workspace_part_id(part_workspace(root, "part_0004")) == "part_0004"
    assert load_state(part_workspace(root, "part_0004")).novel_path.endswith("part_0004.txt")

    with pytest.raises(PartEditRejected, match="start of a line"):
        split_part(root, "part_0002", [3])


def test_delete_moves_later_parts_up_and_keeps_one_part(tmp_path) -> None:
    root = _series(tmp_path)
    append_parts(root, [(None, "Second. " * 5), (None, "Third. " * 5)])

    delete_part(root, "part_0002")

    assert _ids(root) == ["part_0001", "part_0002"]
    assert TargetArtifacts(root).read_part_text("part_0002") == "Third. " * 5
    delete_part(root, "part_0002")
    with pytest.raises(PartEditRejected, match="at least one part"):
        delete_part(root, "part_0001")


def _bible(*scenes: Scene, characters=(), locations=()) -> StoryBible:
    return StoryBible(
        title="Rain", author="A. Writer", total_scenes=len(scenes),
        characters=list(characters), locations=list(locations), scenes=list(scenes),
        narrative_arcs=[NarrativeArc(act=1, title="One", scenes=[scenes[0].id])],
    )


def _character(cid: str, scene: str, name: str = "", origin: str = "extracted") -> Character:
    return Character(
        id=cid, name=name or cid, visual_anchor="1woman, adult female", age_range="30s",
        gender="female", distinguishing_features=[], default_outfit="coat",
        first_appearance_scene=scene, origin=origin,
    )


def _scene(sid: str, part: str, characters: list[str], location: str = "loc_001") -> Scene:
    return Scene(
        id=sid, part_id=part, chapter=1, title=sid, location_id=location,
        character_ids=characters, summary="s", scene_type="dialogue",
        narrative_beat="setup", source_start_quote="The rain kept falling on the town.",
    )


def test_replacing_an_extracted_part_withdraws_exactly_its_additions(tmp_path) -> None:
    root = _series(tmp_path)
    append_parts(root, [(None, "Second. " * 5)])
    location = Location(id="loc_001", name="Town", visual_anchor="street", mood="grey")
    before = _bible(_scene("scene_001", "part_0001", ["char_001"]),
                    characters=[_character("char_001", "scene_001")], locations=[location])
    after = before.model_copy(deep=True)
    after.scenes.append(_scene("p0002s0001_scene_001", "part_0002", ["char_001", "p0002s0001_char_001"]))
    after.characters.append(_character("p0002s0001_char_001", "p0002s0001_scene_001", "Newcomer"))
    after.narrative_arcs.append(NarrativeArc(part_id="part_0002", act=1, title="Two",
                                             scenes=["p0002s0001_scene_001"]))
    delta = compute_delta(before, after, "part_0002")
    assert delta.scene_ids == ("p0002s0001_scene_001",)
    assert [ref.entity_id for ref in delta.entities] == ["p0002s0001_char_001"]

    # The author edits an earlier character after the part was extracted.
    edited = after.model_copy(deep=True)
    edited.characters[0].name = "Renamed by author"
    artifacts.write_story_bible(root, edited)
    workspace = part_workspace(root, "part_0002")
    write_extraction_delta(workspace, delta)
    _set_stage(root, "part_0002", "extract", StageStatus.COMPLETE)
    (workspace / "source" / "source.json").write_text("{}")

    replace_part_text(root, "part_0002", "Rewritten. " * 5)

    bible = artifacts.read_story_bible(root)
    assert [scene.id for scene in bible.scenes] == ["scene_001"]
    assert [character.name for character in bible.characters] == ["Renamed by author"]
    assert [arc.part_id for arc in bible.narrative_arcs] == ["part_0001"]
    assert bible.revision == edited.revision + 1
    assert load_state(workspace).stages["extract"].status == StageStatus.PENDING
    assert not (workspace / "source" / "source.json").exists()


def test_characters_added_only_to_a_removed_part_block_the_removal() -> None:
    location = Location(id="loc_001", name="Town", visual_anchor="street", mood="grey")
    bible = _bible(
        _scene("scene_001", "part_0001", ["char_001"]),
        _scene("p0002s0001_scene_001", "part_0002", ["char_002"]),
        characters=[_character("char_001", "scene_001"),
                    _character("char_002", "p0002s0001_scene_001", "Added Later", origin="author")],
        locations=[location],
    )
    before = bible.model_copy(deep=True)
    before.scenes = before.scenes[:1]
    before.characters = before.characters[:1]
    # The author added char_002 after extraction, so the delta doesn't own it.
    delta = compute_delta(before, before, "part_0002").model_copy(
        update={"scene_ids": ("p0002s0001_scene_001",)})

    assert removal_conflicts(bible, delta) == ["Added Later"]
    removed = remove_delta(bible, delta.model_copy(update={"scene_ids": ()}))
    assert [scene.id for scene in removed.scenes] == ["scene_001", "p0002s0001_scene_001"]
