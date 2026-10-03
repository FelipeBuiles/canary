"""Request contracts prevent structural repairs before a provider submission."""

import json
import re

import pytest

from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
from novel_to_comic.ai.codex_schema import strict_output_schema
from novel_to_comic.extraction_schema import extraction_schema
from novel_to_comic.models.story_bible import Character, Location, Prop, StoryBible
from novel_to_comic.stages.s1_extract import PROMPT_PATH, WHOLE_SOURCE_INSTRUCTIONS
from novel_to_comic.extraction_sections import organization_schema, section_instructions


def registry():
    character = Character(
        id='part0001_char_001', name='Ari', visual_anchor='adult, black hair',
        age_range='adult', gender='female', distinguishing_features=[],
        default_outfit='coat', first_appearance_scene='part0001_scene_001')
    return StoryBible(
        title='Crossing', author='Unknown', total_scenes=0, characters=[character],
        locations=[Location(id='part0001_loc_001', name='Gate', visual_anchor='iron gate', mood='quiet')],
        props=[Prop(id='part0001_prop_001', name='Key', visual_anchor='iron key')],
        scenes=[], sequences=[])


@pytest.mark.parametrize('adapter', [strict_output_schema, anthropic_output_schema])
@pytest.mark.parametrize('section', [False, True])
def test_schemas_work_with_both_structured_output_adapters(adapter, section):
    schema = extraction_schema(registry=registry(), prefix='part0002_') if section else extraction_schema()
    original = json.dumps(schema, sort_keys=True)
    wire = adapter(schema)
    assert wire['additionalProperties'] is False
    assert set(wire['required']) == set(wire['properties'])
    assert 'character_participation' in wire['properties']
    assert {'total_scenes', 'revision', 'excluded_entities'}.isdisjoint(wire['properties'])
    assert {'part_id', 'source_start_offset'}.isdisjoint(wire['$defs']['Scene']['properties'])
    assert 'origin' not in wire['$defs']['Character']['properties']
    assert json.dumps(schema, sort_keys=True) == original
    if section:
        assert {'title', 'author', 'style_notes', 'sequences'}.isdisjoint(wire['properties'])
    else:
        assert {'title', 'author', 'sequences'} <= set(wire['properties'])


def test_known_id_branches_cannot_restate_physical_identity():
    schema = strict_output_schema(extraction_schema(registry=registry(), prefix='part0002_'))
    for field, kind in [('characters', 'Character'), ('locations', 'Location'), ('props', 'Prop')]:
        minimal, changes, new = schema['properties'][field]['items']['anyOf']
        assert set(minimal['properties']) == {'id'}
        assert {'name', 'visual_anchor', 'gender', 'first_appearance_scene'}.isdisjoint(changes['properties'])
        assert {'id', 'appearance_states', 'appearance_timeline'} <= set(changes['properties'])
        assert changes['properties']['id'] == {'$ref': f'#/$defs/Known{kind}Id'}
        old_id = getattr(registry(), field)[0].id
        assert old_id in schema['$defs'][f'Known{kind}Id']['enum']
        new_id = schema['$defs'][kind]['properties']['id']['pattern']
        assert re.fullmatch(new_id, old_id) is None
        assert re.fullmatch(new_id, f'part0002_{field}_new') is not None
        assert new == {'$ref': f'#/$defs/{kind}'}
        if field == 'characters':
            assert {'distinguishing_features', 'cast_required'} <= set(changes['properties'])


def test_reference_constraints_include_every_registry_identity_and_only_local_new_ids():
    schema = extraction_schema(registry=registry(), prefix='p0002s0001_')
    definitions = schema['$defs']
    for kind, field in [('Character', 'characters'), ('Location', 'locations'), ('Prop', 'props')]:
        assert definitions[f'Known{kind}Id']['enum'] == [entity.id for entity in getattr(registry(), field)]
    assert definitions['Scene']['properties']['character_ids']['items']['anyOf'][0] == {
        '$ref': '#/$defs/KnownCharacterId'}
    assert definitions['CharacterRelationship']['properties']['character_id']['anyOf'][0] == {
        '$ref': '#/$defs/KnownCharacterId'}
    for kind, field in [('CharacterParticipation', 'scene_id'), ('StoryPosition', 'scene_id'),
                        ('Character', 'first_appearance_scene')]:
        constraint = definitions[kind]['properties'][field]['pattern']
        assert re.fullmatch(constraint, 'p0002s0001_scene_001')
        assert not re.fullmatch(constraint, 'part0001_scene_001')
    state = strict_output_schema(schema)['$defs']['AppearanceState']
    assert {'changed_facets', 'replaces_identity', 'continuity_guard'} <= set(state['required'])


def test_large_series_stay_within_enum_budgets_without_losing_ids():
    bible = registry()
    bible.characters = [bible.characters[0].model_copy(update={'id': f'part0001_char_{index:04d}'})
                        for index in range(1005)]
    schema = strict_output_schema(extraction_schema(registry=bible, prefix='part0002_'))
    constraint = schema['$defs']['KnownCharacterId']['pattern']
    assert all(re.fullmatch(constraint, entity.id) for entity in bible.characters)
    assert not re.fullmatch(constraint, 'part0001_char_10050')
    assert not re.fullmatch(constraint, 'part0002_char_0001')


def test_prompts_have_one_scope_without_scene_or_description_quotas():
    common = PROMPT_PATH.read_text()
    section = common + section_instructions(registry())
    assert WHOLE_SOURCE_INSTRUCTIONS not in section
    assert 'overrides' not in section
    assert 'SCHEMA' not in common  # the request schema carries the field contract
    assert '5-15 scenes' not in common
    assert '15+ tags' not in common
    assert '40–60 words' not in common
    assert 'there is no target scene count' in common
    assert 'same exact character and scene' in common
    assert 'copy' in common.lower() and 'verbatim' in common.lower()


def test_organization_schema_has_open_ended_part_sequences_without_part_metadata():
    scenes = ['part0001_scene_001', 'part0002_scene_001']
    schema = strict_output_schema(organization_schema(scenes))
    sequence = schema['$defs']['StorySequence']
    assert 'part_id' not in sequence['properties']
    # A part is not a complete story: no fixed act count or act enum.
    assert 'act' not in sequence['properties']
    assert 'minItems' not in schema['properties']['sequences']
    assert 'maxItems' not in schema['properties']['sequences']
    assert sequence['properties']['scenes']['minItems'] == 1
    assert sequence['properties']['scenes']['items'] == {'$ref': '#/$defs/ReviewSceneId'}
    assert schema['$defs']['ReviewSceneId']['enum'] == scenes


@pytest.mark.parametrize('adapter', [strict_output_schema, anthropic_output_schema])
def test_source_review_schema_binds_existing_ids_and_new_correction_ids_once(adapter):
    known = registry()
    scenes = ['part0001_scene_001', 'part0002_scene_001']
    schema = adapter(organization_schema(scenes, bible=known, prefix='p0001audit_'))
    definitions = schema['$defs']
    assert definitions['SourceEvidence']['properties']['scene_id'] == {'$ref': '#/$defs/ReviewSceneId'}
    assert definitions['ReviewSceneId']['enum'] == scenes
    assert definitions['CharacterDetails']['properties']['id'] == {'$ref': '#/$defs/ReviewCharacterId'}
    assert definitions['ReviewCharacterId']['enum'] == [known.characters[0].id]
    assert re.fullmatch(definitions['CharacterAddition']['properties']['id']['pattern'], 'p0001audit_boss')
    assert not re.fullmatch(definitions['CharacterAddition']['properties']['id']['pattern'], known.characters[0].id)
    assert 'origin' not in definitions['CharacterAddition']['properties']
    assert 'source_review' in schema['required']
    section = adapter(extraction_schema(registry=known, prefix='part0002_'))
    assert 'source_review' not in section['properties']
    assert 'ExtractionReview' not in section['$defs']  # no unused review DTO cost per section


def test_final_source_review_does_not_duplicate_large_registry_enum_budgets():
    known = registry()
    known.characters = [known.characters[0].model_copy(update={'id': f'char_{i:04d}'}) for i in range(750)]
    scenes = [f'scene_{i:04d}' for i in range(200)]
    schema = strict_output_schema(organization_schema(scenes, bible=known))
    assert 'enum' not in schema['$defs']['ReviewCharacterId']
    constraint = schema['$defs']['ReviewCharacterId']['pattern']
    assert all(re.fullmatch(constraint, character.id) for character in known.characters)
    assert not re.fullmatch(constraint, 'char_9999')
