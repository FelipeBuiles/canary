from novel_to_comic import artifacts
from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.stages.s5_plan import approved_reference_files


def test_canonical_equivalent_state_reuses_base_character_reference(tmp_path):
    bible = StoryBible(
        title="Fever",
        author="A. Witness",
        total_scenes=0,
        characters=[
            Character(
                id="char_001",
                name="Henry",
                visual_anchor="1man, adult male, dark hair, pale skin",
                age_range="early 20s",
                gender="male",
                distinguishing_features=["dark hair"],
                default_outfit="artist clothes",
                first_appearance_scene="scene_001",
                appearance_states=[
                    AppearanceState(
                        id="henry_recovered",
                        label="Recovered",
                        visual_anchor="1man, adult male, dark hair, pale skin",
                        canonical_equivalent=True,
                    )
                ],
            )
        ],
        locations=[],
        scenes=[],
        narrative_arcs=[],
    )
    artifacts.write_story_bible(tmp_path, bible)

    references = approved_reference_files(tmp_path)

    assert references["char_001:henry_recovered"].path == artifacts.character_ref_sheet_path(
        tmp_path,
        "char_001",
    )
