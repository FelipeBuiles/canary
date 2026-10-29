#!/usr/bin/env python3
"""Compare a private production env file and prepare signed, selective reconciliation.

Secret plaintext exists only in memory. Diff/report output contains secret names
and change categories, never secret values or secret value hashes.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime
import importlib.util
import io
import json
import os
import re
import resource
import stat
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent
MAX_BYTES = 1024 * 1024
MAX_CIPHERTEXT_BYTES = 2 * 1024 * 1024


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


client = module('env_config_client', 'canary_config.py')
secrets = module('env_secret_loader', 'canary_secrets.py')


class EnvError(RuntimeError):
    """Fixed error codes only: never interpolate parser/crypto exception text."""


def private_bytes(path, limit=MAX_BYTES):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise EnvError('local_file_must_be_owned_by_you_and_mode_0600')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise EnvError('local_file_too_large')
    return raw


def read_env(path):
    # The locked project dependency parses dotenv syntax without interpolation,
    # shell execution, ambient environment reads, or warning echoes of input.
    from dotenv.parser import parse_stream
    values = {}
    for item in parse_stream(io.StringIO(private_bytes(path).decode())):
        if item.error or (item.key and (item.value is None or not re.fullmatch(r'[A-Z][A-Z0-9_]*', item.key))):
            raise EnvError('invalid_production_env_syntax')
        if not item.key:
            continue
        if item.key in values:
            raise EnvError('duplicate_production_env_name')
        if '\0' in item.value:
            raise EnvError('invalid_production_env_value')
        values[item.key] = item.value
    return values


def export(settings):
    snapshot = client.send({'action': 'config_export'}, settings)
    if set(snapshot) != {'revision', 'bundle_sha256', 'loader_sha256', 'ciphertext', 'schema', 'values', 'secret_schema', 'host_recipient'}:
        raise EnvError('unsupported_production_export_rerun_with_matching_tooling')
    raw = base64.b64decode(snapshot['ciphertext'], validate=True)
    if len(raw) > MAX_CIPHERTEXT_BYTES or secrets.hashlib.sha256(raw).hexdigest() != snapshot['bundle_sha256']:
        raise EnvError('production_ciphertext_digest_mismatch')
    return snapshot, raw


def decrypt_memory(raw, identity, expected):
    # Verify the exact checked bytes without ever saving plaintext to disk.
    if secrets.hashlib.sha256(raw).hexdigest() != expected:
        raise EnvError('ciphertext_digest_mismatch')
    plain = secrets.checked_process(secrets.sops('--decrypt', '--input-type', 'json', '--output-type', 'json', '/dev/stdin'),
                                    data=raw, env=secrets.sops_env(identity))
    return secrets.validate(secrets.parse(plain))


def compare(local, snapshot, production):
    schema = snapshot['schema']
    allowed = set(snapshot['secret_schema']['allowed'])
    rows = []
    for name in sorted(local.keys() | production['env'].keys() | snapshot['values'].keys()):
        kind = 'secret' if name in allowed else 'setting' if name in schema else 'unsupported'
        present_local = name in local
        present_prod = name in (production['env'] if kind == 'secret' else snapshot['values'])
        old = (production['env'] if kind == 'secret' else snapshot['values']).get(name)
        state = ('unsupported' if kind == 'unsupported' else 'production_only' if not present_local
                 else 'local_only' if not present_prod else 'same' if local[name] == old else 'changed')
        row = {'name': name, 'kind': kind, 'status': state}
        # Unsupported names are redacted too: they may be new, undeployed secrets.
        if kind == 'setting':
            row.update(production_value=old, local_value=local.get(name))
        if kind == 'secret' and present_local and not local[name]:
            row['status'] = 'empty_secret_refused'
        rows.append(row)
    return {'revision': snapshot['revision'], 'bundle_sha256': snapshot['bundle_sha256'], 'variables': rows,
            'note': 'Secret values are hidden. Production-only names are preserved; removals require explicit selection.'}


def select_changes(report, selected, removed):
    if selected or removed:
        return selected
    if any(row['kind'] == 'unsupported' for row in report['variables']):
        raise EnvError('unsupported_names_present_select_supported_names_or_deploy_schema_first')
    if any(row['status'] == 'empty_secret_refused' for row in report['variables']):
        raise EnvError('empty_secret_requires_explicit_remove')
    return [row['name'] for row in report['variables'] if row['status'] in {'changed', 'local_only'}]


def reconcile(local, snapshot, production, selected, removed):
    if not selected and not removed:
        raise EnvError('select_at_least_one_name')
    if len(selected) != len(set(selected)) or len(removed) != len(set(removed)) or set(selected) & set(removed):
        raise EnvError('duplicate_or_conflicting_selection')
    candidate = copy.deepcopy(production)
    patch = {}
    allowed = set(snapshot['secret_schema']['allowed'])
    mirrors = snapshot['secret_schema']['mirrored']
    applied = {}
    for name in selected:
        if name not in local:
            raise EnvError('selected_name_missing_locally')
        if name in snapshot['schema']:
            patch[name] = local[name]
            continue
        if name not in allowed:
            raise EnvError('unsupported_name_requires_reviewed_schema_and_release')
        if not local[name]:
            raise EnvError('empty_secret_requires_explicit_remove')
        for target in [name, *([mirrors[name]] if name in mirrors else [])]:
            if target in applied and applied[target] != local[name]:
                raise EnvError('conflicting_mirrored_secret_values')
            if target in selected and local[target] != local[name]:
                raise EnvError('conflicting_mirrored_secret_values')
            candidate['env'][target] = applied[target] = local[name]
    for name in removed:
        if name in snapshot['schema']:
            rule = snapshot['schema'][name]
            if 'default' not in rule:
                raise EnvError('required_public_setting_cannot_be_removed')
            patch[name] = rule['default']
            continue
        if name not in allowed or name not in candidate['env']:
            raise EnvError('only_existing_optional_secrets_can_be_removed')
        for target in [name, *([mirrors[name]] if name in mirrors else [])]:
            candidate['env'].pop(target, None)
    try:
        secrets.validate(candidate)
    except secrets.SecretError:
        raise EnvError('candidate_invalid_required_secret_or_paired_credentials') from None
    for name, value in patch.items():
        rule = snapshot['schema'][name]
        valid = (isinstance(value, str) and rule.get('min_length', 0) <= len(value) <= 4096
                 and all(32 <= ord(char) <= 126 and char not in '\\\"$`' for char in value))
        if rule['type'] == 'boolean':
            valid = valid and value in {'true', 'false'}
        elif rule['type'] == 'fraction':
            valid = valid and bool(re.fullmatch(r'(?:0(?:\.\d+)?|1(?:\.0+)?)', value))
        elif rule['type'] == 'url':
            valid = valid and value.startswith('https://') and len(value) > 8
        if not valid:
            raise EnvError('invalid_public_setting_check_schema_and_literal_characters')
    return patch, candidate


def write_private(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(value)


def verify_recovery_identity(snapshot, identity):
    private_bytes(identity)
    recipient = secrets.checked_process([secrets.trusted_tool('age-keygen'), '-y', str(identity)]).decode().strip()
    recipients = secrets.ciphertext_recipients(json.loads(base64.b64decode(snapshot['ciphertext'], validate=True)))
    if recipient == snapshot['host_recipient'] or recipient not in recipients:
        raise EnvError('independent_recovery_recipient_required')


def prepare(local, snapshot, production, selected, removed, output, identity, signing_key):
    if snapshot['loader_sha256'] != secrets.loader_digest():
        raise EnvError('secret_loader_version_mismatch_update_operator_tooling')
    verify_recovery_identity(snapshot, identity)
    patch, candidate = reconcile(local, snapshot, production, selected, removed)
    report = compare(local, snapshot, production)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    request = {'revision': snapshot['revision'], 'patch': patch, 'bundle_sha256': None}
    if candidate != production:
        recipients = secrets.ciphertext_recipients(json.loads(base64.b64decode(snapshot['ciphertext'], validate=True)))
        bundle = output / 'bundle.sops.json'
        secrets.encrypt_export(client.canonical(candidate), sorted(recipients), bundle)
        bundle.chmod(0o600)
        digest = secrets.hashlib.sha256(bundle.read_bytes()).hexdigest()
        verified = decrypt_memory(bundle.read_bytes(), identity, digest)
        if verified != candidate:
            raise EnvError('candidate_recovery_verification_failed')
        authorization = {'target': 'production', 'bundle_sha256': digest,
                         'replaces_bundle_sha256': snapshot['bundle_sha256'], 'authorization_id': str(uuid.uuid4()),
                         'expires_at': int(time.time()) + 3600, 'recovery_verification': True}
        manifest = output / 'manifest.json'
        write_private(manifest, client.canonical(authorization))
        # trusted_tool also checks ancestor ownership/permissions.
        private_bytes(signing_key)
        secrets.checked_process([secrets.trusted_tool('ssh-keygen'), '-Y', 'sign', '-f', str(signing_key),
                                 '-n', 'canary-production-config', str(manifest)])
        Path(str(manifest) + '.sig').chmod(0o600)
        request['bundle_sha256'] = digest
    write_private(output / 'reconciliation.json', client.canonical(request))
    write_private(output / 'diff.json', client.canonical(report))
    return request


def submit_prepared(output, settings):
    prepared = json.loads(private_bytes(output / 'reconciliation.json'))
    if set(prepared) != {'revision', 'patch', 'bundle_sha256'}:
        raise EnvError('invalid_prepared_reconciliation')
    # Fail before upload if production moved; do not rebuild or retry the plan.
    current = client.send({'action': 'config_status'}, settings)
    if current['revision'] != prepared['revision']:
        raise EnvError('baseline_changed_compare_and_review_again')
    request = {'action': 'config_plan', 'request_id': str(uuid.uuid4()), 'patch': prepared['patch'],
               'expected_revision': prepared['revision']}
    if prepared['bundle_sha256']:
        raw = private_bytes(output / 'bundle.sops.json', MAX_CIPHERTEXT_BYTES)
        if secrets.hashlib.sha256(raw).hexdigest() != prepared['bundle_sha256']:
            raise EnvError('prepared_ciphertext_digest_mismatch')
        upload = client.send({'action': 'config_stage_bundle', 'bundle': base64.b64encode(raw).decode(),
                              'manifest': json.loads(private_bytes(output / 'manifest.json')),
                              'signature': base64.b64encode(private_bytes(output / 'manifest.json.sig')).decode()}, settings)
        request['bundle_id'] = upload['bundle_id']
    print(json.dumps({'request_id': request['request_id'], 'prepared_directory': str(output)}), flush=True)
    client.send(request, settings)
    observed = []
    def retain(line):
        value = json.loads(line)
        observed.append(value)
        print(line, flush=True)
    result = client.watch(request['request_id'], settings, emit=retain)
    if result == 0:
        ready = next((row['plan'] for row in reversed(observed) if row.get('phase') == 'plan_ready' and row.get('plan')), None)
        if ready:
            write_private(output / ('plan-' + request['request_id'] + '.json'), client.canonical(ready))
            command = ('python3 scripts/canary_config.py apply --target production --plan ' + ready['plan_id']
                       + ' --expect-plan-sha256 ' + ready['digest'] + ' --watch')
            print(json.dumps({'plan_id': ready['plan_id'], 'plan_digest': ready['digest'],
                              'restart_required': ready['restart_required'],
                              'changed_public_names': list(ready['changes']), 'secret_changes': ready['secret_changes'],
                              'backoffice_next_step': 'Open Backoffice → Environment, load the latest proposal, review and apply. SSH-only changes still require this command.',
                              'after_review_and_approval': command}))
    return result


def initialize(path, snapshot):
    lines = ['# Desired production overrides. Edit locally; never commit this file.',
             '# Missing names preserve production. Empty secret values are refused.',
             '# No interpolation: dollar signs are literal. No production secrets are copied here.', '']
    for name, value in sorted(snapshot['values'].items()):
        lines.append(name + '=' + json.dumps(value, ensure_ascii=False))
    lines.extend(['', '# Secret names currently supported (uncomment only values you intend to set):'])
    lines.extend('# ' + name + '=' for name in sorted(snapshot['secret_schema']['allowed']))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_private(path, ('\n'.join(lines) + '\n').encode())


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'diff', 'reconcile', 'plan'])
    parser.add_argument('--env-file', type=Path, default=BASE.parent / '.env.prod')
    parser.add_argument('--connection', type=Path, default=home / '.config/canary/production-operator.json')
    parser.add_argument('--recovery-identity', type=Path, default=home / '.config/canary/recovery/age.txt')
    parser.add_argument('--signing-key', type=Path, default=home / '.config/canary/prod/config_signing_ed25519')
    parser.add_argument('--select', action='append', default=[])
    parser.add_argument('--remove', action='append', default=[])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--prepare-only', action='store_true', help='Create encrypted artifacts without submitting a preview')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    settings = json.loads(private_bytes(args.connection))
    if set(settings) != {'identity', 'known_hosts', 'destination'} or not settings['destination'].startswith('canary-config@'):
        raise EnvError('invalid_operator_connection')
    if args.command == 'plan':
        if not args.prepared:
            raise EnvError('prepared_directory_required')
        return submit_prepared(args.prepared, settings)
    snapshot, raw = export(settings)
    if args.command == 'init':
        initialize(args.env_file, snapshot)
        print(json.dumps({'production_env_file': str(args.env_file), 'secret_values_written': False}))
        return 0
    local = read_env(args.env_file)
    verify_recovery_identity(snapshot, args.recovery_identity)
    production = decrypt_memory(raw, args.recovery_identity, snapshot['bundle_sha256'])
    report = compare(local, snapshot, production)
    if args.command == 'diff':
        if args.json:
            print(json.dumps(report))
        else:
            print(f"Production revision: {report['revision']}")
            for row in report['variables']:
                line = f"{row['status']:22} {row['kind']:11} {row['name']}"
                if row['kind'] == 'setting' and row['status'] == 'changed':
                    line += '  production=' + json.dumps(row['production_value']) + ' local=' + json.dumps(row['local_value'])
                print(line)
            print(report['note'])
        return 0
    selected = select_changes(report, args.select, args.remove)
    if not selected and not args.remove:
        print(json.dumps({'status': 'already_matches', 'production_only_names_preserved': True}))
        return 0
    output = args.output or home / '.config/canary/prod/reconciliations' / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    prepare(local, snapshot, production, selected, args.remove, output, args.recovery_identity, args.signing_key)
    print(json.dumps({'prepared_directory': str(output), 'selected_names': selected, 'removed_names': args.remove,
                      'next_command': f'./scripts/prod-env plan --prepared {output}'}))
    return 0 if args.prepare_only else submit_prepared(output, settings)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (EnvError, client.Rejected, secrets.SecretError) as error:
        print(json.dumps({'code': str(error)}))
        raise SystemExit(3) from None
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 — secret-bearing input/crypto boundary.
        print(json.dumps({'code': 'production_env_operation_failed_no_values_logged'}))
        raise SystemExit(5) from None
