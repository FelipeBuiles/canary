"""Brief requests generate new intent, not approval or inherited direction."""

import pytest

from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
from novel_to_comic.ai.codex_schema import strict_output_schema
from novel_to_comic.briefing import SERIES_BRIEF_FIELDS, brief_inference_schema, propose_brief


@pytest.mark.parametrize('adapter', [strict_output_schema, anthropic_output_schema])
def test_brief_request_types_prevent_shape_corrections(adapter):
    schema = adapter(brief_inference_schema())
    properties = schema['properties']
    assert {'revision', 'status', 'content_sha256'}.isdisjoint(properties)
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
