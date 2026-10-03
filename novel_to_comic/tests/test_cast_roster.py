"""Incidental participants keep story authority without becoming paid Cast work."""
from copy import deepcopy

from novel_to_comic import artifacts
from novel_to_comic.cast_roster import cast_character_ids, cast_story_bible, character_scene_counts
from novel_to_comic.models.story_bible import Character, Scene, StoryBible
from novel_to_comic.models.appearance import AppearanceState, StateActivation, StoryPosition
from novel_to_comic.series import cast_inventory_keys
from novel_to_comic.stages.s5_plan import approved_reference_files, approved_visual_inventory


def bible():
    characters = [Character(id=name, name=name.title(), visual_anchor='adult, black hair',
                            age_range='adult', gender='female', distinguishing_features=[],
                            default_outfit='coat', first_appearance_scene='scene_1')
                  for name in ['ari', 'visitor', 'guard']]
    scenes = [Scene(id=f'scene_{index}', chapter=1, title='Crossing', location_id=None,
                    character_ids=roster, summary='Ari crosses the gate.', scene_type='action',
                    narrative_beat='crossing', source_start_quote='Ari crosses the gate.')
              for index, roster in enumerate([
                  ['ari', 'visitor', 'visitor'], ['ari', 'visitor'], ['ari', 'guard'],
                  ['ari'], ['ari'],
              ], 1)]
    return StoryBible(title='Crossing', author='Unknown', total_scenes=5, characters=characters,
                      locations=[], scenes=scenes, sequences=[])


def test_only_recurrent_characters_enter_cast_without_mutating_source_facts():
    source = bible()
    original = deepcopy(source.model_dump())
    assert character_scene_counts(source) == {'ari': 5, 'visitor': 2, 'guard': 1}
    view = cast_story_bible(source)
    assert [character.id for character in view.characters] == ['ari']
    assert all(scene.character_ids == ['ari'] for scene in view.scenes)
    assert source.model_dump() == original
    assert source.scenes[0].character_ids == ['ari', 'visitor', 'visitor']


def test_author_additions_and_existing_reference_authorities_are_retained(tmp_path):
    source = bible()
    source.characters[-1].origin = 'author'
    path = artifacts.character_ref_sheet_path(tmp_path, 'visitor')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'retained-reference')
    assert cast_character_ids(source, tmp_path) == {'ari', 'visitor', 'guard'}


def test_a_tiny_story_keeps_its_participants():
    source = bible()
    source.scenes = source.scenes[:2]
    source.total_scenes = 2
    assert cast_character_ids(source) == {'ari', 'visitor', 'guard'}


def test_explicit_character_requests_can_include_an_incidental_participant():
    source = bible()
    assert [character.id for character in cast_story_bible(source, character_ids=['visitor']).characters] == ['ari', 'visitor']
    assert cast_character_ids(source) == {'ari'}


def test_a_plot_critical_creature_is_designed_even_for_one_scene():
    source = bible()
    source.characters[-1].cast_required = True
    assert cast_character_ids(source) == {'ari', 'guard'}


def test_later_parts_promote_an_incidental_identity_without_renumbering(tmp_path):
    source = bible()
    artifacts.write_story_bible(tmp_path, source)
    before = cast_inventory_keys(tmp_path)
    assert before == {('ari', None)}
    source.scenes.append(source.scenes[-1].model_copy(update={
        'id': 'later_scene', 'part_id': 'part_0002', 'character_ids': ['visitor']}))
    artifacts.write_story_bible(tmp_path, source)
    assert cast_inventory_keys(tmp_path) - before == {('visitor', None)}
    assert [c.id for c in source.characters] == ['ari', 'visitor', 'guard']


def test_plan_keeps_incidental_identity_and_does_not_require_missing_cast_bytes(tmp_path):
    source = bible()
    artifacts.write_story_bible(tmp_path, source)
    inventory = approved_visual_inventory(tmp_path)
    assert {ref.entity_id for ref in inventory.references} == {'ari', 'visitor', 'guard'}
    assert {ref.entity_id for ref in inventory.references if ref.requires_image} == {'ari'}
    assert set(approved_reference_files(tmp_path)) == {'ari:base'}


def test_minor_states_keep_the_carried_crown_reference_without_another_paid_image(tmp_path):
    source = bible()
    character = source.characters[0]
    character.appearance_states = [
        AppearanceState(id='crowned', label='Crowned', visual_anchor='adult, black hair, crown', visually_significant=True),
        AppearanceState(id='scratched', label='Scratched', visual_anchor='adult, black hair, crown, scratch'),
        AppearanceState(id='returned', label='Returned', visual_anchor=character.visual_anchor, canonical_equivalent=True),
        AppearanceState(id='dusty', label='Dusty', visual_anchor='adult, black hair, dust'),
    ]
    character.appearance_timeline = [StateActivation(state_id=state, at=StoryPosition(scene_id=f'scene_{index}'))
                                    for index, state in enumerate(['crowned', 'scratched', 'returned', 'dusty'], 2)]
    artifacts.write_story_bible(tmp_path, source)

    files = approved_reference_files(tmp_path)

    assert files['ari:scratched'].path == artifacts.character_state_ref_sheet_path(tmp_path, 'ari', 'crowned')
    assert files['ari:scratched'].metadata_path == artifacts.asset_meta_path(files['ari:crowned'].path)
    assert files['ari:returned'].path == files['ari:base'].path
    assert files['ari:dusty'].path == files['ari:base'].path
    assert {file.path for file in files.values()} == {files['ari:base'].path, files['ari:crowned'].path}
