"""The reported defect classes are corrected before Extract publishes a Bible."""

import asyncio
import json

import pytest

from novel_to_comic.briefing import build_brief_inference_prompt, story_page_envelope
from novel_to_comic.cast_roster import cast_character_ids
from novel_to_comic.config import Config
from novel_to_comic.extraction_review import ExtractionReview, PartEndLook, apply_source_review, end_look_candidates
from novel_to_comic.models.story_bible import Character, Location, StorySequence, Scene, StoryBible, TransientObject
from novel_to_comic.models.appearance import AppearanceState, StateActivation, StoryPosition
from novel_to_comic.source_extraction import SourceSceneAnchor, build_source_document, source_units
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import create_initial_state
from novel_to_comic.stages import s1_extract, s2_brief
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult


PASSAGES = (
    "Mira entered the vault. A burrowing king attacked her. The grubs swarmed. A discarded tooth lay nearby.",
    "Mira equipped a blue jeweled crown. Two gray hounds snapped at her.",
    "A red tattoo appeared on Mira's face. She stood six feet tall.",
    "Mira returned to her unmarked form. Her crown stayed on.",
    "Mira took off the crown.",
    "ABOUT THE AUTHOR\nJoin the reading club and browse these recommendations.",
)
TEXT = "\n\n".join(PASSAGES)


def evidence(index, quote=None):
    return [{'scene_id': f'scene_{index}', 'source_quote': quote or PASSAGES[index - 1]}]


def bible():
    mira = Character(id='char_mira', name='Mira', visual_anchor='1girl, teenage girl, black hair',
        age_range='13', gender='female', distinguishing_features=[], default_outfit='plain shirt',
        first_appearance_scene='scene_1', appearance_states=[
            AppearanceState(id='tattoo', label='Facial tattoo', visual_anchor='1girl, teenage girl, black hair, red facial tattoo',
                            changed_facets=('color',), continuity_guard='Keep the red facial tattoo visible.'),
            AppearanceState(id='return', label='Unmarked', visual_anchor='1girl, teenage girl, black hair',
                            canonical_equivalent=True, changed_facets=('color',))],
        appearance_timeline=[StateActivation(state_id='tattoo', at=StoryPosition(scene_id='scene_3')),
                             StateActivation(state_id='return', at=StoryPosition(scene_id='scene_4'))])
    hound = Character(id='char_hound_a', name='Gray hound A', visual_anchor='gray fur, long fangs',
                      age_range='', gender='', distinguishing_features=[], default_outfit='', first_appearance_scene='scene_2',
                      identity_kind='interchangeable')
    scenes = [Scene(id=f'scene_{index}', chapter=1, title=f'Event {index}', location_id='loc_vault',
        character_ids=([mira.id, hound.id, 'char_hound_b'] if index == 2 else [mira.id]) if index < 6 else [],
        summary=passage, scene_type='action', narrative_beat='rising_action',
        source_start_quote=source_units(passage)[0].text.strip()) for index, passage in enumerate(PASSAGES, 1)]
    scenes[0].transient_objects = [
        TransientObject(id='trans_king', name='Burrowing king', visual_anchor='large pink creature'),
        TransientObject(id='trans_tooth', name='Discarded tooth', visual_anchor='broken tooth')]
    return StoryBible(title='Vault', author='Unknown', total_scenes=6,
        characters=[mira, hound, hound.model_copy(update={'id': 'char_hound_b', 'name': 'Gray hound B'})],
        locations=[Location(id='loc_vault', name='Vault', visual_anchor='stone vault', mood='tense')], scenes=scenes,
        sequences=[StorySequence(number=act, title=f'Act {act}', scenes=[s.id for s in scenes] if act == 1 else [])
                        for act in (1, 2, 3)])


def new_character(identifier, name, anchor, scene=1, group=False, required=False):
    return dict(id=identifier, name=name, visual_anchor=anchor, age_range='', gender='',
                distinguishing_features=[], default_outfit='', first_appearance_scene=f'scene_{scene}',
                identity_kind='group' if group else 'individual', cast_required=required, evidence=evidence(scene))


def review():
    return ExtractionReview.model_validate(dict(
        characters=[new_character('audit_king', 'Burrowing king', 'large pink creature', required=True),
                    new_character('audit_grubs', 'Grubs', 'small burrowing worms', group=True, required=True)],
        character_details=[dict(id='char_mira', distinguishing_features=['Six feet tall'], evidence=evidence(3))],
        creature_groups=[dict(character=new_character('audit_hounds', 'Two gray hounds', 'gray fur, long fangs',
                                                     scene=2, group=True), member_ids=['char_hound_a', 'char_hound_b'])],
        props=[dict(id='audit_crown', name='Crown', visual_anchor='blue jeweled crown',
                    first_appearance_scene='scene_2', evidence=evidence(2))],
        scene_details=[dict(id='scene_1', character_ids=['audit_king', 'audit_grubs'],
                            remove_transient_object_ids=['trans_king'], evidence=evidence(1)),
                       dict(id='scene_6', non_narrative=True, evidence=evidence(6))],
        persistent_accessories=[dict(id='crown', character_id='char_mira', label='Crowned',
            visual_anchor='blue jeweled crown', at=dict(scene_id='scene_2', beat=1),
            until=dict(scene_id='scene_5', beat=1), evidence=evidence(2))],
        part_end_looks=[dict(character_id='char_mira', state_id=None, evidence=evidence(5))]))


def test_source_review_promotes_actors_groups_copies_and_excludes_back_matter_without_rewriting_source():
    original = bible()
    changes = review()
    snapshot = original.model_dump()
    review_snapshot = changes.model_dump()
    result = apply_source_review(original, changes, TEXT, part_id='part_0001')
    assert original.model_dump() == snapshot
    assert changes.model_dump() == review_snapshot
    assert {c.id for c in result.characters} == {'char_mira', 'audit_king', 'audit_grubs', 'audit_hounds'}
    assert result.scenes[1].character_ids == ['char_mira', 'audit_hounds']
    assert result.scenes[1].summary == PASSAGES[1]  # member count/action retained
    assert [o.id for o in result.scenes[0].transient_objects] == ['trans_tooth']
    assert {'audit_king', 'audit_grubs'} <= set(result.scenes[0].character_ids)
    assert {'audit_king', 'audit_grubs'} <= cast_character_ids(result)
    assert 'audit_hounds' not in cast_character_ids(result)  # incidental copies do not cost paid sheets
    assert result.characters[0].visual_anchor == original.characters[0].visual_anchor
    assert result.characters[0].distinguishing_features == ['Six feet tall']
    assert result.scenes[-1].scene_type == 'non_narrative'
    assert result.scenes[-1].location_id is None
    assert 'scene_6' not in result.sequences[0].scenes
    source = build_source_document(TEXT, [SourceSceneAnchor(id=s.id, title=s.title,
        opening_quote=s.source_start_quote, start_offset=s.source_start_offset) for s in result.scenes])
    assert source.text == TEXT and ''.join(u.text for u in source.units) == TEXT
    assert source.scenes[-1].last_unit_id == source.units[-1].id


def test_unresolved_scene_opening_reaches_the_repair_prompt_with_its_exact_sentence():
    original = bible()
    # A near-miss the model typed from memory; the source sentence is unique enough to name.
    original.scenes[4].source_start_quote = 'Mira took the crown off.'
    with pytest.raises(s1_extract._UnresolvedSceneOpenings, match='scene_5') as error:
        apply_source_review(original, review(), TEXT, part_id='part_0001')
    assert [scene_id for scene_id, _, _ in error.value.openings] == ['scene_5']
    correction = s1_extract._participation_quote_correction(error.value)
    assert "scene_id='scene_5'" in correction
    assert 'entire corrected Story Bible JSON object' in correction


def test_equipment_carries_through_minor_looks_and_base_return_until_explicit_removal():
    original = bible()
    result = apply_source_review(original, review(), TEXT, part_id='part_0001')
    character = result.characters[0]
    states = {s.id: s for s in character.appearance_states}
    timeline = {a.at.scene_id: states[a.state_id] for a in character.appearance_timeline}
    for scene_id in ('scene_2', 'scene_3', 'scene_4'):
        assert 'blue jeweled crown' in timeline[scene_id].visual_anchor
        assert timeline[scene_id].canonical_equivalent is False
        assert 'blue jeweled crown' in timeline[scene_id].continuity_guard
    assert timeline['scene_3'].visually_significant is False
    assert timeline['scene_3'].continuity_guard.startswith(original.characters[0].appearance_states[0].continuity_guard)
    assert timeline['scene_2'].id == timeline['scene_4'].id
    assert 'crown' not in timeline['scene_5'].visual_anchor
    assert timeline['scene_5'].canonical_equivalent is True
    assert states['tattoo'].visual_anchor == original.characters[0].appearance_states[0].visual_anchor
    assert states['tattoo'].continuity_guard == original.characters[0].appearance_states[0].continuity_guard
    assert sum(s.visually_significant for s in character.appearance_states) == 1


def test_explicit_earlier_life_interval_does_not_inherit_a_later_acquired_item():
    earlier = 'Earlier that day, Mira waited with her unmarked face and bare head.'
    original = bible()
    original.scenes[3].source_start_quote = earlier
    original.scenes[3].summary = earlier
    text = TEXT.replace(PASSAGES[3], earlier)
    data = review().model_dump(mode='json')
    data['persistent_accessories'][0]['absent_intervals'] = [dict(
        at=dict(scene_id='scene_4'), until=dict(scene_id='scene_5'), evidence=evidence(4, earlier))]
    changes = ExtractionReview.model_validate(data)
    result = apply_source_review(original, changes, text, part_id='part_0001')
    character = result.characters[0]
    states = {state.id: state for state in character.appearance_states}
    looks = {(a.at.scene_id, a.at.beat): states[a.state_id] for a in character.appearance_timeline}
    assert 'crown' not in looks[('scene_4', None)].visual_anchor
    assert 'blue jeweled crown' in looks[('scene_5', None)].visual_anchor
    assert 'crown' not in looks[('scene_5', 1)].visual_anchor


def test_live_actor_addition_already_supplies_membership_without_a_redundant_scene_roster():
    changes = review()
    changes.scene_details[0].character_ids = []
    result = apply_source_review(bible(), changes, TEXT, part_id='part_0001')
    assert {'audit_king', 'audit_grubs'} <= set(result.scenes[0].character_ids)
    assert [obj.id for obj in result.scenes[0].transient_objects] == ['trans_tooth']


@pytest.mark.parametrize('variant', ['wrong_evidence', 'protected_member', 'different_look', 'named_individual',
                                   'removal_before_acquisition'])
def test_review_cannot_invent_evidence_merge_prior_authorities_or_erase_a_distinct_look(variant):
    original = bible()
    changes = review()
    protected = frozenset()
    if variant == 'wrong_evidence':
        changes.character_details[0].evidence[0].source_quote = 'Mira grew wings and flew away.'
    elif variant == 'protected_member':
        protected = frozenset({'char_hound_a'})
    elif variant == 'different_look':
        original.characters[-1].visual_anchor += ', one eye'
    elif variant == 'named_individual':
        original.characters[-1].name = 'Cedar'
        original.characters[-1].identity_kind = 'individual'
    else:
        changes.persistent_accessories[0].until.scene_id = 'scene_1'
    snapshot = original.model_dump()
    with pytest.raises(ValueError):
        apply_source_review(original, changes, TEXT, part_id='part_0001', protected_character_ids=protected)
    assert original.model_dump() == snapshot


def test_evidence_is_grounded_in_code_and_only_words_outside_the_source_are_rejected():
    # A section cut once split one action beat into two scenes; the model's
    # description of the goblins crossed that boundary and three paid attempts
    # failed. Evidence is checked and discarded, so code settles where it sits.
    spanning = "Two gray hounds snapped at her.\n\nA red tattoo appeared on Mira's face."
    changes = review()
    changes.props[0].evidence[0].source_quote = spanning
    apply_source_review(bible(), changes, TEXT, part_id='part_0001')

    # Words that begin in the neighbouring scene are a boundary drawn one sentence away.
    changes.props[0].evidence[0].source_quote = "She stood six feet tall."
    apply_source_review(bible(), changes, TEXT, part_id='part_0001')
    # Typographic quotes and a dropped ending are still that scene's sentence.
    changes.props[0].evidence[0].source_quote = "Mira equipped a blue jeweled crown, shining"
    changes.character_details[0].evidence[0].source_quote = "A red tattoo appeared on Mira’s face."
    apply_source_review(bible(), changes, TEXT, part_id='part_0001')

    # An actor cited far from its words joins the scene that owns them.
    changes = review()
    changes.characters[0].evidence[0].scene_id = 'scene_4'
    result = apply_source_review(bible(), changes, TEXT, part_id='part_0001')
    assert 'audit_king' in result.scenes[0].character_ids and 'audit_king' not in result.scenes[3].character_ids

    # A correction to one exact scene cannot borrow a distant scene's words.
    changes = review()
    changes.scene_details[1].evidence[0].source_quote = "Mira equipped a blue jeweled crown."
    with pytest.raises(ValueError) as error:
        apply_source_review(bible(), changes, TEXT, part_id='part_0001')
    assert 'Those words are in scene scene_2' in str(error.value)
    assert 'Scene scene_6 runs from "ABOUT THE AUTHOR Join the reading club' in str(error.value)

    changes = review()
    changes.props[0].evidence[0].source_quote = "Mira flew away."
    with pytest.raises(ValueError, match='not verbatim source text'):
        apply_source_review(bible(), changes, TEXT, part_id='part_0001')


def test_whole_source_applies_review_on_first_response_instead_of_a_paid_repair():
    original = bible()
    raw = original.model_dump(mode='json')
    raw['source_review'] = review().model_dump(mode='json')
    raw['character_participation'] = [dict(character_id=cid, scene_id=scene.id,
        classification='direct_action', source_quote=scene.source_start_quote)
        for scene in original.scenes for cid in scene.character_ids]
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        assert len(calls) == 1
        return ApiResult(value=raw)

    result = asyncio.run(s1_extract._extract_with_retry(Config(), 'source analyst', TEXT, generate=generate))
    assert len(calls) == 1
    assert result.value.scenes[0].character_ids == ['char_mira', 'audit_king', 'audit_grubs']
    assert result.value.scenes[-1].scene_type == 'non_narrative'


def test_brief_sees_source_grounded_identity_equipment_and_short_lived_principal_actors():
    result = apply_source_review(bible(), review(), TEXT, part_id='part_0001')
    source = build_source_document(TEXT, [SourceSceneAnchor(id=s.id, title=s.title,
        opening_quote=s.source_start_quote, start_offset=s.source_start_offset) for s in result.scenes])
    prompt = build_brief_inference_prompt(source, result)
    context = json.loads(prompt.split('\n', 1)[1])
    story = context['story_bible']
    assert {'audit_king', 'audit_grubs'} <= set(story['cast_character_ids'])
    assert story['characters'][0]['distinguishing_features'] == ['Six feet tall']
    looks = story['visual_continuity']['char_mira']
    assert any('blue jeweled crown' in state['visual_anchor'] for state in looks['states'])
    assert context['source_scenes'][-1]['scene_type'] == 'non_narrative'
    assert ''.join(scene['text'] for scene in context['source_scenes']) == TEXT
    assert story_page_envelope(source, result) == (5, 7)


@pytest.mark.parametrize('age,anchor', [('13', '1girl, 130 pounds, number 23 jersey'),
                                      ('teenage girl', '1girl, 200cm tall'),
                                      ('', '1girl, 2 dogs, 23 jersey'), ('16-19', '1girl, 130 pounds')])
def test_measurements_and_counts_do_not_turn_stated_young_characters_into_adults(age, anchor):
    character = dict(id='child', name='Youth', age_range=age, gender='female', visual_anchor=anchor)
    s1_extract._normalize_character_anchor_tags([character])
    assert character['visual_anchor'].startswith('1girl')


@pytest.mark.parametrize('anchor', ['1woman, adult female, black hair', 'woman, black hair'])
def test_stated_minor_age_corrects_a_provisional_adult_identity_label(anchor):
    character = dict(id='child', name='Youth', age_range='13', gender='female', visual_anchor=anchor)
    s1_extract._normalize_character_anchor_tags([character])
    assert 'woman' not in character['visual_anchor'] and 'adult' not in character['visual_anchor']
    assert 'girl' in character['visual_anchor']


def test_sectioned_extract_and_brief_use_the_existing_call_graph_and_cache_source_review(tmp_path, monkeypatch):
    from novel_to_comic import extraction_sections
    from novel_to_comic.clients import structured_call

    text = ('THE CAVE\nBy A. Example\nMira, a thirteen-year-old girl, entered in a plain shirt. '
            + ''.join(f'Mira crossed cave marker {i}. ' for i in range(180))
            + 'The worm queen bit Mira. Mira stood six feet tall. '
            + ''.join(f'Mira returned past marker {i}. ' for i in range(180)))
    (tmp_path / 'novel.txt').write_text(text)
    config = Config(extraction_chunk_chars=4000)
    calls = []
    seen_brief = []

    async def generate(**kwargs):
        calls.append(kwargs['feature'])
        if kwargs['feature'] == 'brief.infer':
            context = json.loads(kwargs['user_content'].split('\n', 1)[1])
            seen_brief.append(context)
            assert 'p0001audit_queen' in context['story_bible']['cast_character_ids']
            assert any(c['distinguishing_features'] == ['Six feet tall'] for c in context['story_bible']['characters'])
            return ApiResult(value=dict(essential_events=['Mira survives the worm queen.'],
                desired_emphasis=['The worm queen attack.'], target_page_min=6, target_page_max=12))
        context = json.loads(kwargs['user_content'])
        if kwargs['feature'] == 'extract.sequences':
            assert context['source_text'] == text  # the reviewer sees omitted events, not only summaries
            assert 'source_review' in kwargs['json_schema']['properties']
            ids = [s['id'] for s in context['scenes']]
            position = text.index('The worm queen bit Mira.')
            scene_id = next(s['id'] for s in context['scenes']
                            if s['source_start_offset'] <= position < s['source_end_offset'])
            return ApiResult(value=dict(title='The Cave', author='A. Example', sequences=[
                dict(number=act, title=f'Act {act}', scenes=ids if act == 1 else []) for act in (1, 2, 3)],
                source_review=dict(characters=[dict(id='p0001audit_queen', name='Worm queen',
                    visual_anchor='burrowing worm', age_range='', gender='', distinguishing_features=[],
                    default_outfit='', first_appearance_scene=scene_id, cast_required=True,
                    evidence=[dict(scene_id=scene_id, source_quote='The worm queen bit Mira.')])],
                    character_details=[dict(id='p0001s0001_char_mira', distinguishing_features=['Six feet tall'],
                        evidence=[dict(scene_id=scene_id, source_quote='Mira stood six feet tall.')])])))
        index = context['section']
        scene_id = context['id_prefix'] + 'scene_1'
        character = dict(id='p0001s0001_char_mira', name='Mira', visual_anchor='teenage girl', age_range='13',
                         gender='female', distinguishing_features=[], default_outfit='plain shirt',
                         first_appearance_scene=scene_id) if index == 1 else {'id': 'p0001s0001_char_mira'}
        value = dict(title='The Cave', author='A. Example', characters=[character],
            locations=[dict(id='p0001s0001_loc_cave', name='Cave', visual_anchor='cave', mood='tense')]
                      if index == 1 else [], scenes=[dict(id=scene_id, chapter=1, title='Crossing',
                location_id='p0001s0001_loc_cave', character_ids=['p0001s0001_char_mira'], summary='Mira crosses the cave.',
                scene_type='action', narrative_beat='rising_action',
                source_start_quote=context['required_first_scene_source_start_quote'])], props=[],
            character_participation=[dict(character_id='p0001s0001_char_mira', scene_id=scene_id,
                classification='direct_action', source_quote=context['required_first_scene_source_start_quote'])])
        assert 'source_review' not in kwargs['json_schema']['properties']
        return ApiResult(value=value)

    monkeypatch.setattr(extraction_sections, 'generate_json', generate)
    monkeypatch.setattr(structured_call, 'generate_json', generate)
    state = create_initial_state('test', 'novel.txt')

    async def run():
        result = await s1_extract.run(config, tmp_path, StageRuntime('extract', state, tmp_path))
        assert any(c.id == 'p0001audit_queen' for c in result.characters)
        expected = len(extraction_sections.split_source(text, 4000)) + 1
        assert len(calls) == expected  # sections plus the existing organization call
        await s1_extract.run(config, tmp_path, StageRuntime('extract', state, tmp_path))
        assert len(calls) == expected  # completed review revalidates from its exact cache
        await s2_brief.run(config, tmp_path, StageRuntime('brief', state, tmp_path))
        assert len(calls) == expected + 1

    asyncio.run(run())
    assert len(seen_brief) == 1
    source = TargetArtifacts(tmp_path).read_source()
    assert source.text == text and ''.join(unit.text for unit in source.units) == text
    assert TargetArtifacts(tmp_path).read_brief().essential_events == ('Mira survives the worm queen.',)


def test_a_transformation_still_running_at_the_part_end_must_be_reported_and_closed():
    # Three runs left a transformed companion transformed after the text
    # showed her back in her own body; the next part inherited the wrong look.
    original = bible()
    original.characters[0].appearance_timeline = original.characters[0].appearance_timeline[:1]
    original.characters[0].appearance_states = original.characters[0].appearance_states[:1]
    changes = ExtractionReview()
    with pytest.raises(ValueError, match=r"Report part_end_looks for: Mira \(char_mira\), latest look tattoo"):
        apply_source_review(original, changes, TEXT, part_id='part_0001', require_end_looks=True)

    changes.part_end_looks = [PartEndLook(character_id='char_mira', state_id=None, evidence=evidence(4))]
    with pytest.raises(ValueError, match='give since'):
        apply_source_review(original, changes, TEXT, part_id='part_0001', require_end_looks=True)

    changes.part_end_looks[0].since = StoryPosition(scene_id='scene_4', beat=1)
    result = apply_source_review(original, changes, TEXT, part_id='part_0001', require_end_looks=True)
    mira = result.characters[0]
    returned = {state.id: state for state in mira.appearance_states}[mira.appearance_timeline[-1].state_id]
    assert returned.canonical_equivalent and returned.visual_anchor == mira.visual_anchor
    assert mira.appearance_timeline[-1].at == StoryPosition(scene_id='scene_4', beat=1)

    # A look the text keeps to the end needs only the confirmation.
    changes.part_end_looks = [PartEndLook(character_id='char_mira', state_id='tattoo', evidence=evidence(4))]
    kept = apply_source_review(original, changes, TEXT, part_id='part_0001', require_end_looks=True)
    assert [a.state_id for a in kept.characters[0].appearance_timeline] == ['tattoo']
    assert end_look_candidates(original, 'part_0001')[0]['latest_state_id'] == 'tattoo'


def accessory(identifier, label, anchor, scene, *, significant=True, removes=(), until=None):
    return dict(id=identifier, character_id='char_mira', label=label, visual_anchor=anchor,
                removes_tags=list(removes), at=dict(scene_id=f'scene_{scene}'),
                until=dict(scene_id=f'scene_{until}') if until else None,
                visually_significant=significant, evidence=evidence(scene))


def test_worn_items_compose_readable_looks_that_only_enforce_what_is_visible():
    original = bible()
    original.characters[0].cast_required = True
    original.characters[0].visual_anchor += ', plain shirt, pink sandals'
    changes = ExtractionReview.model_validate(dict(persistent_accessories=[
        accessory('lost_sandals', 'Lost sandals', 'bare feet.', 2, removes=['pink sandals']),
        accessory('cloak', 'Bone cloak', 'black hooded cloak, Cool to the touch.', 2),
        accessory('ring', 'Toe ring', 'silver toe ring', 2, significant=False)]))
    result = apply_source_review(original, changes, TEXT, part_id='part_0001')
    mira = result.characters[0]
    states = {state.id: state for state in mira.appearance_states}
    look = states[mira.appearance_timeline[0].state_id]
    assert look.label == 'Lost sandals, Bone cloak and Toe ring'
    assert look.visual_anchor == ('1girl, teenage girl, black hair, plain shirt, bare feet, black hooded cloak, '
                                  'Cool to the touch, silver toe ring')
    assert 'pink sandals' not in look.visual_anchor and '.,' not in look.visual_anchor
    assert 'Keep the Bone cloak visible' in look.continuity_guard
    assert 'Never draw pink sandals (Lost sandals).' in look.continuity_guard
    assert 'toe ring' not in look.continuity_guard
    # The look a principal ends the part in carries forward and gets a reference.
    final = states[mira.appearance_timeline[-1].state_id]
    assert final.visually_significant and not final.canonical_equivalent


def test_a_loss_must_name_tags_the_look_actually_has():
    original = bible()
    changes = ExtractionReview.model_validate(dict(persistent_accessories=[
        accessory('lost_boots', 'Lost boots', 'bare feet', 2, removes=['leather boots'])]))
    with pytest.raises(ValueError, match=r"must be exact tags of Mira's look at scene_2: \['1girl'"):
        apply_source_review(original, changes, TEXT, part_id='part_0001')


def test_review_moves_a_scene_to_the_place_its_action_happens():
    changes = ExtractionReview.model_validate(dict(
        locations=[dict(id='audit_lair', name='Lair', visual_anchor='low cave lit by blue moss', mood='close',
                        evidence=evidence(2))],
        scene_details=[dict(id='scene_2', location_id='audit_lair', evidence=evidence(2))]))
    result = apply_source_review(bible(), changes, TEXT, part_id='part_0001')
    assert result.scenes[1].location_id == 'audit_lair'
    assert 'audit_lair' in {location.id for location in result.locations}

    unused = ExtractionReview.model_validate(dict(locations=changes.model_dump()['locations']))
    with pytest.raises(ValueError, match='is no scene'):
        apply_source_review(bible(), unused, TEXT, part_id='part_0001')


def test_extraction_rejects_a_formation_sheet_for_one_entity():
    from novel_to_comic.stages.s1_extract import _check_character_looks

    eye = {"id": "eye", "name": "Cosmic Eye", "identity_kind": "individual",
           "reference_form": "formation", "visual_anchor": "gigantic eye", "appearance_states": []}
    with pytest.raises(ValueError, match="reference_form 'formation' but is not identity_kind 'group'"):
        _check_character_looks([eye])
    _check_character_looks([{**eye, "identity_kind": "group"}])
    _check_character_looks([{**eye, "reference_form": "form"}])


UNPUNCTUATED_LOG = (
    "Afterword: The vocabulary grew.\n\n"
    "29/08/2018\n\nROUND 6 TESTS (VOCABULARY) - RESULTS\n\n"
    "Foods\n\nCHICKEN TURKEY PORK\n\n"
    "30/06/2019\n\nUPDATE\n\nSCP-5031 has said its first word: \"Salt\".\n\n"
    "29/11/2019\n\nFINAL TEST - SUMMARY\n\nA three-course meal was served.\n"
)


def test_headings_and_dates_without_punctuation_are_separate_units_so_adjacent_scenes_resolve():
    from novel_to_comic.models.source import sentence_end_offsets
    from novel_to_comic.source_extraction import align_scene_openings

    assert all(UNPUNCTUATED_LOG[end - 1].isspace() or end == len(UNPUNCTUATED_LOG)
               for end in sentence_end_offsets(UNPUNCTUATED_LOG))
    # A PDF page break inside a sentence is joined as a blank line; it is not a boundary.
    page_break = "He watched the ice slur clumsily\n\nabout. Then he spoke.\n\nChapter 2\n\nMorning came."
    assert [page_break[:end] for end in sentence_end_offsets(page_break)][:2] == [
        "He watched the ice slur clumsily\n\nabout. ", "He watched the ice slur clumsily\n\nabout. Then he spoke.\n\n"]
    assert "Chapter 2\n\n" in [page_break[start:end] for start, end in zip(
        (0, *sentence_end_offsets(page_break)), sentence_end_offsets(page_break))]
    scenes = [Scene(id=f'scene_{index}', chapter=1, title=title, location_id='loc_vault', character_ids=[],
                    summary=title, scene_type='action', narrative_beat='rising_action', source_start_quote=quote)
              for index, (title, quote) in enumerate([
                  ('Round 6', 'ROUND 6 TESTS (VOCABULARY) - RESULTS'),
                  ('Update', 'UPDATE'),
                  ('Final test', 'FINAL TEST - SUMMARY')], 1)]
    assert align_scene_openings(scenes, UNPUNCTUATED_LOG) == ()
    assert [scene.source_start_quote for scene in scenes] == [
        'ROUND 6 TESTS (VOCABULARY) - RESULTS', 'UPDATE', 'FINAL TEST - SUMMARY']


def _whole_source_response(quote, *, move_return_look=False):
    original = bible()
    raw = original.model_dump(mode='json')
    raw['source_review'] = review().model_dump(mode='json')
    raw['character_participation'] = [dict(character_id=cid, scene_id=scene.id,
        classification='direct_action', source_quote=scene.source_start_quote)
        for scene in original.scenes for cid in scene.character_ids]
    raw['scenes'][4]['source_start_quote'] = quote
    if move_return_look:
        raw['characters'][0]['appearance_timeline'][1]['at'] = {'scene_id': 'scene_5', 'beat': None}
    return raw


def _extract_with_an_uncopyable_opening(raw):
    calls, reports = [], []

    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=json.loads(json.dumps(raw)))

    result = asyncio.run(s1_extract._extract_with_retry(
        Config(), 'source analyst', TEXT, generate=generate, report=reports.append,
        validate=s1_extract._check_whole_source_sequences))
    return result.value, calls, reports


def test_an_opening_the_model_never_copies_exactly_is_placed_instead_of_failing_extract():
    # Production failure: three whole-bible responses kept one near-miss opening and Extract was lost.
    value, calls, reports = _extract_with_an_uncopyable_opening(_whole_source_response('Mira took the crown off.'))
    assert len(calls) == 1  # a correction regenerates the whole Story Bible; none is spent on a quote
    assert [scene.id for scene in value.scenes] == [f'scene_{index}' for index in range(1, 7)]
    assert value.scenes[4].source_start_quote == 'Mira took off the crown.'
    assert reports == ['Scene openings the model did not copy exactly from the source were settled without '
                       'another call: scene_5 placed at its closest source sentence.']
    build_source_document(TEXT, [SourceSceneAnchor(id=s.id, title=s.title, opening_quote=s.source_start_quote)
                                 for s in value.scenes])


def test_a_scene_with_no_source_boundary_is_merged_into_the_scene_that_owns_its_sentences():
    value, calls, reports = _extract_with_an_uncopyable_opening(
        _whole_source_response('The dragon swallowed the moon.', move_return_look=True))
    assert len(calls) == 1
    assert [scene.id for scene in value.scenes] == ['scene_1', 'scene_2', 'scene_3', 'scene_4', 'scene_6']
    assert value.total_scenes == 5
    assert value.scenes[3].summary == f'{PASSAGES[3]} {PASSAGES[4]}'
    assert all('scene_5' not in sequence.scenes for sequence in value.sequences)
    # The look that began in the merged scene now begins after the earlier scene's own beats.
    returned = [a.at for a in value.characters[0].appearance_timeline if a.state_id == 'return']
    assert returned[0].scene_id == 'scene_4' and returned[0].beat >= 1
    assert reports and reports[0].endswith('scene_5 merged into scene_4.')
    source = build_source_document(TEXT, [SourceSceneAnchor(id=s.id, title=s.title, opening_quote=s.source_start_quote)
                                          for s in value.scenes])
    assert ''.join(unit.text for unit in source.units) == TEXT


def test_settled_openings_leave_the_correction_for_what_only_the_model_can_fix():
    wrong = _whole_source_response('The dragon swallowed the moon.')
    del wrong['characters'][0]['appearance_states'][0]['changed_facets']
    right = _whole_source_response('Mira took off the crown.')
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=wrong if len(calls) == 1 else right)

    value = asyncio.run(s1_extract._extract_with_retry(
        Config(), 'source analyst', TEXT, generate=generate, validate=s1_extract._check_whole_source_sequences)).value
    assert len(calls) == 2 and len(value.scenes) == 6
    assert 'changed_facets' in calls[1]['user_content'] and 'UNRESOLVED SCENE OPENINGS' not in calls[1]['user_content']


def test_a_first_scene_with_no_sentence_of_its_own_shares_the_second_scenes_opening():
    raw = _whole_source_response(PASSAGES[4])
    raw['scenes'][0]['source_start_quote'] = 'Nothing like the source.'
    raw['scenes'][1]['source_start_quote'] = PASSAGES[0]
    value, calls, reports = _extract_with_an_uncopyable_opening(raw)
    assert len(calls) == 1
    assert [scene.id for scene in value.scenes] == ['scene_1', 'scene_3', 'scene_4', 'scene_5', 'scene_6']
    assert value.scenes[0].source_start_quote == 'Mira entered the vault.'
    assert reports and reports[0].endswith('scene_2 merged into scene_1.')


def test_a_dated_heading_copied_with_its_line_break_as_a_space_is_an_exact_opening():
    # SCP-5031 opens every entry on a date and a heading too short for fuzzy matching.
    from novel_to_comic.source_extraction import align_scene_openings

    text = ('Item #: SCP-5031\n\nObject Class: Keter\n\n30/06/2019\n\nUPDATE\n\n'
            'SCP-5031 has said its first word: "Salt".\n\n29/11/2019\n\nFINAL TEST - SUMMARY\n\nTesting concluded.')
    scenes = [s1_extract._SceneOpening(id=f's{index}', source_start_quote=quote) for index, quote in enumerate(
        ('Item #: SCP-5031', '30/06/2019 UPDATE', '29/11/2019\nFINAL TEST - SUMMARY'), 1)]
    assert align_scene_openings(scenes, text) == ()
    assert [scene.source_start_quote for scene in scenes] == ['Item #: SCP-5031', '30/06/2019', '29/11/2019']


def test_openings_settle_only_between_their_resolved_neighbours():
    from novel_to_comic.source_extraction import settle_scene_openings

    text = 'Ann woke; later Bob left the house in a hurry. Cy sang. Dee ran. Cy sang again.'

    def openings(*quotes):
        return [s1_extract._SceneOpening(id=f's{index}', source_start_quote=quote)
                for index, quote in enumerate(quotes, 1)]

    # A scene that starts inside the previous scene's opening sentence takes the next one.
    fused = openings('Ann woke; later Bob left the house in a hurry.', 'later Bob left the house in a hurry.', 'Dee ran.')
    assert settle_scene_openings(fused, text) == ({'s2': 'Cy sang.'}, ())
    assert fused[1].source_start_quote == 'later Bob left the house in a hurry.'  # nothing is mutated
    # The first scene owns the start of the text; an invented later opening has no boundary.
    assert settle_scene_openings(openings('Invented words here.', 'Dee ran.', 'Nothing like the source.'), text) == (
        {'s1': 'Ann woke; later Bob left the house in a hurry.'}, ('s3',))
    # A sentence that also occurs before the previous scene is never matched backwards.
    assert settle_scene_openings(openings('Dee ran.', 'Cy sang, again.'), text) == ({'s2': 'Cy sang again.'}, ())
    # Recorded offsets are exact provenance, never re-guessed.
    stale = openings('Ann woke; later Bob left the house in a hurry.', 'Dee ran.')
    stale[1].source_start_offset = 3
    assert settle_scene_openings(stale, text) == ({}, ('s2',))
