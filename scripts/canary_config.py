#!/usr/bin/env python3
"""Operator client for the installed configuration controller; no production defaults."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

REJECTIONS = frozenset({
    'invalid_request', 'rejected_busy', 'baseline_changed', 'plan_expired', 'authorization_expired',
    'configuration_operation_active', 'maintenance_active', 'config_not_enabled', 'already_drained',
    'drift_detected', 'unsupported_setting', 'ssh_only', 'invalid_setting', 'signature_required',
    'signature_invalid', 'invalid_manifest', 'authorization_used', 'recipient_change_forbidden',
    'ops_token_rotation_ssh_only', 'request_id_conflict', 'plan_not_ready', 'credential_required',
    'public_maintenance_active', 'upload_too_large', 'unsafe_permissions',
})


class Rejected(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def send(request, settings):
    # No remote command. The key must be forced to the exact installed controller.
    result = subprocess.run(['ssh', '-T', '-i', settings['identity'], '-o', 'IdentitiesOnly=yes',
                             '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                             '-o', 'UserKnownHostsFile=' + settings['known_hosts'],
                             '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10',
                             '-o', 'ServerAliveCountMax=2', settings['destination']],
                            input=canonical(request), capture_output=True, timeout=40, check=False)
    try:
        response = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError('request_outcome_unknown') from None
    if response.get('ok') is not True:
        code = response.get('code')
        if code in REJECTIONS:
            raise Rejected(code)
        raise RuntimeError('request_outcome_unknown')
    return response['result']


def watch(op, settings, after=0, *, preview=False, emit=print):
    while True:
        batch = send({'action': 'config_events', 'operation_id': op, 'after': after}, settings)
        for event in batch['events']:
            emit(json.dumps(event))
        after = batch['after']
        current = send({'action': 'config_status', 'operation_id': op}, settings)['operation']
        phase = current['phase']
        if phase in {'complete', 'plan_ready', 'failed', 'needs_inspection', 'rejected', 'rejected_busy'} and after >= current.get('seq', after):
            emit(json.dumps(current))
            return 0 if phase in {'complete', 'plan_ready'} else 3 if phase.startswith('rejected') else 4
        if len(batch['events']) < 100:
            time.sleep(2.5)


def sign(args):
    raw = args.bundle.read_bytes()
    if len(raw) > 2 * 1024 * 1024 or not args.recovery_verified:
        raise RuntimeError('recovery_verification_required')
    manifest = {'target': 'production', 'bundle_sha256': hashlib.sha256(raw).hexdigest(),
                'replaces_bundle_sha256': args.replaces_bundle_sha256,
                'authorization_id': str(uuid.uuid4()), 'expires_at': int(time.time()) + args.expires_in,
                'recovery_verification': True}
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = args.output / 'manifest.json'
    path.write_bytes(canonical(manifest))
    subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(args.signing_key),
                    '-n', 'canary-production-config', str(path)], check=True, capture_output=True, timeout=60)
    print(json.dumps({'manifest': str(path), 'signature': str(path) + '.sig',
                      'bundle_sha256': manifest['bundle_sha256'], 'authorization_id': manifest['authorization_id']}))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'apply', 'status', 'watch', 'sign'])
    parser.add_argument('--target', choices=['production'], default='production')
    parser.add_argument('--connection', type=Path, default=Path.home() / '.config/canary/production-operator.json')
    parser.add_argument('--set', action='append', default=[], dest='changes')
    parser.add_argument('--request-id', default=None)
    parser.add_argument('--operation')
    parser.add_argument('--plan')
    parser.add_argument('--expect-plan-sha256')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--after', type=int, default=0)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--bundle-sha256')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--signature', type=Path)
    parser.add_argument('--signing-key', type=Path)
    parser.add_argument('--replaces-bundle-sha256')
    parser.add_argument('--recovery-verified', action='store_true')
    parser.add_argument('--expires-in', type=int, default=3600)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--json', action='store_true', help='Output is always structured JSON')
    args = parser.parse_args()
    if args.command == 'sign':
        if not all((args.bundle, args.signing_key, args.replaces_bundle_sha256, args.output)) or not 1 <= args.expires_in <= 86400:
            parser.error('sign requires bundle, signing-key, replaces-bundle-sha256 and output; expiry is 1–86400 seconds')
        sign(args)
        return 0
    settings = json.loads(args.connection.read_text())
    if set(settings) != {'identity', 'known_hosts', 'destination'} or not settings['destination'].startswith('canary-config@'):
        raise RuntimeError('invalid_operator_connection')
    if args.command == 'watch':
        return watch(str(uuid.UUID(args.operation)), settings, args.after)
    if args.command == 'status':
        result = send({'action': 'config_status', **({'operation_id': str(uuid.UUID(args.operation))} if args.operation else {})}, settings)
    else:
        op = str(uuid.UUID(args.request_id)) if args.request_id else str(uuid.uuid4())
        # Publish recovery context BEFORE any submission, including if SSH loses its reply.
        print(json.dumps({'request_id': op, 'status_command': f'python3 scripts/canary_config.py status --target production --operation {op}'}), flush=True)
        if args.command == 'plan':
            patch = {}
            for value in args.changes:
                key, separator, item = value.partition('=')
                if not separator or key in patch:
                    raise RuntimeError('invalid_setting')
                patch[key] = item
            request = {'action': 'config_plan', 'request_id': op, 'patch': patch}
            if args.bundle:
                if not all((args.manifest, args.signature, args.bundle_sha256)):
                    raise RuntimeError('signed_bundle_required')
                raw = args.bundle.read_bytes()
                if len(raw) > 2 * 1024 * 1024 or args.manifest.stat().st_size > 4096 or args.signature.stat().st_size > 16384:
                    raise RuntimeError('upload_too_large')
                if hashlib.sha256(raw).hexdigest() != args.bundle_sha256:
                    raise RuntimeError('invalid_bundle_digest')
                upload = send({'action': 'config_stage_bundle', 'bundle': base64.b64encode(raw).decode(),
                               'manifest': json.loads(args.manifest.read_text()),
                               'signature': base64.b64encode(args.signature.read_bytes()).decode()}, settings)
                request['bundle_id'] = upload['bundle_id']
        else:
            if not args.plan or not args.expect_plan_sha256:
                parser.error('apply requires plan and expect-plan-sha256; approve this exact plan before invoking')
            request = {'action': 'config_apply', 'request_id': op,
                       'plan_id': args.plan, 'plan_digest': args.expect_plan_sha256}
        result = send(request, settings)
        print(json.dumps(result), flush=True)
        if args.watch or args.command == 'plan':
            return watch(op, settings)
        return 2  # Accepted; inspect/watch the ID for completion.
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Rejected as error:
        print(json.dumps({'code': str(error)}))
        raise SystemExit(3) from None
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        # Errors may include paths or credential-bearing subprocess input; do not print them.
        print(json.dumps({'code': 'client_request_not_confirmed', 'action': 'inspect_the_printed_request_id_before_retry'}))
        raise SystemExit(5) from None
