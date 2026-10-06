"""Provider-free long-source recovery and continuity contracts."""

import json
import asyncio
from functools import wraps

import pytest

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.clients.structured_call import StructuredCallError
from novel_to_comic import extraction_sections as sections
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.source_extraction import source_units, build_source_document, SourceSceneAnchor, align_scene_anchors
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import create_initial_state
from novel_to_comic.stages import s1_extract
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


def payload(index, text, state=None):
    prefix = sections.section_prefix(1, index)
    scene_id = prefix + "scene_001"
    character = {
        "id": "p0001s0001_char_001", "name": "Ari", "visual_anchor": "adult, black hair",
        "age_range": "adult", "gender": "female", "distinguishing_features": [],
        "default_outfit": "coat", "first_appearance_scene": scene_id,
        "appearance_states": [], "appearance_timeline": [],
    }
    if state:
        character["appearance_states"] = [state]
        character["appearance_timeline"] = [{"state_id": state["id"], "at": {"scene_id": scene_id}}]
    return {
        "title": "Crossing", "author": "Unknown", "total_scenes": 1,
        "characters": [character],
        "locations": [{"id": "p0001s0001_loc_001", "name": "Gate", "visual_anchor": "iron gate", "mood": "quiet"}],
        "scenes": [{"id": scene_id, "chapter": 1, "title": "Crossing", "location_id": "p0001s0001_loc_001",
                    "character_ids": [character["id"]], "summary": "Ari crosses the gate.", "scene_type": "action",
                    "narrative_beat": "rising_action", "source_start_quote": source_units(text)[0].text.strip()}],
        "sequences": [], "props": [],
        "character_participation": [{"character_id": character["id"], "scene_id": scene_id,
                                     "classification": "direct_action", "source_quote": "Ari"}],
    }


def appearance(id="hurt"):
    return {"id": id, "label": id, "visual_anchor": "adult, black hair, bandaged arm",
            "changed_facets": ["damage"], "replaces_identity": False,
            "visually_significant": True, "continuity_guard": "Preserve the bandaged arm."}


def test_sentence_partition_preserves_all_original_offsets_and_unicode():
    text = ('Dr. Ari said, “Go!”\n\nThe gate opened at 3.5 seconds. A final thought…\n' * 100) + 'The end.'
    parts = sections.split_source(text, 4000)
    assert len(parts) > 1
    assert ''.join(parts) == text
    assert all(len(part) <= 4000 for part in parts)
    assert [u.text for part in parts for u in source_units(part)] == [u.text for u in source_units(text)]
    anchors = [SourceSceneAnchor(id=str(i), title=str(i), opening_quote=source_units(part)[0].text.strip())
               for i, part in enumerate(parts)]
    document = build_source_document(text, anchors)
    assert document.text == text
    assert document.scenes[-1].last_unit_id == document.units[-1].id


def test_partition_balances_sections_instead_of_leaving_a_runt_tail():
    # A source just over the limit once produced a 578-character final section
    # that the model replaced with other supplied text.
    text = 'Ari walked to the old gate and waited there. ' * 368
    parts = sections.split_source(text, 16000)
    assert ''.join(parts) == text
    assert len(parts) == 2
    assert all(len(part) <= 16000 for part in parts)
    assert min(len(part) for part in parts) > 0.45 * len(text)


def _wrapped(paragraphs, width=68):
    # PDF text: hard-wrapped lines, a paragraph ends on a short last line.
    import textwrap
    return "".join(textwrap.fill(paragraph, width) + "\n" for paragraph in paragraphs)


def test_cuts_move_to_a_paragraph_end_instead_of_splitting_an_action_beat():
    # Each section opens a scene. An equal-share cut once fell mid-paragraph and
    # turned one goblin attack into a three-sentence scene plus its remainder.
    sentence = "The goblins howled on the rusting tractor and I ran for the alley. "
    text = _wrapped([sentence * (5 + index % 7) + "Then silence." for index in range(24)])
    parts = sections.split_source(text, 4000)
    assert ''.join(parts) == text
    assert len(parts) > 1 and all(len(part) <= 4000 for part in parts)
    paragraph_starts, offset = {0}, 0
    for paragraph in text.splitlines(keepends=True):
        offset += len(paragraph)
        if len(paragraph.rstrip()) < 50:
            paragraph_starts.add(offset)
    cuts = [sum(map(len, parts[:index])) for index in range(len(parts))]
    assert set(cuts) <= paragraph_starts
    assert min(len(part) for part in parts) > 0.5 * len(text) / len(parts)


def test_a_chapter_heading_near_the_share_beats_a_closer_paragraph_end():
    sentence = "Mira crossed the frozen yard and checked every lock twice. "
    chapter_one = _wrapped([sentence * 5] * 7)
    text = chapter_one + "[ 2 ]\n" + _wrapped([sentence * 5] * 6)
    parts = sections.split_source(text, len(text) // 2 + 300)
    assert ''.join(parts) == text
    assert len(parts) == 2 and parts[1].startswith("[ 2 ]\n")


def test_section_requests_carry_no_second_source_passage():
    import inspect
    assert 'source_heading' not in inspect.getsource(sections.extract_sections).split('organization_content')[0]


@pytest.mark.parametrize('placeholder_definition', [False, True])
@run_async
async def test_promotional_matter_does_not_need_a_fictional_location_or_retry(placeholder_definition):
    text = 'Join the Reading Club. Find more stories on our website.'
    raw = payload(1, text)
    raw['characters'] = []
    raw['character_participation'] = []
    raw['scenes'][0].update(character_ids=[], scene_type='promotional front matter',
                            location_id='p0001s0001_unspecified', summary='Recommendations for reading communities.')
    raw['locations'] = ([{'id': 'p0001s0001_unspecified', 'name': 'Unspecified setting',
                         'visual_anchor': '', 'mood': 'Unstated'}] if placeholder_definition else [])
    original = json.dumps(raw, sort_keys=True)
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        assert len(calls) == 1, 'Non-story source matter must not cause a paid repair'
        return ApiResult(value=raw)
    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', text, generate=generate,
        validate=lambda value: sections.merge_section(None, value, 'p0001s0001_'))
    assert result.value.scenes[0].scene_type == 'non_narrative'
    assert result.value.scenes[0].location_id is None
    assert not result.value.locations and not result.value.characters
    document = build_source_document(text, [SourceSceneAnchor(
        id=result.value.scenes[0].id, title=result.value.scenes[0].title,
        opening_quote=result.value.scenes[0].source_start_quote)])
    assert document.text == text
    assert ''.join(unit.text for unit in document.units) == text
    assert document.scenes[0].last_unit_id == document.units[-1].id
    assert json.dumps(raw, sort_keys=True) == original


def test_non_narrative_span_keeps_existing_location_authorities():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.', appearance()))
    raw = payload(2, 'Join the Reading Club.')
    raw['characters'] = []
    raw['character_participation'] = []
    raw['scenes'][0].update(character_ids=[], scene_type='back matter')
    raw['locations'] = [{'id': previous.locations[0].id}]
    parsed = s1_extract._parse_extraction(sections.hydrate_section(raw, previous), 'Join the Reading Club.')
    merged = sections.merge_section(previous, parsed, 'p0001s0002_')
    assert merged.scenes[-1].location_id is None
    assert merged.locations == previous.locations
    assert merged.characters == previous.characters


def test_late_physical_facts_and_important_cast_selection_accumulate_without_rewriting_anchors():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    previous.characters[0].distinguishing_features = ['Black hair']
    raw = payload(2, 'Ari stands six feet tall and faces the raiders.')
    raw['characters'] = [{'id': previous.characters[0].id,
                          'distinguishing_features': ['Black hair', 'Six feet tall'], 'cast_required': True}]
    hydrated = sections.hydrate_section(raw, previous)
    merged = sections.merge_section(previous, StoryBible.model_validate(hydrated), 'p0001s0002_')
    character = merged.characters[0]
    assert character.visual_anchor == previous.characters[0].visual_anchor
    assert character.distinguishing_features == ['Black hair', 'Six feet tall']
    assert character.cast_required is True
    assert not character.appearance_states and not character.appearance_timeline
    assert previous.characters[0].distinguishing_features == ['Black hair']
    assert previous.characters[0].cast_required is False

    # A later default/empty delta cannot discard facts or demote an authority.
    raw = payload(3, 'Ari walks through the courtyard.')
    raw['characters'] = [{'id': character.id, 'distinguishing_features': [], 'cast_required': False}]
    next_bible = sections.merge_section(merged, StoryBible.model_validate(sections.hydrate_section(raw, merged)), 'p0001s0003_')
    assert next_bible.characters[0].distinguishing_features == character.distinguishing_features
    assert next_bible.characters[0].cast_required is True


@pytest.mark.parametrize('classification', [None, 'background_only'])
@run_async
async def test_known_identity_facts_do_not_require_invented_local_participation_or_a_retry(classification):
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    # Keep even a retained, imperfect anchor verbatim; normalization applies
    # only to provisional new identities, never established authorities.
    previous.characters[0].visual_anchor = '1woman, black hair'
    previous.characters[0].age_range = '13'
    text = 'A letter identifies Ari as Qwist and describes her black hair and six-foot height.'
    raw = payload(2, text)
    raw['scenes'][0]['character_ids'] = []
    raw['characters'] = [{'id': previous.characters[0].id, 'aliases': ['Qwist'],
                          'distinguishing_features': ['Six feet tall']}]
    raw['character_participation'] = [] if classification is None else [{
        'character_id': previous.characters[0].id, 'scene_id': raw['scenes'][0]['id'],
        'classification': classification, 'source_quote': text}]
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        assert len(calls) == 1
        return ApiResult(value=raw)

    result = await s1_extract._extract_with_retry(Config(), 'source reader', text, generate=generate,
        prepare=lambda value: sections.hydrate_section(value, previous), registry=previous,
        validate=lambda value: sections.merge_section(previous, value, 'p0001s0002_'))
    merged = sections.merge_section(previous, result.value, 'p0001s0002_')
    assert len(calls) == 1
    assert merged.characters[0].aliases == ['Qwist']
    assert merged.characters[0].distinguishing_features == ['Six feet tall']
    assert merged.characters[0].visual_anchor == previous.characters[0].visual_anchor
    assert merged.characters[0].first_appearance_scene == previous.characters[0].first_appearance_scene
    assert not merged.scenes[-1].character_ids


def test_a_real_unknown_setting_still_fails_with_its_id():
    raw = payload(1, 'Ari opened the gate.')
    raw['locations'] = []
    raw['scenes'][0]['location_id'] = 'p0001s0001_missing_gate'
    parsed = s1_extract._parse_extraction(raw, 'Ari opened the gate.')
    with pytest.raises(ValueError, match="Undefined location ID: 'p0001s0001_missing_gate'"):
        sections.merge_section(None, parsed, 'p0001s0001_')


@pytest.mark.parametrize('staged', ['characters', 'objects'])
def test_nonnarrative_classification_does_not_discard_staged_entities(staged):
    raw = payload(1, 'Ari opened the gate.')
    raw['scenes'][0]['scene_type'] = 'non_narrative'
    if staged == 'objects':
        raw['characters'] = []
        raw['character_participation'] = []
        raw['scenes'][0]['character_ids'] = []
        raw['scenes'][0]['transient_objects'] = [{
            'id': 'p0001s0001_trans_001', 'name': 'Gate', 'visual_anchor': 'iron gate',
        }]
    with pytest.raises(ValueError, match='physically staged character participation'):
        s1_extract._parse_extraction(raw, 'Ari opened the gate.')


def test_an_empty_setting_used_by_a_narrative_scene_still_fails():
    text = 'Ari opened the gate. Join the Reading Club.'
    raw = payload(1, text)
    raw['locations'][0]['visual_anchor'] = ''
    raw['scenes'].append({**raw['scenes'][0], 'id': 'p0001s0001_scene_002',
                          'character_ids': [], 'scene_type': 'back matter',
                          'source_start_quote': 'Join the Reading Club.'})
    with pytest.raises(ValueError, match='nonempty visual_anchor'):
        s1_extract._parse_extraction(raw, text)


def test_oversized_sentence_fails_before_any_call():
    with pytest.raises(ValueError, match="sentence formatting"):
        sections.split_source("Ari " + "x" * 5000 + ".", 4000)


def test_merge_keeps_entity_scoped_states_and_cross_section_recovery():
    first = StoryBible.model_validate(payload(1, "Ari fell.", appearance()))
    second = StoryBible.model_validate(payload(2, "Ari recovered.", appearance("restored")))
    merged = sections.merge_section(first, second, "p0001s0002_")
    assert len(merged.characters) == 1
    assert merged.characters[0].first_appearance_scene == "p0001s0001_scene_001"
    assert [a.state_id for a in merged.characters[0].appearance_timeline] == ["hurt", "restored"]
    assert sections.registry_context(merged)["characters"][0]["carried_state_id"] == "restored"
    assert len(first.scenes) == 1  # failed/preview merges cannot mutate prior work


@pytest.mark.parametrize("change,match", [
    ("base", "base visual_anchor"), ("state", "state definition"),
    ("alias", "Reuse the registry ID"), ("location", "Unknown entity"),
    ("timeline", "only local timeline"), ("state_reference", "Unknown appearance"),
])
def test_merge_rejects_identity_drift_and_bad_references(change, match):
    first = StoryBible.model_validate(payload(1, "Ari fell.", appearance()))
    raw = payload(2, "Ari walked.", appearance())
    if change == "base":
        raw["characters"][0]["visual_anchor"] = "blonde"
    elif change == "state":
        raw["characters"][0]["appearance_states"][0]["continuity_guard"] = "Discard bandages."
    elif change == "alias":
        raw["characters"][0]["id"] = "p0001s0002_char_001"
    elif change == "location":
        raw["scenes"][0]["location_id"] = "missing"
    elif change == "timeline":
        raw["characters"][0]["appearance_timeline"][0]["at"]["scene_id"] = "p0001s0001_scene_001"
    elif change == "state_reference":
        raw["characters"][0]["appearance_timeline"][0]["state_id"] = "missing"
    with pytest.raises(ValueError, match=match):
        sections.merge_section(first, StoryBible.model_validate(raw), "p0001s0002_")


@run_async
async def test_section_removes_links_to_undefined_background_mentions_without_a_retry():
    text = 'Ari opened the gate. A photograph of Jo stood on the shelf.'
    raw = payload(1, text)
    raw['characters'][0]['relationships'] = [{'character_id': 'p0001s0001_char_002', 'relationship': 'friend'}]
    raw['character_participation'].append({
        'character_id': 'p0001s0001_char_002', 'scene_id': 'p0001s0001_scene_001',
        'classification': 'background_only', 'source_quote': 'A photograph of Jo',
    })
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=raw)

    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', text, generate=generate,
        validate=lambda value: sections.merge_section(None, value, 'p0001s0001_'))

    assert len(calls) == 1
    assert [character.id for character in result.value.characters] == ['p0001s0001_char_001']
    assert not result.value.characters[0].relationships


def correction_payloads():
    text = 'Ari opened the gate. Jo waited.'
    initial = payload(1, text)
    jo = {**initial['characters'][0], 'id': 'p0001s0001_char_002', 'name': 'Jo',
          'visual_anchor': 'adult, red hair', 'relationships': []}
    initial['characters'].extend([jo, {**initial['characters'][0], 'id': 'p0001s0001_char_003',
                                     'name': 'Unstaged residents'}])
    initial['scenes'][0]['character_ids'].append(jo['id'])
    initial['character_participation'].append({
        'character_id': jo['id'], 'scene_id': 'p0001s0001_scene_001',
        'classification': 'direct_action', 'source_quote': 'Jo waited.',
    })
    corrected = json.loads(json.dumps(initial))
    corrected['characters'].pop()
    # Removing the residents made the model renumber Ari's definition, while
    # leaving all the redundant references on Ari's previous ID.
    corrected['characters'][0]['id'] = 'p0001s0001_char_003'
    corrected['characters'][1]['relationships'] = [
        {'character_id': 'p0001s0001_char_001', 'relationship': 'friend'}]
    return text, initial, corrected


@run_async
async def test_schema_correction_reconciles_renumbered_characters_without_an_extra_retry():
    text, initial, corrected = correction_payloads()
    originals = json.dumps([initial, corrected], sort_keys=True)
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        assert len(calls) <= 2, 'An unchanged identity must not need another model correction'
        return ApiResult(value=[initial, corrected][len(calls) - 1])

    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', text, max_retries=1, generate=generate,
        validate=lambda value: sections.merge_section(None, value, 'p0001s0001_'))

    assert len(calls) == 2
    assert [c.id for c in result.value.characters] == ['p0001s0001_char_003', 'p0001s0001_char_002']
    assert result.value.scenes[0].character_ids == ['p0001s0001_char_003', 'p0001s0001_char_002']
    assert result.value.characters[0].name == 'Ari'
    assert result.value.characters[0].visual_anchor == initial['characters'][0]['visual_anchor']
    assert result.value.characters[1].relationships[0].character_id == 'p0001s0001_char_003'
    assert json.dumps([initial, corrected], sort_keys=True) == originals


@pytest.mark.parametrize('change', ['anchor', 'name', 'missing_definition', 'ambiguous_current', 'ambiguous_previous'])
@run_async
async def test_correction_reference_recovery_requires_one_unchanged_defined_identity(change):
    text, initial, corrected = correction_payloads()
    if change == 'anchor':
        corrected['characters'][0]['visual_anchor'] = 'adult, blonde hair'
    elif change == 'name':
        corrected['characters'][0]['name'] = 'Ren'
    elif change == 'missing_definition':
        corrected['characters'].pop(0)
    elif change == 'ambiguous_current':
        corrected['characters'].append({**corrected['characters'][0], 'id': 'p0001s0001_char_004'})
    elif change == 'ambiguous_previous':
        initial['characters'].append({**initial['characters'][0], 'id': 'p0001s0001_char_004'})
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=[initial, corrected][len(calls) - 1])

    with pytest.raises(ValueError, match="Undefined character IDs: \\['p0001s0001_char_001'\\]"):
        await s1_extract._extract_with_retry(
            Config(), 'instructions', text, max_retries=1, generate=generate,
            validate=lambda value: sections.merge_section(None, value, 'p0001s0001_'))
    assert len(calls) == 2


@run_async
async def test_correction_recovery_does_not_guess_an_identity_without_previous_response_evidence():
    text, _, corrected = correction_payloads()
    async def generate(**kwargs):
        return ApiResult(value=corrected)

    with pytest.raises(ValueError, match="Undefined character IDs: \\['p0001s0001_char_001'\\]"):
        await s1_extract._extract_with_retry(Config(), 'instructions', text, max_retries=0, generate=generate)


@run_async
async def test_correction_reference_recovery_never_rewrites_scene_ids():
    text, initial, corrected = correction_payloads()
    corrected['scenes'][0]['id'] = 'p0001s0001_scene_002'
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=[initial, corrected][len(calls) - 1])

    with pytest.raises(ValueError, match="scene IDs outside this section: \\['p0001s0001_scene_001'\\]"):
        await s1_extract._extract_with_retry(Config(), 'instructions', text, max_retries=1, generate=generate)
    assert len(calls) == 2


@run_async
async def test_correction_recovery_preserves_existing_intermediate_feedback_and_accepted_chain():
    text, initial, intermediate = correction_payloads()
    intermediate['scenes'][0]['source_start_quote'] = 'Not a source sentence.'
    final = json.loads(json.dumps(intermediate))
    final['scenes'][0]['source_start_quote'] = 'Ari opened the gate.'
    final['scenes'][0]['character_ids'][0] = 'p0001s0001_char_003'
    final['character_participation'][0]['character_id'] = 'p0001s0001_char_003'
    final['characters'][1]['relationships'][0]['character_id'] = 'p0001s0001_char_003'
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 3:
            assert "Undefined character IDs: ['p0001s0001_char_001']" in kwargs['user_content']
            assert 'Unresolved scene IDs' not in kwargs['user_content']
        return ApiResult(value=[initial, intermediate, final][len(calls) - 1])

    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', text, generate=generate,
        validate=lambda value: sections.merge_section(None, value, 'p0001s0001_'))

    assert len(calls) == 3
    assert len(result.value.characters) == 2


@run_async
async def test_correction_recovery_leaves_normally_valid_final_response_membership_unchanged():
    text, initial, final = correction_payloads()
    final['scenes'][0]['character_ids'][0] = 'p0001s0001_char_003'
    final['character_participation'][0]['classification'] = 'background_only'
    final['characters'][1]['relationships'] = []
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=[initial, final][len(calls) - 1])

    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', text, max_retries=1, generate=generate,
        validate=lambda value: sections.merge_section(None, value, 'p0001s0001_'))

    assert len(calls) == 2
    assert result.value.scenes[0].character_ids == ['p0001s0001_char_003', 'p0001s0001_char_002']
    assert [c.name for c in result.value.characters] == ['Ari', 'Jo']


@run_async
async def test_terminal_identity_conflict_names_both_declarations_without_changing_cached_feedback():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['characters'][0].update(name='Jo', visual_anchor='adult, red hair')
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            assert 'Preserve base visual_anchor verbatim for p0001s0001_char_001' in kwargs['user_content']
            assert 'Registry ID' not in kwargs['user_content']
        return ApiResult(value=raw)

    with pytest.raises(ValueError, match='Preserve base visual_anchor') as error:
        await s1_extract._extract_with_retry(
            Config(), 'instructions', 'Ari closed the gate.', generate=generate,
            prepare=lambda value: sections.hydrate_section(value, previous),
            validate=lambda value: sections.merge_section(previous, value, 'p0001s0002_'))

    assert len(calls) == 3
    assert "belongs to 'Ari'" in str(error.value)
    assert "declares 'Jo'" in str(error.value)
    assert 'adult, black hair' in str(error.value)
    assert 'adult, red hair' in str(error.value)
    assert previous.characters[0].name == 'Ari'
    assert previous.characters[0].visual_anchor == 'adult, black hair'


def test_unknown_relationship_feedback_identifies_the_missing_target_without_inventing_it():
    raw = payload(1, 'Ari opened the gate.')
    raw['characters'][0]['relationships'] = [{'character_id': 'missing_character', 'relationship': 'friend'}]
    parsed = s1_extract._parse_extraction(raw, 'Ari opened the gate.')

    with pytest.raises(ValueError, match='Unknown relationship target for p0001s0001_char_001') as error:
        sections.merge_section(None, parsed, 'p0001s0001_')

    assert 'missing_character' in str(error.value)
    assert 'registry IDs' in str(error.value)
    assert 'never invent visual participation' in str(error.value)
    assert parsed.characters[0].relationships[0].character_id == 'missing_character'


def test_section_relationships_keep_known_registry_targets_absent_from_local_rosters():
    first = payload(1, 'Ari opened the gate.')
    first['characters'].append({**first['characters'][0], 'id': 'p0001s0001_char_002', 'name': 'Jo'})
    previous = StoryBible.model_validate(first)
    raw = payload(2, 'Ari closed the gate.')
    raw['characters'][0]['relationships'] = [{'character_id': 'p0001s0001_char_002', 'relationship': 'friend'}]

    parsed = s1_extract._parse_extraction(sections.hydrate_section(raw, previous), 'Ari closed the gate.')
    merged = sections.merge_section(previous, parsed, 'p0001s0002_')

    assert [character.id for character in parsed.characters] == ['p0001s0001_char_001']
    assert parsed.scenes[0].character_ids == ['p0001s0001_char_001']
    assert merged.characters[0].relationships[0].character_id == 'p0001s0001_char_002'
    assert not previous.characters[0].relationships


@run_async
async def test_stage_timeout_resume_reuses_sections_and_publishes_complete_source(tmp_path, monkeypatch):
    text = "".join(f"Ari crossed gate number {i}. " for i in range(400))
    (tmp_path / "novel.txt").write_text(text)
    config = Config(extraction_chunk_chars=4000)
    calls = []
    should_fail = True

    async def generate(**kwargs):
        nonlocal should_fail
        content = json.loads(kwargs["user_content"])
        if kwargs["feature"] == "extract.sequences":
            ids = [s["id"] for s in content["scenes"]]
            value = {"title": "Crossing", "author": "Unknown", "sequences": [
                {"number": i, "title": f"Act {i}", "scenes": ids if i == 1 else []} for i in (1, 2, 3)]}
            calls.append("arcs")
        else:
            index = content["section"]
            calls.append(index)
            if index == 2 and should_fail:
                should_fail = False
                raise TimeoutError("runtime_timeout")
            value = payload(index, content["source_section"])
        return ApiResult(value=value, usage=UsageRecord(provider="test", model="test", operation="text", cost_usd=0))

    monkeypatch.setattr(sections, "generate_json", generate)
    state = create_initial_state("test", "novel.txt")
    ctx = StageRuntime("extract", state, tmp_path)
    logs = []
    log = ctx.log
    ctx.log = lambda message, level="info": (logs.append(message), log(message, level))[1]
    with pytest.raises(TimeoutError):
        await s1_extract.run(config, tmp_path, ctx)
    assert calls == [1, 2]  # no automatic timeout resubmission
    sections_total = len(sections.split_source(text, 4000))
    assert f"Sections 1–1 are saved. Running Extract again resumes at section 2 of {sections_total}." in logs
    assert not artifacts.story_bible_path(tmp_path).exists()
    assert len(list((tmp_path / ".checkpoints/extract/responses").glob("*.json"))) == 1
    result = await s1_extract.run(config, tmp_path, ctx)
    assert calls.count(1) == 1
    assert calls.count(2) == 2
    assert result.total_scenes == len(sections.split_source(text, 4000))
    assert state.stages["extract"].items_done == state.stages["extract"].items_total
    assert json.loads((tmp_path / "source/source.json").read_text())["text"] == text
    before = list(calls)
    await s1_extract.run(config, tmp_path, ctx)
    assert calls == before  # including final organization


@run_async
async def test_section_validation_repair_is_scoped_and_cached(tmp_path, monkeypatch):
    text = "Ari crossed the gate. " * 400
    count = 0
    async def generate(**kwargs):
        nonlocal count
        count += 1
        content = kwargs["user_content"]
        if kwargs["feature"] == "extract.sequences":
            ids = [s["id"] for s in json.loads(content)["scenes"]]
            return ApiResult(value={"title": "Crossing", "author": "Unknown", "sequences": [
                {"number": i, "title": str(i), "scenes": ids if i == 1 else []} for i in (1, 2, 3)]})
        if content.startswith("Your previous"):
            # The repair contains only this section and its established registry.
            assert len(content) < len(text) + len(json.dumps(payload(2, text))) + 5000
            return ApiResult(value=payload(2, text))
        data = json.loads(content)
        value = payload(data["section"], data["source_section"])
        if data["section"] == 2:
            value["characters"][0]["visual_anchor"] = "incorrect new identity"
        return ApiResult(value=value)
    monkeypatch.setattr(sections, "generate_json", generate)
    config = Config(extraction_chunk_chars=4000)
    ctx = StageRuntime("extract", create_initial_state("test", "novel.txt"), tmp_path)
    ctx.begin()
    bible = await sections.extract_sections(config, tmp_path, ctx, text, s1_extract.PROMPT_PATH.read_text())
    assert bible.characters[0].visual_anchor == "adult, black hair"
    # Identical sentences in earlier sections must not steal later boundaries.
    offsets = [0]
    for part in sections.split_source(text, 4000)[:-1]:
        offsets.append(offsets[-1] + len(part))
    assert [scene.source_start_offset for scene in bible.scenes] == offsets
    assert align_scene_anchors(bible, text) == ()
    document = build_source_document(text, [
        SourceSceneAnchor(id=s.id, title=s.title, opening_quote=s.source_start_quote,
                          start_offset=s.source_start_offset) for s in bible.scenes
    ])
    unit_starts = {u.id: u.start_offset for u in document.units}
    assert [unit_starts[s.first_unit_id] for s in document.scenes] == offsets
    assert count == len(sections.split_source(text, 4000)) + 2
    before = count
    await sections.extract_sections(config, tmp_path, ctx, text, s1_extract.PROMPT_PATH.read_text())
    assert count == before


@pytest.mark.parametrize("skip_opening", [False, True])
@run_async
async def test_section_opening_with_front_matter_is_explicit_and_repairable(tmp_path, monkeypatch, skip_opening):
    text = ('\n  CROSSING — “BOOK ONE”\nBy A. Writer\nAll rights reserved.\n\nCHAPTER 1\n'
            + "".join(f"Ari crossed gate number {i}. " for i in range(220)))
    (tmp_path / "novel.txt").write_text(text)
    first_quote = source_units(text)[0].text.strip()
    calls = []
    rejected = None

    async def generate(**kwargs):
        nonlocal rejected
        content = kwargs["user_content"]
        if kwargs["feature"] == "extract.sequences":
            calls.append("arcs")
            ids = [scene["id"] for scene in json.loads(content)["scenes"]]
            return ApiResult(value={"title": "Crossing", "author": "A. Writer", "sequences": [
                {"number": act, "title": str(act), "scenes": ids if act == 1 else []} for act in (1, 2, 3)]})
        if content.startswith("Your previous"):
            calls.append("repair")
            error = content.split("VALIDATION ERRORS:\n", 1)[1]
            assert "(source_000001)" in error
            assert json.dumps(first_quote, ensure_ascii=False) in error
            assert "Received:" in error
            value = json.loads(json.dumps(rejected))
            value["scenes"][0]["source_start_quote"] = first_quote
            return ApiResult(value=value)

        data = json.loads(content)
        calls.append(data["section"])
        opening = data["required_first_scene_source_start_quote"]
        assert opening == source_units(data["source_section"])[0].text.strip()
        assert "do not invent a separate comic scene" in kwargs["system_prompt"]
        schema = kwargs['json_schema']
        assert 'sequences' not in schema['properties']
        assert schema['$defs']['Scene']['properties']['id']['pattern'].startswith('^' + data['id_prefix'])
        if data['registry']:
            assert 'title' not in schema['properties']
            assert 'KnownCharacterId' in schema['$defs']
        value = payload(data["section"], data["source_section"])
        value["scenes"][0]["source_start_quote"] = opening
        if skip_opening and data["section"] == 1:
            value["scenes"][0]["source_start_quote"] = "Ari crossed gate number 0."
            rejected = value
        return ApiResult(value=value)

    monkeypatch.setattr(sections, "generate_json", generate)
    config = Config(extraction_chunk_chars=4000)
    ctx = StageRuntime("extract", create_initial_state("test", "novel.txt"), tmp_path)
    bible = await s1_extract.run(config, tmp_path, ctx)
    parts = sections.split_source(text, config.extraction_chunk_chars)
    assert len(parts) > 1
    assert calls == [1, *(["repair"] if skip_opening else []), *range(2, len(parts) + 1), "arcs"]
    assert bible.scenes[0].source_start_quote == first_quote
    assert bible.scenes[0].source_start_offset == len(text) - len(text.lstrip())
    assert len(bible.scenes) == len(parts)  # front matter needs no invented scene
    document = TargetArtifacts(tmp_path).read_source()
    assert document.text == text
    assert document.scenes[0].first_unit_id == document.units[0].id
    assert document.scenes[-1].last_unit_id == document.units[-1].id
    assert "".join(unit.text for unit in document.units) == text
    before = list(calls)
    await s1_extract.run(config, tmp_path, ctx)
    assert calls == before  # both the sections and their repair remain resumable


@run_async
async def test_section_still_rejects_a_response_that_keeps_skipping_the_opening(tmp_path, monkeypatch):
    text = "Copyright notice. Ari crossed the gate."
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        value = payload(1, text)
        value["scenes"][0]["source_start_quote"] = "Ari crossed the gate."
        return ApiResult(value=value)

    monkeypatch.setattr(sections, "generate_json", generate)
    ctx = StageRuntime("extract", create_initial_state("test", "novel.txt"), tmp_path)
    ctx.begin()
    with pytest.raises(ValueError, match="first source unit") as error:
        await sections.extract_sections(Config(), tmp_path, ctx, text, s1_extract.PROMPT_PATH.read_text())
    assert '"Copyright notice."' in str(error.value)
    assert 'Received: "Ari crossed the gate."' in str(error.value)
    assert calls == 2  # the unchanged repair response is replayed on the final attempt
    assert not artifacts.story_bible_path(tmp_path).exists()


@pytest.mark.parametrize("failed_call", ["section", "arcs"])
@run_async
async def test_validation_failure_archives_only_failed_responses_and_retry_resumes(tmp_path, monkeypatch, failed_call):
    text = "Ari crossed the gate. " * 300
    (tmp_path / "novel.txt").write_text(text)
    config = Config(extraction_chunk_chars=4000)
    assert len(sections.split_source(text, config.extraction_chunk_chars)) == 2
    reject = True
    calls = []
    second_payload = None
    arc_ids = None

    async def generate(**kwargs):
        nonlocal second_payload, arc_ids
        content = kwargs["user_content"]
        if kwargs["feature"] == "extract.sequences":
            calls.append("arcs")
            if content.startswith("{"):
                # A correction starts with the original JSON, followed by
                # feedback, so decode that prefix independently of feedback.
                data, _ = json.JSONDecoder().raw_decode(content)
                arc_ids = [scene["id"] for scene in data["scenes"]]
            ids = [] if reject and failed_call == "arcs" else arc_ids
            return ApiResult(value={"title": "Crossing", "author": "Unknown", "sequences": [
                {"number": act, "title": str(act), "scenes": ids if act == 1 else []} for act in (1, 2, 3)]})
        if content.startswith("Your previous"):
            calls.append(2)
            assert "UNCLASSIFIED CHARACTERS:" in content
            assert "character_id='p0001s0002_char_002', name='Elderly residents'" in content
            value = json.loads(json.dumps(second_payload))
        else:
            data = json.loads(content)
            calls.append(data["section"])
            value = payload(data["section"], data["source_section"])
            if data["section"] == 2:
                second_payload = json.loads(json.dumps(value))
        if reject and failed_call == "section" and calls[-1] == 2:
            value["characters"].append({
                **value["characters"][0], "id": "p0001s0002_char_002", "name": "Elderly residents",
            })
        return ApiResult(value=value)

    monkeypatch.setattr(sections, "generate_json", generate)
    ctx = StageRuntime("extract", create_initial_state("test", "novel.txt"), tmp_path)
    with pytest.raises(ValueError if failed_call == "section" else StructuredCallError):
        await s1_extract.run(config, tmp_path, ctx)

    checkpoints = tmp_path / ".checkpoints/extract"
    completed = {path.name: path.read_text() for path in (checkpoints / "responses").glob("*.json")}
    assert len(completed) == (1 if failed_call == "section" else 2)
    assert list((checkpoints / "rejected").glob("*.json"))
    assert calls.count(1) == 1
    # A fresh explicit retry can generate the failed section/organization,
    # while each completed section comes from its exact existing checkpoint.
    reject = False
    result = await s1_extract.run(config, tmp_path, ctx)
    assert result.total_scenes == 2
    assert calls.count(1) == 1
    assert calls.count(2) == (3 if failed_call == "section" else 1)
    assert calls.count("arcs") == (1 if failed_call == "section" else 3)
    assert all((checkpoints / "responses" / name).read_text() == content for name, content in completed.items())
    assert TargetArtifacts(tmp_path).read_source().text == text
    before = list(calls)
    await s1_extract.run(config, tmp_path, ctx)
    assert calls == before


@run_async
async def test_interrupted_correction_does_not_discard_checkpoints_or_retry_transport():
    requests = []
    archived = []

    async def generate(**kwargs):
        requests.append(kwargs)
        if len(requests) == 2:
            raise TimeoutError("provider interrupted")
        value = payload(1, "Ari crossed the gate.")
        value["characters"].append({**value["characters"][0], "id": "unused", "name": "Unused"})
        return ApiResult(value=value)

    with pytest.raises(TimeoutError, match="provider interrupted"):
        await s1_extract._extract_with_retry(
            Config(), "instructions", "Ari crossed the gate.", generate=generate,
            on_validation_failure=lambda: archived.append(True),
        )
    assert len(requests) == 2
    assert archived == []


def test_explicit_invalid_offset_never_falls_back_to_a_different_occurrence():
    text = "Ari left. Ari left."
    bible = StoryBible.model_validate(payload(1, text))
    bible.scenes[0].source_start_offset = 1
    assert align_scene_anchors(bible, text) == (bible.scenes[0].id,)
    with pytest.raises(ValueError):
        build_source_document(text, [SourceSceneAnchor(
            id="bad", title="bad", opening_quote="Ari left.", start_offset=1)])


def test_existing_entity_delta_inherits_authorities_without_repeating_old_transitions():
    previous = StoryBible.model_validate(payload(1, 'Ari fell.', appearance()))
    raw = payload(2, 'Ari recovered.')
    raw['characters'] = [{'id': 'p0001s0001_char_001', 'appearance_timeline': [
        {'state_id': 'hurt', 'at': {'scene_id': 'p0001s0002_scene_001'}}]}]
    raw['locations'] = [{'id': 'p0001s0001_loc_001'}]
    hydrated = sections.hydrate_section(raw, previous)
    parsed = s1_extract._parse_extraction(hydrated, 'Ari recovered.')
    merged = sections.merge_section(previous, parsed, 'p0001s0002_')
    character = merged.characters[0]
    assert character.visual_anchor == previous.characters[0].visual_anchor
    assert character.appearance_states == previous.characters[0].appearance_states
    assert [item.at.scene_id for item in character.appearance_timeline] == [
        'p0001s0001_scene_001', 'p0001s0002_scene_001']
    assert 'visual_anchor' not in raw['characters'][0]
    assert len(json.dumps(raw)) < len(json.dumps(hydrated))


@pytest.mark.parametrize('name,anchor', [
    ('Gate', 'iron gate'),
    (' NORTH GATE ', 'iron gate, stone wall'),
    ('Gate', None),
])
def test_recurring_location_reuses_unique_registry_identity_and_preserves_state_authorities(name, anchor):
    first = payload(1, 'Ari opened the gate.')
    first['locations'][0].update(visual_anchor='iron gate, stone wall', aliases=['North Gate'])
    first['locations'][0]['appearance_states'] = [{
        'id': 'closed', 'label': 'Closed gate', 'visual_anchor': 'closed iron gate, stone wall',
        'changed_facets': ['architecture'], 'replaces_identity': False,
        'continuity_guard': 'Keep the gate  closed.',
    }]
    previous = StoryBible.model_validate(first)
    raw = payload(2, 'Ari closed the gate.')
    raw['locations'] = [{
        'id': 'p0001s0002_loc_001', 'name': name,
        'appearance_timeline': [{'state_id': 'closed', 'at': {'scene_id': 'p0001s0002_scene_001'}}],
    }]
    if anchor is not None:
        raw['locations'][0]['visual_anchor'] = anchor
    raw['scenes'][0]['location_id'] = 'p0001s0002_loc_001'

    parsed = s1_extract._parse_extraction(sections.hydrate_section(raw, previous), 'Ari closed the gate.')
    merged = sections.merge_section(previous, parsed, 'p0001s0002_')

    assert parsed.scenes[0].location_id == 'p0001s0001_loc_001'
    assert len(merged.locations) == 1
    assert merged.locations[0].name == 'Gate'
    assert merged.locations[0].aliases == ['North Gate']
    assert merged.locations[0].visual_anchor == 'iron gate, stone wall'
    assert merged.locations[0].appearance_states == previous.locations[0].appearance_states
    assert merged.locations[0].appearance_states[0].continuity_guard == 'Keep the gate  closed.'
    assert merged.locations[0].appearance_timeline[0].state_id == 'closed'
    assert not previous.locations[0].appearance_timeline
    assert raw['locations'][0]['id'] == raw['scenes'][0]['location_id'] == 'p0001s0002_loc_001'


def test_recurring_character_and_prop_ids_are_resolved_in_all_typed_references():
    first = payload(1, 'Ari opened the gate.')
    first['characters'].append({
        **first['characters'][0], 'id': 'p0001s0001_char_002', 'name': 'Jo', 'visual_anchor': 'adult, red hair',
    })
    first['props'] = [{'id': 'p0001s0001_prop_001', 'name': 'Key', 'aliases': ['Latch key'],
                       'visual_anchor': 'iron key, round bow', 'first_appearance_scene': 'p0001s0001_scene_001'}]
    previous = StoryBible.model_validate(first)
    text = 'Ari closed the gate. Jo waited.'
    raw = payload(2, text)
    raw['characters'][0].update(
        id='p0001s0002_char_001', name='ARI', visual_anchor='black hair',
        relationships=[{'character_id': 'p0001s0002_char_002', 'relationship': 'friend'}])
    raw['characters'].append({
        **raw['characters'][0], 'id': 'p0001s0002_char_002', 'name': 'Jo', 'visual_anchor': 'red hair',
        'relationships': [{'character_id': 'p0001s0002_char_001', 'relationship': 'friend'}],
    })
    raw['scenes'][0]['character_ids'] = ['p0001s0002_char_001', 'p0001s0002_char_002']
    raw['character_participation'][0]['character_id'] = 'p0001s0002_char_001'
    raw['character_participation'].append({
        'character_id': 'p0001s0002_char_002', 'scene_id': 'p0001s0002_scene_001',
        'classification': 'direct_action', 'source_quote': 'Jo waited.',
    })
    raw['props'] = [{'id': 'p0001s0002_prop_001', 'name': 'Latch key', 'visual_anchor': 'iron key'}]

    parsed = s1_extract._parse_extraction(sections.hydrate_section(raw, previous), text)
    merged = sections.merge_section(previous, parsed, 'p0001s0002_')

    assert parsed.scenes[0].character_ids == ['p0001s0001_char_001', 'p0001s0001_char_002']
    assert len(merged.characters) == 2
    assert [c.visual_anchor for c in merged.characters] == ['adult, black hair', 'adult, red hair']
    assert merged.characters[0].relationships[0].character_id == 'p0001s0001_char_002'
    assert merged.characters[1].relationships[0].character_id == 'p0001s0001_char_001'
    assert len(merged.props) == 1
    assert merged.props[0].id == 'p0001s0001_prop_001'
    assert merged.props[0].visual_anchor == 'iron key, round bow'
    assert merged.props[0].first_appearance_scene == 'p0001s0001_scene_001'
    assert raw['characters'][0]['relationships'][0]['character_id'] == 'p0001s0002_char_002'


@pytest.mark.parametrize('anchor', ['wooden gate', 'iron gate, broken hinge', '', None])
def test_registry_name_matching_does_not_hide_conflicting_or_blank_anchors(anchor):
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['locations'][0].update(id='p0001s0002_loc_001', visual_anchor=anchor)
    raw['scenes'][0]['location_id'] = 'p0001s0002_loc_001'

    hydrated = sections.hydrate_section(raw, previous)

    assert hydrated['locations'][0]['id'] == 'p0001s0002_loc_001'
    assert hydrated['locations'][0]['visual_anchor'] == anchor
    assert hydrated['scenes'][0]['location_id'] == 'p0001s0002_loc_001'
    if anchor:
        parsed = s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
        with pytest.raises(ValueError, match='Reuse the registry ID for Gate') as error:
            sections.merge_section(previous, parsed, 'p0001s0002_')
        assert 'p0001s0001_loc_001' in str(error.value)
        assert 'p0001s0002_loc_001' in str(error.value)
        assert 'visual_anchor' in str(error.value)
    else:
        with pytest.raises(ValueError):
            s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')


def test_ambiguous_registry_aliases_are_never_resolved_by_picking_one_entity():
    first = payload(1, 'Ari opened the gate.')
    first['locations'].append({**first['locations'][0], 'id': 'p0001s0001_loc_002',
                               'name': 'Second gate', 'aliases': ['Gate']})
    previous = StoryBible.model_validate(first)
    raw = payload(2, 'Ari closed the gate.')
    raw['locations'][0]['id'] = raw['scenes'][0]['location_id'] = 'p0001s0002_loc_001'

    hydrated = sections.hydrate_section(raw, previous)
    parsed = s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')

    assert parsed.scenes[0].location_id == 'p0001s0002_loc_001'
    with pytest.raises(ValueError, match='Reuse the registry ID for Gate') as error:
        sections.merge_section(previous, parsed, 'p0001s0002_')
    assert 'p0001s0001_loc_001' in str(error.value)
    assert 'p0001s0001_loc_002' in str(error.value)


def test_resolving_registry_identity_still_rejects_conflicting_state_definitions():
    previous = StoryBible.model_validate(payload(1, 'Ari fell.', appearance()))
    raw = payload(2, 'Ari walked.', appearance())
    raw['characters'][0]['id'] = 'p0001s0002_char_001'
    raw['characters'][0]['appearance_states'][0]['continuity_guard'] = 'Discard bandages.'
    raw['scenes'][0]['character_ids'] = ['p0001s0002_char_001']
    raw['character_participation'][0]['character_id'] = 'p0001s0002_char_001'

    parsed = s1_extract._parse_extraction(sections.hydrate_section(raw, previous), 'Ari walked.')

    with pytest.raises(ValueError, match='Preserve state definition verbatim'):
        sections.merge_section(previous, parsed, 'p0001s0002_')


def test_registry_resolution_keeps_duplicate_deltas_visible_to_validation():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['locations'].append({**raw['locations'][0], 'id': 'p0001s0002_loc_001'})

    parsed = s1_extract._parse_extraction(sections.hydrate_section(raw, previous), 'Ari closed the gate.')

    with pytest.raises(ValueError, match='Duplicate locations IDs in section'):
        sections.merge_section(previous, parsed, 'p0001s0002_')


def test_entity_delta_does_not_hide_explicit_identity_or_state_conflicts():
    previous = StoryBible.model_validate(payload(1, 'Ari fell.', appearance()))
    raw = payload(2, 'Ari walked.')
    raw['characters'] = [{'id': 'p0001s0001_char_001', 'visual_anchor': 'different identity'}]
    hydrated = sections.hydrate_section(raw, previous)
    parsed = s1_extract._parse_extraction(hydrated, 'Ari walked.')
    with pytest.raises(ValueError, match='base visual_anchor'):
        sections.merge_section(previous, parsed, 'p0001s0002_')


def test_section_inherits_book_metadata_and_ignores_only_unused_known_id_echoes():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    previous.characters.append(previous.characters[0].model_copy(update={
        'id': 'p0001s0001_char_002', 'name': 'Keeper'}))
    raw = payload(2, 'Ari closed the gate.')
    raw.pop('title')
    raw.pop('author')
    raw.pop('total_scenes')
    raw['characters'].append({'id': 'p0001s0001_char_002'})
    hydrated = sections.hydrate_section(raw, previous)
    assert hydrated['title'] == previous.title
    assert hydrated['author'] == previous.author
    assert [c['id'] for c in hydrated['characters']] == ['p0001s0001_char_001']
    parsed = s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
    merged = sections.merge_section(previous, parsed, 'p0001s0002_')
    assert len(merged.characters) == 2  # the book still retains the earlier keeper
    raw['characters'][-1]['appearance_timeline'] = []
    assert len(sections.hydrate_section(raw, previous)['characters']) == 1  # empty deltas are echoes too
    raw['characters'][-1] = {'id': 'p0001s0002_char_unknown'}
    assert len(sections.hydrate_section(raw, previous)['characters']) == 2


@run_async
async def test_section_repairs_metadata_and_evidence_locally_without_model_retry():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    for key in ('title', 'author', 'total_scenes'):
        raw.pop(key)
    raw['characters'][0].update(default_outfit=None, gender=None)
    raw['character_participation'] = []
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=raw)
    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', 'Ari closed the gate.', generate=generate,
        prepare=lambda value: sections.hydrate_section(value, previous),
        validate=lambda value: sections.merge_section(previous, value, 'p0001s0002_'))
    assert len(calls) == 1
    assert result.value.scenes[0].character_ids == ['p0001s0001_char_001']
    assert result.value.total_scenes == 1


@pytest.mark.parametrize('echo', ['identical', 'id_only', 'empty_delta'])
@run_async
async def test_redundant_registry_entries_need_one_model_response(echo):
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.', appearance())
    character = raw['characters'][0]
    duplicate = (json.loads(json.dumps(character)) if echo == 'identical' else
                 {'id': character['id']})
    if echo == 'empty_delta':
        duplicate.update(appearance_states=[], appearance_timeline=[], relationships=[])
    raw['characters'].append(duplicate)
    original = json.dumps(raw, sort_keys=True)
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        assert len(calls) == 1, 'Repeating the same authority must not trigger a paid correction'
        return ApiResult(value=raw)
    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', 'Ari closed the gate.', generate=generate,
        prepare=lambda value: sections.hydrate_section(value, previous),
        validate=lambda value: sections.merge_section(previous, value, 'p0001s0002_'))
    merged = sections.merge_section(previous, result.value, 'p0001s0002_')
    assert len(result.value.characters) == 1
    assert merged.characters[0].appearance_states[0].continuity_guard == 'Preserve the bandaged arm.'
    assert merged.characters[0].appearance_timeline[-1].state_id == 'hurt'
    assert json.dumps(raw, sort_keys=True) == original


def test_coalescing_repetitions_retains_conflicting_definitions():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['characters'].append({**raw['characters'][0], 'name': 'Different individual',
                              'visual_anchor': 'adult, red hair'})
    hydrated = sections.hydrate_section(raw, previous)
    assert len(hydrated['characters']) == 2
    parsed = s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
    with pytest.raises(ValueError, match='Duplicate characters IDs'):
        sections.merge_section(previous, parsed, 'p0001s0002_')


@pytest.mark.parametrize('reference', ['roster', 'evidence', 'both', 'background'])
def test_section_resolves_omitted_known_entities_from_references(reference):
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.', appearance()))
    raw = payload(2, 'Ari closed the gate.')
    raw.pop('characters')
    raw.pop('locations')
    if reference == 'roster':
        raw['character_participation'] = []
    elif reference == 'evidence':
        raw['scenes'][0]['character_ids'] = []
    elif reference == 'background':
        raw['scenes'][0]['character_ids'] = []
        raw['character_participation'][0]['classification'] = 'background_only'
    hydrated = sections.hydrate_section(raw, previous)
    assert hydrated['characters'][0]['visual_anchor'] == previous.characters[0].visual_anchor
    assert hydrated['characters'][0]['appearance_states'] == previous.characters[0].model_dump(mode='json')['appearance_states']
    assert hydrated['characters'][0]['appearance_timeline'] == []
    assert hydrated['locations'][0]['id'] == 'p0001s0001_loc_001'
    assert 'characters' not in raw
    parsed = s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
    merged = sections.merge_section(previous, parsed, 'p0001s0002_')
    assert merged.characters == previous.characters
    assert parsed.scenes[0].character_ids == ([] if reference == 'background' else ['p0001s0001_char_001'])
    assert len(merged.scenes) == 2


@pytest.mark.parametrize('unknown', ['character', 'scene', 'both'])
def test_registry_resolution_never_invents_unknown_entities_or_imports_old_scenes(unknown):
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['characters'] = []
    evidence = raw['character_participation'][0]
    if unknown in {'character', 'both'}:
        evidence['character_id'] = 'p0001s0002_unknown'
        raw['scenes'][0]['character_ids'] = ['p0001s0002_unknown']
    if unknown in {'scene', 'both'}:
        evidence['scene_id'] = 'p0001s0001_scene_001'
    hydrated = sections.hydrate_section(raw, previous)
    with pytest.raises(ValueError, match='Participation evidence must reference') as error:
        s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
    if unknown in {'character', 'both'}:
        assert 'p0001s0002_unknown' in str(error.value)
        assert not hydrated['characters']
    if unknown in {'scene', 'both'}:
        assert 'p0001s0001_scene_001' in str(error.value)
        assert len(hydrated['scenes']) == 1


@run_async
async def test_omitted_known_definitions_need_one_response_not_a_correction():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['characters'] = []
    raw['locations'] = []
    calls = 0
    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        assert calls == 1, 'Registry assembly must not need a model correction'
        return ApiResult(value=raw)
    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', 'Ari closed the gate.', generate=generate,
        prepare=lambda value: sections.hydrate_section(value, previous),
        validate=lambda value: sections.merge_section(previous, value, 'p0001s0002_'))
    assert result.value.characters[0].id == 'p0001s0001_char_001'
    assert calls == 1


@pytest.mark.parametrize("heading, number", [
    ("[ 7 ]", 7), ("XII.", 12), ("Chapter Twenty-One: The Gate", 21), ("CHAPTER IV", 4),
    ("Prologue", None), ("Book Two", None), ("Part 3", None)])
def test_heading_number_reads_only_chapter_numbers(heading, number):
    from novel_to_comic.chapter_detection import heading_number
    assert heading_number(heading) == number


def _scene_at(offset, chapter=99, quote="q"):
    from novel_to_comic.models.story_bible import Scene
    return Scene(id=f"s{offset}", chapter=chapter, title="t", location_id=None, character_ids=[],
                 summary="s", scene_type="action", narrative_beat="rising_action",
                 source_start_quote=quote, source_start_offset=offset)


def test_chapters_come_from_detected_headings_not_the_model():
    body = "Ari crossed the gate and waited for the bell. " * 6 + "\n"
    text = ("CROSSING\nBy A. Writer\n\n[ 1 ]\n" + body + "[ PART 1 ]\n\n[ 2 ]\n" + body * 2
            + "[ 4 ]\n" + body)
    second, fourth = text.index("[ PART 1 ]"), text.index("[ 4 ]")
    scenes = [_scene_at(0), _scene_at(second, quote="[ PART 1 ]\n\n[ 2 ]\nAri crossed the gate."),
              _scene_at(second + 300), _scene_at(fourth)]
    sections.assign_chapters(scenes, text, None)
    assert [scene.chapter for scene in scenes] == [1, 2, 2, 4]

    # A later part that opens mid-chapter continues the previous part's chapter.
    later = body + "[ 8 ]\n" + body
    scenes = [_scene_at(0), _scene_at(later.index("[ 8 ]"))]
    sections.assign_chapters(scenes, later, 7)
    assert [scene.chapter for scene in scenes] == [7, 8]

    untitled = [_scene_at(0, chapter=3)]
    sections.assign_chapters(untitled, body * 3, 2)
    assert untitled[0].chapter == 3  # no headings: the extraction's numbering stands


def test_joining_a_continued_scene_keeps_every_reference_and_activation_order():
    bible = StoryBible.model_validate({
        "title": "T", "author": "A", "total_scenes": 2, "sequences": [], "props": [],
        "characters": [{"id": "ari", "name": "Ari", "visual_anchor": "adult", "age_range": "", "gender": "",
                        "distinguishing_features": [], "default_outfit": "", "first_appearance_scene": "a",
                        "appearance_states": [appearance("hurt"), appearance("healed")],
                        "appearance_timeline": [{"state_id": "hurt", "at": {"scene_id": "a", "beat": 2}},
                                                {"state_id": "healed", "at": {"scene_id": "b"}}]},
                       {"id": "goblin", "name": "Goblin", "visual_anchor": "green", "age_range": "", "gender": "",
                        "distinguishing_features": [], "default_outfit": "", "first_appearance_scene": "b"}],
        "locations": [{"id": "hall", "name": "Hall", "visual_anchor": "hall", "mood": "dim"}],
        "scenes": [{"id": scene_id, "chapter": 1, "title": scene_id, "location_id": "hall",
                    "character_ids": ["ari"] if scene_id == "a" else ["ari", "goblin"],
                    "summary": f"Part {scene_id}.", "scene_type": "action", "narrative_beat": "rising_action",
                    "source_start_quote": scene_id} for scene_id in ("a", "b")]})
    joined = sections.join_continued_scene(bible, "a", "b")
    assert [scene.id for scene in joined.scenes] == ["a"] and joined.total_scenes == 1
    assert joined.scenes[0].summary == "Part a. Part b."
    assert joined.scenes[0].character_ids == ["ari", "goblin"]
    assert joined.characters[1].first_appearance_scene == "a"
    assert [(a.state_id, a.at.scene_id, a.at.beat) for a in joined.characters[0].appearance_timeline] == [
        ("hurt", "a", 2), ("healed", "a", 3)]


@run_async
async def test_a_section_that_opens_mid_scene_continues_it(tmp_path, monkeypatch):
    text = "".join(f"Ari crossed gate number {i}. " for i in range(400))
    (tmp_path / "novel.txt").write_text(text)
    seen = {}

    async def generate(**kwargs):
        content = json.loads(kwargs["user_content"])
        if kwargs["feature"] == "extract.sequences":
            ids = [s["id"] for s in content["scenes"]]
            return ApiResult(value={"title": "Crossing", "author": "Unknown",
                                    "sequences": [{"number": 1, "title": "All", "scenes": ids}]})
        index = content["section"]
        seen[index] = ("previous_scene" in content,
                       "continues_previous_scene" in kwargs["json_schema"]["properties"])
        value = payload(index, content["source_section"])
        if index == 2:
            value["continues_previous_scene"] = True
            assert content["previous_scene"]["id"] == "p0001s0001_scene_001"
        return ApiResult(value=value)

    monkeypatch.setattr(sections, "generate_json", generate)
    config = Config(extraction_chunk_chars=4000)
    ctx = StageRuntime("extract", create_initial_state("test", "novel.txt"), tmp_path)
    bible = await s1_extract.run(config, tmp_path, ctx)
    parts = sections.split_source(text, 4000)
    assert seen[1] == (False, False) and seen[2] == (True, True)
    assert len(bible.scenes) == len(parts) - 1
    assert bible.scenes[0].summary == "Ari crosses the gate. Ari crosses the gate."
    document = TargetArtifacts(tmp_path).read_source()
    assert document.scenes[0].last_unit_id == document.units[
        len(source_units(parts[0] + parts[1])) - 1].id


def test_section_prefixes_name_the_part_and_never_look_like_another_part():
    """A one-part book once got ``p0001s0002_*`` entities from its second section."""
    assert sections.section_prefix(1, 2) == "p0001s0002_"
    assert sections.section_prefix(1, 2) != sections.section_prefix(2, 1)
    assert not sections.section_prefix(1, 2).startswith("part")
