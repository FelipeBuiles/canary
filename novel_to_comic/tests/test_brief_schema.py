"""Brief requests generate new intent, not approval or inherited direction."""

import pytest

from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
from novel_to_comic.ai.codex_schema import strict_output_schema
from novel_to_comic.briefing import SERIES_BRIEF_FIELDS, brief_inference_schema, propose_brief


@pytest.mark.parametrize('adapter', [strict_output_schema, anthropic_output_schema])
def test_brief_request_types_prevent_shape_corrections(adapter):
    schema = adapter(brief_inference_schema())
    properties = schema['properties']
    assert {'revision', 'status', 'content_sha256', 'unmatched_protected_language'}.isdisjoint(properties)
    assert set(schema['required']) == set(properties)
    assert properties['transformation_level']['enum'] == ['faithful', 'medium_specific', 'transformative']
    assert properties['character_turns']['type'] == 'array'
    assert properties['character_turns']['items']['type'] == 'string'
    assert properties['point_of_view']['type'] == 'string'
    assert properties['target_page_min']['type'] == 'integer'
    assert schema['additionalProperties'] is False


def test_later_part_generates_only_local_fields_and_keeps_approved_series_direction():
    inherited = {
        'themes': ('passage',), 'point_of_view': 'Ari', 'narrator_treatment': 'captions',
        'tone': 'hushed', 'motifs': ('doors',), 'transformation_level': 'faithful',
    }
    schema = strict_output_schema(brief_inference_schema(inherited=inherited))
    assert set(SERIES_BRIEF_FIELDS).isdisjoint(schema['properties'])
    brief = propose_brief({'story_promises': ['Cross the gate.'], 'target_page_min': 2,
                           'target_page_max': 4}, inherited=inherited)
    for field, value in inherited.items():
        assert getattr(brief, field) == value
    assert brief.status == 'draft'
    assert brief.revision == 1


def _source(*texts):
    from novel_to_comic.models.source import SourceDocument

    offset, units = 0, []
    for ordinal, text in enumerate(texts, start=1):
        units.append({'id': f'source_{ordinal:06d}', 'ordinal': ordinal,
                      'start_offset': offset, 'end_offset': offset + len(text), 'text': text})
        offset += len(text)
    return SourceDocument.model_validate({
        'text': ''.join(texts), 'units': units,
        'scenes': [{'id': 'scene_001', 'title': 'Paw', 'first_unit_id': units[0]['id'],
                    'last_unit_id': units[-1]['id']}],
    })


def test_draft_brief_protects_only_wording_the_source_carries():
    source = _source('“It had a spell put on it by an old fakir,” said the sergeant-major, “a very holy man. ',
                     'He wanted to show that fate ruled people’s lives. ')
    brief = propose_brief({
        'protected_language': [
            'It had a spell put on it by an old Fakir, a very holy man.',
            'He wanted to show that fate ruled people’s lives.',
            'Be careful what you wish for.',
        ],
        'target_page_min': 2, 'target_page_max': 4,
    }, source=source)

    assert brief.protected_language == (
        '"It had a spell put on it by an old fakir," said the sergeant-major, "a very holy man."',
        'He wanted to show that fate ruled people’s lives.',
    )
    assert brief.unmatched_protected_language == ('Be careful what you wish for.',)


def test_authored_protected_language_edits_are_anchored_before_they_persist(tmp_path):
    from novel_to_comic.briefing import revise_persisted_brief
    from novel_to_comic.target_artifacts import TargetArtifacts

    artifacts = TargetArtifacts(tmp_path)
    source = _source('I saw the door open. ', 'I fled into the rain. ')
    artifacts.write_source(source)
    artifacts.write_brief(propose_brief({'target_page_min': 1, 'target_page_max': 2}, source=source))

    revised = revise_persisted_brief(
        artifacts, expected_revision=1,
        protected_language=['I saw the Door open.', 'The door was never there.'],
    )

    assert revised.protected_language == ('I saw the door open.',)
    assert revised.unmatched_protected_language == ('The door was never there.',)
    # Unrelated edits keep the author-visible note.
    assert revise_persisted_brief(artifacts, expected_revision=2, tone='cold').unmatched_protected_language == (
        'The door was never there.',
    )


def test_brief_saved_before_unmatched_language_existed_keeps_its_hash():
    import hashlib
    import json

    from novel_to_comic.models.adaptation import AdaptationBrief

    legacy = {'revision': 2, 'status': 'draft', 'story_promises': ['Cross the gate.'], 'themes': [],
              'point_of_view': '', 'narrator_treatment': '', 'tone': '', 'ambiguities': [], 'motifs': [],
              'protected_language': ['I saw the door open.'], 'essential_events': [], 'character_turns': [],
              'transformation_level': 'medium_specific', 'desired_emphasis': [],
              'target_page_min': 1, 'target_page_max': 2}
    digest = hashlib.sha256(json.dumps(legacy, ensure_ascii=False, separators=(',', ':'),
                                       sort_keys=True).encode()).hexdigest()

    brief = AdaptationBrief.model_validate({**legacy, 'content_sha256': digest})

    # Adapt lineage, prompts and BookAdaptation.brief_sha256 all bind this serialization.
    assert brief.content_sha256 == digest
    assert brief.model_dump(mode='json') == {**legacy, 'content_sha256': digest}
