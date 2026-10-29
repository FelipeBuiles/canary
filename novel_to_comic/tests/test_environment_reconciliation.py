"""Local reconciliation must never spill secret values or lose unselected production state."""
import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('environment_sync', ROOT / 'scripts/canary_env.py')
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)


@pytest.fixture
def production():
    values = {name: 'PRODUCTION_DISTINCTIVE_' + name for name in env.secrets.REQUIRED}
    values['LITELLM_API_KEY'] = values['LITELLM_MASTER_KEY']
    values['RUNWARE_API_KEY'] = 'PRODUCTION_DISTINCTIVE_RUNWARE'
    return {'version': 1, 'env': values, 'files': {}}


@pytest.fixture
def snapshot(production):
    return {'revision': 'r1', 'bundle_sha256': 'b' * 64, 'loader_sha256': env.secrets.loader_digest(),
            'ciphertext': base64.b64encode(b'{"encrypted":"only"}').decode(), 'host_recipient': 'host',
            'schema': {'CANARY_RUNWARE_FIRST_ENABLED': {'type': 'boolean', 'default': 'false', 'backoffice': 'editable'}},
            'values': {'CANARY_RUNWARE_FIRST_ENABLED': 'false'},
            'secret_schema': {'allowed': sorted(env.secrets.ALLOWED), 'required': sorted(env.secrets.REQUIRED),
                              'mirrored': dict(env.secrets.MIRRORED)}}


def test_diff_redacts_known_and_new_unknown_secret_values(snapshot, production):
    local = {'RUNWARE_API_KEY': 'LOCAL_DISTINCTIVE_KEY', 'NEW_PROVIDER_TOKEN': 'UNKNOWN_DISTINCTIVE_KEY',
             'CANARY_RUNWARE_FIRST_ENABLED': 'true'}
    result = env.compare(local, snapshot, production)
    serialized = json.dumps(result)
    assert 'DISTINCTIVE' not in serialized
    rows = {row['name']: row for row in result['variables']}
    assert rows['RUNWARE_API_KEY'] == {'name': 'RUNWARE_API_KEY', 'kind': 'secret', 'status': 'changed'}
    assert rows['NEW_PROVIDER_TOKEN']['status'] == 'unsupported'
    assert rows['CANARY_OPS_TOKEN']['status'] == 'production_only'
    assert rows['CANARY_RUNWARE_FIRST_ENABLED']['local_value'] == 'true'


def test_merge_preserves_unselected_and_production_only_secrets(snapshot, production):
    local = {'RUNWARE_API_KEY': 'chosen', 'STRIPE_SECRET_KEY': 'unselected', 'FAL_KEY': 'new'}
    patch, candidate = env.reconcile(local, snapshot, production, ['RUNWARE_API_KEY', 'FAL_KEY'], [])
    assert patch == {}
    assert candidate['env']['RUNWARE_API_KEY'] == 'chosen'
    assert candidate['env']['FAL_KEY'] == 'new'
    assert candidate['env']['STRIPE_SECRET_KEY'] == production['env']['STRIPE_SECRET_KEY']
    assert production['env']['RUNWARE_API_KEY'] != 'chosen'


def test_explicit_remove_is_required_and_required_names_cannot_be_removed(snapshot, production):
    _, candidate = env.reconcile({}, snapshot, production, [], ['RUNWARE_API_KEY'])
    assert 'RUNWARE_API_KEY' not in candidate['env']
    with pytest.raises(env.EnvError, match='required_secret'):
        env.reconcile({}, snapshot, production, [], ['CANARY_OPS_TOKEN'])


def test_mirrored_gateway_keys_cannot_diverge(snapshot, production):
    _, result = env.reconcile({'LITELLM_API_KEY': 'new'}, snapshot, production, ['LITELLM_API_KEY'], [])
    assert result['env']['LITELLM_API_KEY'] == result['env']['LITELLM_MASTER_KEY'] == 'new'
    with pytest.raises(env.EnvError, match='conflicting_mirrored'):
        env.reconcile({'LITELLM_API_KEY': 'one', 'LITELLM_MASTER_KEY': 'two'}, snapshot, production,
                      ['LITELLM_API_KEY', 'LITELLM_MASTER_KEY'], [])


@pytest.mark.parametrize('local, selected, removed, code', [
    ({'RUNWARE_API_KEY': ''}, ['RUNWARE_API_KEY'], [], 'empty_secret'),
    ({'NEW_SECRET': 'never show'}, ['NEW_SECRET'], [], 'unsupported_name'),
    ({}, ['RUNWARE_API_KEY'], [], 'missing_locally'),
    ({}, [], [], 'select_at_least'),
    ({'RUNWARE_API_KEY': 'x'}, ['RUNWARE_API_KEY'], ['RUNWARE_API_KEY'], 'conflicting_selection'),
])
def test_selection_guards(local, selected, removed, code, snapshot, production):
    with pytest.raises(env.EnvError, match=code):
        env.reconcile(local, snapshot, production, selected, removed)


def test_private_dotenv_does_not_interpolate_or_execute(tmp_path):
    path = tmp_path / 'production.env'
    path.write_text('RUNWARE_API_KEY="literal-$HOME-${OTHER}-$(echo secret)"\nCANARY_RUNWARE_FIRST_ENABLED=false\n')
    path.chmod(0o600)
    result = env.read_env(path)
    assert result['RUNWARE_API_KEY'] == 'literal-$HOME-${OTHER}-$(echo secret)'
    path.write_text('KEY=x\nKEY=y\n')
    with pytest.raises(env.EnvError, match='duplicate'):
        env.read_env(path)
    path.chmod(0o644)
    with pytest.raises(env.EnvError, match='0600'):
        env.read_env(path)


def test_initializer_never_writes_production_secrets(snapshot, tmp_path):
    path = tmp_path / 'production.env'
    env.initialize(path, snapshot)
    assert path.stat().st_mode & 0o077 == 0
    assert 'DISTINCTIVE' not in path.read_text()
    assert env.read_env(path) == snapshot['values']
    with pytest.raises(FileExistsError):
        env.initialize(path, snapshot)


def test_stale_preparation_fails_before_upload_or_plan(snapshot, tmp_path, monkeypatch):
    file = tmp_path / 'reconciliation.json'
    file.write_text(json.dumps({'revision': 'old', 'patch': {}, 'bundle_sha256': 'b' * 64}))
    file.chmod(0o600)
    calls = []
    monkeypatch.setattr(env.client, 'send', lambda request, _: calls.append(request) or {'revision': 'new'})
    with pytest.raises(env.EnvError, match='baseline_changed'):
        env.submit_prepared(tmp_path, {})
    assert calls == [{'action': 'config_status'}]


def test_plan_binds_exact_baseline_and_never_applies(tmp_path, monkeypatch):
    path = tmp_path / 'reconciliation.json'
    path.write_text(json.dumps({'revision': 'r1', 'patch': {'CANARY_RUNWARE_FIRST_ENABLED': 'true'}, 'bundle_sha256': None}))
    path.chmod(0o600)
    calls = []
    monkeypatch.setattr(env.client, 'send', lambda request, _: calls.append(request) or {'revision': 'r1'})
    monkeypatch.setattr(env.client, 'watch', lambda *_, **__: 0)
    assert env.submit_prepared(tmp_path, {}) == 0
    assert calls[1]['expected_revision'] == 'r1'
    assert calls[1]['action'] == 'config_plan'
    assert all(row['action'] != 'config_apply' for row in calls)


def test_prepare_verifies_exact_ciphertext_before_signing(snapshot, production, tmp_path, monkeypatch):
    output = tmp_path / 'prepared'
    observed = []
    monkeypatch.setattr(env, 'verify_recovery_identity', lambda *_: None)
    def encrypt(data, recipients, path):
        observed.append(('encrypt', json.loads(data)))
        path.write_bytes(b'ciphertext-only')
    monkeypatch.setattr(env.secrets, 'encrypt_export', encrypt)
    monkeypatch.setattr(env.secrets, 'ciphertext_recipients', lambda *_: {'host', 'recovery'})
    expected = copy.deepcopy(production)
    expected['env']['RUNWARE_API_KEY'] = 'LOCAL_DISTINCTIVE_KEY'
    def decrypt(raw, identity, digest):
        assert raw == b'ciphertext-only'
        assert digest == env.secrets.hashlib.sha256(raw).hexdigest()
        observed.append(('recovery', digest))
        return expected
    monkeypatch.setattr(env, 'decrypt_memory', decrypt)
    monkeypatch.setattr(env.secrets, 'trusted_tool', lambda _: 'ssh-keygen')
    def sign(args):
        observed.append(('sign', args))
        Path(args[-1] + '.sig').write_text('dummy-signature')
    monkeypatch.setattr(env.secrets, 'checked_process', sign)
    key = tmp_path / 'signing'
    key.write_bytes(b'dummy')
    key.chmod(0o600)
    result = env.prepare({'RUNWARE_API_KEY': 'LOCAL_DISTINCTIVE_KEY'}, snapshot, production,
                         ['RUNWARE_API_KEY'], [], output, tmp_path / 'recovery', key)
    assert [row[0] for row in observed] == ['encrypt', 'recovery', 'sign']
    assert result['bundle_sha256'] == env.secrets.hashlib.sha256(b'ciphertext-only').hexdigest()
    for path in output.iterdir():
        assert 'DISTINCTIVE' not in path.read_text()
        assert path.stat().st_mode & 0o077 == 0


def test_export_refuses_wrong_digest(monkeypatch):
    value = {'revision': 'r', 'bundle_sha256': 'a' * 64, 'loader_sha256': 'b' * 64,
             'ciphertext': base64.b64encode(b'wrong').decode(), 'schema': {}, 'values': {}, 'secret_schema': {}, 'host_recipient': 'host'}
    monkeypatch.setattr(env.client, 'send', lambda *_: value)
    with pytest.raises(env.EnvError, match='digest_mismatch'):
        env.export({})


def test_recovery_identity_must_be_independent(snapshot, tmp_path, monkeypatch):
    identity = tmp_path / 'key'
    identity.write_text('dummy')
    identity.chmod(0o600)
    monkeypatch.setattr(env.secrets, 'trusted_tool', lambda _: 'age-keygen')
    monkeypatch.setattr(env.secrets, 'checked_process', lambda *_: b'host\n')
    monkeypatch.setattr(env.secrets, 'ciphertext_recipients', lambda *_: {'host', 'recovery'})
    with pytest.raises(env.EnvError, match='independent'):
        env.verify_recovery_identity(snapshot, identity)


def test_explicit_public_removal_restores_declared_default(snapshot, production):
    patch, candidate = env.reconcile({}, snapshot, production, [], ['CANARY_RUNWARE_FIRST_ENABLED'])
    assert patch == {'CANARY_RUNWARE_FIRST_ENABLED': 'false'}
    assert candidate == production


@pytest.mark.parametrize('value', ['yes', '${INTERPOLATED}', 'quote"', 'line\nbreak'])
def test_invalid_public_values_refused_before_encryption(snapshot, production, value):
    with pytest.raises(env.EnvError, match='invalid_public_setting'):
        env.reconcile({'CANARY_RUNWARE_FIRST_ENABLED': value}, snapshot, production,
                      ['CANARY_RUNWARE_FIRST_ENABLED'], [])


def test_automatic_selection_never_silently_skips_empty_or_unsupported(snapshot, production):
    empty = env.compare({'RUNWARE_API_KEY': ''}, snapshot, production)
    with pytest.raises(env.EnvError, match='explicit_remove'):
        env.select_changes(empty, [], [])
    unsupported = env.compare({'NEW_SECRET': 'hidden'}, snapshot, production)
    with pytest.raises(env.EnvError, match='unsupported_names'):
        env.select_changes(unsupported, [], [])
    changed = env.compare({'RUNWARE_API_KEY': 'new'}, snapshot, production)
    assert env.select_changes(changed, [], []) == ['RUNWARE_API_KEY']
    assert env.select_changes(unsupported, ['RUNWARE_API_KEY'], []) == ['RUNWARE_API_KEY']
