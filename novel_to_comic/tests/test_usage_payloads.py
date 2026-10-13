import copy
import json
from unittest.mock import MagicMock

from novel_to_comic.ai import client
from novel_to_comic.ai.usage_payloads import compact_metadata, compact_params
from novel_to_comic.usage import UsageRecord


def test_params_drop_nested_content_and_fingerprint_schemas():
    params = {
        'model': 'test-model', 'temperature': 0.2, 'quality': 'high', 'service_tier': 'priority',
        'messages': [{'content': 'private story'}],
        'metadata': {'prompt': 'private story'},
        'canary_wire_request': json.dumps({'prompt': 'private story', 'image': 'x' * 100000}),
        'response_format': {'type': 'json_schema', 'json_schema': {'schema': {'description': 'private story'}}},
        'unknown_provider_field': {'secret': 'private story'},
        'thinkingConfig': {'thinkingLevel': 'high', 'includeThoughts': True, 'unknown': 'private story'},
    }
    original = copy.deepcopy(params)
    compact = compact_params(params)
    assert params == original
    assert compact['quality'] == 'high'
    assert compact['temperature'] == 0.2
    assert compact['service_tier'] == 'priority'
    assert compact['thinkingConfig'] == {'thinkingLevel': 'high', 'includeThoughts': True}
    assert len(compact['response_format_summary']['sha256']) == 64
    assert compact['canary_wire_request_summary']['bytes'] > 100000
    assert 'private story' not in json.dumps(compact)
    assert len(json.dumps(compact)) < 1000
    assert compact_params({'response_format': 'b64_json'}) == {'response_format': 'b64_json'}


def test_metadata_preserves_accounting_dimensions_without_runtime_content():
    metadata = {'page_number': 3, 'is_correction': True, 'funding': 'codex_subscription',
                'api_equivalent_cost_usd': 0.2, 'metadata': {'source_scope': 'chapter',
                'source_unit_ids': ['source'] * 10000, 'project_name': 'private story'},
                'codex_runtime': {'thread_id': 'thread', 'turn_status': 'completed',
                'requested_service_tier': 'priority', 'service_tier': 'priority',
                'indeterminate': False, 'execution_elapsed_seconds': 12.5,
                'revised_prompt': 'private story', 'events': ['private story'] * 10000,
                'effective_features': {'content': 'private story'}}}
    original = copy.deepcopy(metadata)
    compact = compact_metadata(metadata)
    assert metadata == original
    assert compact['page_number'] == 3 and compact['is_correction'] is True
    assert compact['source_units']['count'] == 10000
    assert compact['codex_runtime'] == {'thread_id': 'thread', 'turn_status': 'completed',
                                        'requested_service_tier': 'priority', 'service_tier': 'priority',
                                        'indeterminate': False, 'execution_elapsed_seconds': 12.5}
    assert compact['api_equivalent_cost_usd'] == 0.2
    assert 'private story' not in json.dumps(compact)
    assert len(json.dumps(compact)) < 1000


def test_database_writes_compact_metadata_and_preserve_usage(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr('novel_to_comic.server.db.get_db', lambda: db)
    monkeypatch.setattr('novel_to_comic.server.telemetry.observe_generation', lambda **kw: None)
    metadata = {'funding': 'codex_subscription', 'page_number': 2,
                'codex_runtime': {'revised_prompt': 'private story', 'thread_id': 'thread'}}
    client._insert_event(event_id='call', model_alias='test-model', feature='test', operation='text',
                         params_json={}, request_summary_json={'prompt_sha256': 'hash'}, metadata_json=metadata)
    inserted = db.table.return_value.insert.call_args
    assert inserted.kwargs == {'returning': 'minimal'}
    assert inserted.args[0]['metadata_json']['codex_runtime'] == {'thread_id': 'thread'}
    usage = UsageRecord(provider='codex', model='test-model', operation='text',
                        funding='codex_subscription', input_tokens=100, output_tokens=20)
    client._finalize_event(event_id='call', status='succeeded', feature='test', model_alias='test-model',
                           latency_ms=42, usage=usage, metadata=metadata,
                           response_data={'id': 'provider-id', 'usage': {'input_tokens': 100}})
    updated = db.table.return_value.update.call_args
    assert updated.kwargs == {'returning': 'minimal'}
    row = updated.args[0]
    assert row['input_tokens'] == 100 and row['output_tokens'] == 20
    assert row['provider_response_id'] == 'provider-id'
    assert row['funding'] == 'codex_subscription'
    assert row['usage_json'] == {'input_tokens': 100}
    assert row['metadata_json']['page_number'] == 2
    assert 'private story' not in json.dumps(row)
    assert metadata['codex_runtime']['revised_prompt'] == 'private story'
