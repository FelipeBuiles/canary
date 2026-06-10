from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import Location, Scene, StoryBible
from novel_to_comic.server.routers.labs import (
    _project_scene_reference_payload,
    _resolve_scene_panel_refs,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")


def test_project_scene_import_collects_draw_stage_reference_images(tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    style_template = "Ink wash with restrained texture."

    character_ref = project_dir / "refs" / "char_001" / "sheet.png"
    prop_ref = project_dir / "refs" / "props" / "prop_001" / "ref.png"
    style_ref = project_dir / "samples" / "style_1.png"
    plate_ref = project_dir / "plates" / "loc_001.png"
    for path in (character_ref, prop_ref, style_ref, plate_ref):
        _touch(path)

    suggestions_path = project_dir / "samples" / "style_suggestions.json"
    suggestions_path.write_text(
        '{"suggestions":[{"label":"Ink","template":"Ink wash with restrained texture."}]}'
    )
    story_bible = StoryBible(
        title="Test",
        author="Tester",
        total_scenes=1,
        characters=[],
        locations=[
            Location(
                id="loc_001",
                name="Library",
                visual_anchor="old library shelves",
                mood="quiet",
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="Library",
                location_id="loc_001",
                character_ids=[],
                summary="A library scene.",
                scene_type="scene",
                narrative_beat="setup",
                source_start_quote="Once",
            )
        ],
        narrative_arcs=[],
    )
    (project_dir / "story_bible.json").write_text(story_bible.model_dump_json())

    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A library panel.",
        reference_image_paths=[
            "refs/char_001/sheet.png",
            "refs/props/prop_001/ref.png",
        ],
        width=768,
        height=1024,
        steps=28,
    )

    refs_per_panel = _resolve_scene_panel_refs(
        project_dir,
        Config(style_template=style_template),
        [prompt],
    )
    refs = _project_scene_reference_payload(
        "project-id",
        project_dir,
        refs_per_panel,
    )

    relative_paths = [ref["relative_path"] for ref in refs]
    assert relative_paths == [
        "refs/char_001/sheet.png",
        "refs/props/prop_001/ref.png",
        "samples/style_1.png",
        "plates/loc_001.png",
    ]
    assert [ref["role"] for ref in refs] == ["subject", "prop", "style", "location_plate"]
    assert refs[0]["url"] == "/api/projects/project-id/files/refs/char_001/sheet.png"
    assert refs[0]["path"] == str(character_ref.resolve())
