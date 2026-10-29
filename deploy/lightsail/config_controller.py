#!/usr/bin/env python3
"""Fixed-action configuration controller. Host only; never log exception details."""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BASE = Path('/usr/local/lib/canary')
STATE = Path('/var/lib/canary-config')
ENABLED = Path('/etc/canary/config-enabled')
PUBLIC_HOLD = Path('/var/lib/canary/public-maintenance')
IDENTITY = Path('/etc/canary/keys/age.txt')
BUNDLES = Path('/etc/canary/bundles')
SIGNERS = Path('/etc/canary/config-allowed-signers')
BOOT = Path('/proc/sys/kernel/random/boot_id')
TERMINAL = {'complete', 'plan_ready', 'rejected_busy', 'rejected', 'failed', 'needs_inspection'}
CODES = frozenset('''invalid_request rejected_busy baseline_changed plan_expired authorization_expired
ci_release_active configuration_operation_active maintenance_active config_not_enabled
already_drained drift_detected observation_stale unsupported_setting ssh_only invalid_setting
invalid_environment unsupported_environment_value host_loader_update_required invalid_bundle_digest
candidate_identity_unknown candidate_restarted candidate_not_drained candidate_readiness_timeout
start_limit_hit drain_timeout public_verification_failed resume_failed signature_required signature_invalid
invalid_manifest authorization_used recipient_change_forbidden ops_token_rotation_ssh_only
request_id_conflict plan_not_ready worker_launch_unknown operation_interrupted credential_required
public_maintenance_active configuration_failed upload_too_large invalid_bundle unsafe_permissions
invalid_public_origin host_agent_unavailable request_outcome_unknown'''.split())
PROBE_LOCK = threading.Lock()


def check(condition, code):
    if not condition:
        raise RuntimeError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def identifier(value):
    try:
        check(isinstance(value, str) and str(uuid.UUID(value)) == value, 'invalid_request')
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError('invalid_request') from None
    return value


def release():
    spec = importlib.util.spec_from_file_location('config_release', BASE / 'release.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('configuration_failed')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def initialize():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    check(not STATE.is_symlink() and STATE.stat().st_uid == os.geteuid()
          and not STATE.stat().st_mode & 0o077, 'unsafe_permissions')
    for name in ('operations', 'uploads'):
        (STATE / name).mkdir(mode=0o700, exist_ok=True)


def atomic(path, value):
    release().atomic_write(path, canonical(value))


def read(path, default=None) -> Any:
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            check(os.fstat(stream.fileno()).st_uid == os.geteuid(), 'unsafe_permissions')
            return json.load(stream)
    except FileNotFoundError:
        return default


@contextmanager
def control():
    initialize()
    with (STATE / 'control.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def folder(op):
    return STATE / 'operations' / identifier(op)


@contextmanager
def database(op):
    db = sqlite3.connect(folder(op) / 'events.sqlite', timeout=2)
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
    try:
        yield db
        db.commit()
    finally:
        db.close()


def record(op, phase, kind='result', **evidence):
    # Callers supply only fixed codes and explicitly selected non-secret evidence.
    event = {'phase': phase, 'kind': kind, 'at': time.time(), **evidence}
    with database(op) as db:
        if kind == 'result':
            previous = db.execute('SELECT payload FROM events ORDER BY seq DESC').fetchall()
            intent = next((item for item in (json.loads(row[0]) for row in previous)
                           if item['phase'] == phase and item['kind'] == 'intent'), None)
            if intent:
                event['duration_seconds'] = event['at'] - intent['at']
        db.execute('INSERT INTO events(payload) VALUES(?)', (canonical(event).decode(),))
        seq = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    print(canonical({'operation_id': op, 'seq': seq, **event}).decode(), file=sys.stderr, flush=True)
    return {'seq': seq, **event}


def events(op, after=0):
    check(type(after) is int and after >= 0, 'invalid_request')
    check((folder(op) / 'events.sqlite').is_file(), 'invalid_request')
    with database(op) as db:
        rows = db.execute('SELECT seq,payload FROM events WHERE seq>? ORDER BY seq LIMIT 100', (after,)).fetchall()
    return {'events': [{'seq': seq, **json.loads(value)} for seq, value in rows],
            'after': rows[-1][0] if rows else after}


def operation(op):
    request = read(folder(op) / 'request.json')
    check(request is not None, 'invalid_request')
    with database(op) as db:
        row = db.execute('SELECT seq,payload FROM events ORDER BY seq DESC LIMIT 1').fetchone()
    last = {'seq': row[0], **json.loads(row[1])} if row else {'phase': 'accepted'}
    return {'request_id': op, 'transport': request['transport'], 'actor': request['actor'], **last,
            'plan': read(folder(op) / 'plan.json'), 'receipt': read(folder(op) / 'receipt.json')}


def boot_id():
    return BOOT.read_text().strip()


def launch(op, action):
    release().run(['systemd-run', '--unit=canary-config-' + op, '--collect',
                   '--property=UMask=0077', '--property=LimitCORE=0',
                   '--property=RuntimeMaxSec=' + ('90' if action == 'config_plan' else '2400'),
                   '/usr/bin/python3', str(BASE / 'config_controller.py'), '--worker', op], timeout=5)


def active(name):
    op = read(STATE / (name + '.json'))
    if not op:
        return None
    current = operation(op)
    return op if current['phase'] not in TERMINAL else None


def submit(request, transport, actor):
    action = request.get('action')
    allowed = {'action', 'request_id', 'patch', 'bundle_id', 'expected_revision'} if action == 'config_plan' else {'action', 'request_id', 'plan_id', 'plan_digest'}
    check(action in {'config_plan', 'config_apply'} and not set(request) - allowed, 'invalid_request')
    op = identifier(request.get('request_id'))
    if action == 'config_plan':
        check(isinstance(request.get('patch', {}), dict) and len(request.get('patch', {})) <= 32, 'invalid_request')
        if request.get('bundle_id'):
            identifier(request['bundle_id'])
        if 'expected_revision' in request:
            check(isinstance(request['expected_revision'], str) and re.fullmatch('[0-9a-f]{64}', request['expected_revision']), 'invalid_request')
    else:
        identifier(request.get('plan_id'))
        check(re.fullmatch('[0-9a-f]{64}', request.get('plan_digest', '')), 'invalid_request')
    stored = {**request, 'transport': transport, 'actor': actor}
    with control():
        existing = read(folder(op) / 'request.json')
        if existing:
            check(existing == stored, 'request_id_conflict')
            return operation(op)
        check(not active('preview' if action == 'config_plan' else 'applying'), 'rejected_busy')
        folder(op).mkdir(mode=0o700)
        atomic(folder(op) / 'request.json', stored)
        atomic(folder(op) / 'boot.json', boot_id())
        record(op, 'accepted')
        atomic(STATE / ('preview.json' if action == 'config_plan' else 'applying.json'), op)
        atomic(STATE / 'latest.json', op)
    try:
        launch(op, action)
    except Exception:
        # Launch could have succeeded. Do not submit another worker on uncertainty.
        with (folder(op) / 'worker.lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass  # Worker is running; its journal is authoritative.
            else:
                if operation(op)['phase'] == 'accepted':
                    record(op, 'launch_unconfirmed', error='worker_launch_unknown')
    return operation(op)


def schema():
    return read(BASE / 'config_schema.json')


def config_snapshot():
    r = release()
    raw = r.private_read(r.CONFIG)
    config = r.parse_environment(raw)
    r.serialize_environment(config)
    files = ('release.py', 'config_controller.py', 'config_schema.json', 'verify_config_runtime.py', 'compose.yaml',
             'canary_secrets.py', 'verify_deployment.py')
    hashes = {name: digest((BASE / name).read_bytes()) for name in files}
    return config, digest(canonical({'config': digest(raw), 'files': hashes}))


def validate_patch(config, patch, transport):
    definitions = schema()
    check(isinstance(patch, dict), 'invalid_request')
    candidate = dict(config)
    for key, value in patch.items():
        check(key in definitions, 'unsupported_setting')
        rule = definitions[key]
        check(transport == 'ssh' or rule['backoffice'] == 'editable', 'ssh_only')
        check(isinstance(value, str) and rule.get('min_length', 0) <= len(value) <= 4096, 'invalid_setting')
        if rule['type'] == 'boolean':
            check(value in {'true', 'false'}, 'invalid_setting')
        elif rule['type'] == 'fraction':
            check(re.fullmatch(r'(?:0(?:\.\d+)?|1(?:\.0+)?)', value), 'invalid_setting')
        elif rule['type'] == 'url':
            check(value.startswith('https://') and len(value) > 8, 'invalid_setting')
        if value != config.get(key, rule.get('default', '')):
            candidate[key] = value
    release().serialize_environment(candidate)
    return candidate


def loader_context(config):
    r = release()
    check(digest((BASE / 'canary_secrets.py').read_bytes()) == config['CANARY_LOADER_SHA256'], 'host_loader_update_required')
    loader = r.load_module('config_secrets', BASE / 'canary_secrets.py')
    bundle = loader.decrypt(Path(config['CANARY_BUNDLE_PATH']), IDENTITY, config['CANARY_BUNDLE_SHA256'])
    return loader, bundle


def manifest_check(manifest, config, ciphertext_digest):
    check(isinstance(manifest, dict) and set(manifest) == {
        'target', 'bundle_sha256', 'replaces_bundle_sha256', 'authorization_id', 'expires_at',
        'recovery_verification'}, 'invalid_manifest')
    identifier(manifest['authorization_id'])
    check(manifest['target'] == 'production' and manifest['bundle_sha256'] == ciphertext_digest
          and manifest['replaces_bundle_sha256'] == config['CANARY_BUNDLE_SHA256']
          and manifest['recovery_verification'] is True, 'invalid_manifest')
    check(type(manifest['expires_at']) in {int, float} and time.time() < manifest['expires_at'], 'authorization_expired')


def signed_bundle(bundle_id, config):
    upload = STATE / 'uploads' / identifier(bundle_id)
    manifest = read(upload / 'manifest.json')
    raw = (upload / 'bundle.sops.json').read_bytes()
    manifest_check(manifest, config, digest(raw))
    signature = upload / 'signature'
    try:
        release().run(['ssh-keygen', '-Y', 'verify', '-f', str(SIGNERS), '-I', 'canary-config',
                       '-n', 'canary-production-config', '-s', str(signature)], data=canonical(manifest), timeout=5)
    except subprocess.SubprocessError:
        raise RuntimeError('signature_invalid') from None
    return upload, manifest


def preflight(request):
    r = release()
    check(ENABLED.is_file(), 'config_not_enabled')
    r.RUNTIME.mkdir(mode=0o700, exist_ok=True)
    check(not PUBLIC_HOLD.exists(), 'public_maintenance_active')
    r.configuration_conflict()
    check(not r.MAINTENANCE.exists(), 'maintenance_active')
    with control():
        config, baseline = config_snapshot()
    if 'expected_revision' in request:
        check(request['expected_revision'] == baseline, 'baseline_changed')
    candidate = validate_patch(config, request.get('patch', {}), request['transport'])
    check(config.get('SCENEWRIGHT_APP_URL') == 'https://scenewright.ink', 'invalid_public_origin')
    upload = manifest = None
    if request.get('bundle_id'):
        upload, manifest = signed_bundle(request['bundle_id'], config)
    live = observe(config, baseline)
    check(live['match'] == 'match', 'drift_detected')
    loader, old = loader_context(config)
    current = old
    if manifest:
        assert upload is not None
        check(loader.ciphertext_recipients(read(upload / 'bundle.sops.json')) ==
              loader.ciphertext_recipients(read(Path(config['CANARY_BUNDLE_PATH']))), 'recipient_change_forbidden')
        current = loader.decrypt(upload / 'bundle.sops.json', IDENTITY, manifest['bundle_sha256'])
        check(request['transport'] == 'ssh' or old['env']['CANARY_OPS_TOKEN'] == current['env']['CANARY_OPS_TOKEN'],
              'ops_token_rotation_ssh_only')
        candidate.update(CANARY_BUNDLE_SHA256=manifest['bundle_sha256'],
                         CANARY_BUNDLE_PATH=str(BUNDLES / (manifest['bundle_sha256'] + '.sops.json')))
    # Only verify policy in memory. ExecStartPre is the only materializer.
    loader.require_tmpfs(r.RUNTIME)
    loader.require_no_swap(False)
    checks = {}
    for key in ('CANARY_RUNWARE_FIRST_ENABLED', 'CANARY_RUNWARE_TEXT_FALLBACK_ENABLED'):
        if candidate.get(key) == 'true':
            check(bool(current['env'].get('RUNWARE_API_KEY')), 'credential_required')
            checks[key + ':RUNWARE_API_KEY'] = 'present'
    if candidate.get('CANARY_TEXTRACT_ENABLED') == 'true':
        check(all(current['env'].get(key) for key in ('CANARY_TEXTRACT_ACCESS_KEY_ID', 'CANARY_TEXTRACT_SECRET_ACCESS_KEY')),
              'credential_required')
        checks['CANARY_TEXTRACT_ENABLED:credentials'] = 'present'
    if candidate.get('VERTEXAI_PROJECT'):
        check(candidate.get('GOOGLE_APPLICATION_CREDENTIALS') == loader.ADC_PATH and
              'google-adc.json' in current['files'], 'credential_required')
        checks['VERTEXAI_PROJECT:google-adc.json'] = 'present'
    r.run(['docker', 'compose', '--env-file', '/dev/null', '--project-name', 'canary',
           '--file', str(BASE / 'compose.yaml'), 'config', '--quiet'], env={**r.SYSTEM_ENV, **candidate}, timeout=15)
    image_hash = r.run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                       '--security-opt', 'no-new-privileges:true', '--entrypoint', 'sha256sum',
                       config['CANARY_IMAGE'], '/app/canary_secrets.py'], timeout=15).decode().split()[0]
    check(image_hash == config['CANARY_LOADER_SHA256'], 'host_loader_update_required')
    token = old['env']['CANARY_OPS_TOKEN']
    activity = r.api('/api/ops/deployment-status', config, token)
    check(activity.get('draining') is False, 'already_drained')
    changes = {key: {'before': config.get(key, schema()[key].get('default', '')),
                     'after': value} for key, value in request.get('patch', {}).items()
               if config.get(key, schema()[key].get('default', '')) != value}
    secret_changes = {}
    for section in ('env', 'files'):
        for name in sorted(old.get(section, {}).keys() | current.get(section, {}).keys()):
            before, after = old.get(section, {}).get(name), current.get(section, {}).get(name)
            if before != after:
                secret_changes[name] = 'added' if before is None else 'removed' if after is None else 'changed'
    with control():
        check(config_snapshot()[1] == baseline, 'baseline_changed')
    return config, candidate, baseline, manifest, changes, secret_changes, checks, activity, live['source_sha']


def make_plan(op, request):
    record(op, 'preflight', 'intent')
    config, candidate, baseline, manifest, changes, secrets, checks, activity, source_sha = preflight(request)
    now = time.time()
    plan = {'plan_id': op, 'baseline': baseline, 'ready_at': now, 'plan_expires_at': now + 1800,
            'authorization_expires_at': manifest['expires_at'] if manifest else None,
            'effective_expires_at': min(now + 1800, manifest['expires_at']) if manifest else now + 1800,
            'image': config['CANARY_IMAGE'], 'source_sha': source_sha, 'bundle_sha256': candidate['CANARY_BUNDLE_SHA256'],
            'changes': changes, 'secret_changes': secrets, 'checks': checks,
            'activity': safe_activity(activity), 'restart_required': candidate != config,
            'recovery_verification': ('operator-recorded recovery verification for ciphertext ' + manifest['bundle_sha256']) if manifest else None}
    plan['digest'] = digest(canonical(plan))
    atomic(folder(op) / 'candidate.json', {'candidate': candidate, 'config': config})
    atomic(folder(op) / 'plan.json', plan)
    record(op, 'preflight', checks=checks)
    record(op, 'plan_ready', checks=checks)


def expiry(plan):
    deadlines = [(plan['plan_expires_at'], 'plan_expired')]
    if plan['authorization_expires_at'] is not None:
        deadlines.append((plan['authorization_expires_at'], 'authorization_expired'))
    deadline, code = min(deadlines, key=lambda item: item[0])
    check(time.time() < deadline, code)


def reserve(manifest, op):
    if not manifest:
        return
    with sqlite3.connect(STATE / 'authorizations.sqlite') as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS used (id TEXT PRIMARY KEY, operation TEXT, expires REAL)')
        try:
            db.execute('INSERT INTO used VALUES(?,?,?)', (manifest['authorization_id'], op, manifest['expires_at']))
        except sqlite3.IntegrityError:
            raise RuntimeError('authorization_used') from None
    directory = os.open(STATE, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def verify_secrets(config, container_id):
    bundle = loader_context(config)[1]
    code = (BASE / 'verify_config_runtime.py').read_text()
    result = release().run(['docker', 'exec', '-i', container_id,
                            '/app/novel_to_comic/.venv/bin/python', '-c', code],
                           data=canonical({**bundle, 'public': {key: config.get(key, rule.get('default', ''))
                                                               for key, rule in schema().items()}}), timeout=10)
    check(json.loads(result) == {'matched': True}, 'drift_detected')


def safe_activity(value):
    counts = value.get('counts', {})
    return {'counts': {k: v for k, v in counts.items() if k in {
        'admitting_requests', 'queued_generation_jobs', 'running_generation_jobs', 'queue_items', 'draw_panels_in_flight'}
        and type(v) is int and v >= 0},
        'preserved_queued_operations': value.get('preserved_queued_operations', 0) if type(value.get('preserved_queued_operations', 0)) is int else 0,
        'draining': value.get('draining') if type(value.get('draining')) is bool else None,
        'safe_to_deploy': value.get('safe_to_deploy') if type(value.get('safe_to_deploy')) is bool else None}


def create_hold(op):
    r = release()
    with r.MAINTENANCE.open('x') as stream:
        info = os.fstat(stream.fileno())
        stream.flush()
        os.fsync(stream.fileno())
    atomic(STATE / 'hold.json', {'operation_id': op, 'device': info.st_dev, 'inode': info.st_ino})


def remove_hold(op):
    r = release()
    owner = read(STATE / 'hold.json', {})
    info = r.MAINTENANCE.stat(follow_symlinks=False)
    check(owner.get('operation_id') == op and (owner.get('device'), owner.get('inode')) == (info.st_dev, info.st_ino),
          'maintenance_active')
    r.MAINTENANCE.unlink()


def apply(op, request):
    r = release()
    plan_op = request['plan_id']
    plan = read(folder(plan_op) / 'plan.json')
    check(plan and plan['digest'] == request['plan_digest'], 'plan_not_ready')
    expiry(plan)
    original = read(folder(plan_op) / 'request.json')
    # Never inherit an SSH plan's privileges through the application socket.
    original.update(transport=request['transport'], actor=request['actor'])
    r.RUNTIME.mkdir(mode=0o700, exist_ok=True)
    with (r.RUNTIME / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            record(op, 'rejected_busy', error='rejected_busy')
            return
        record(op, 'preflight', 'intent')
        config, candidate, baseline, manifest, changes, secrets, checks, _, _source_sha = preflight(original)
        check(baseline == plan['baseline'], 'baseline_changed')
        check(read(folder(plan_op) / 'candidate.json')['candidate'] == candidate, 'baseline_changed')
        expiry(plan)
        before = r.private_read(r.CONFIG)
        record(op, 'preflight', checks=checks)
        resume_attempted = False
        stopping = False
        owns_hold = False
        try:
            if candidate != config:
                reserve(manifest, op)  # After release lock, before hold/drain.
                record(op, 'draining', 'intent', deadline=time.time() + 1800)
                create_hold(op)
                owns_hold = True
                r.drain(config, loader_context(config)[1]['env']['CANARY_OPS_TOKEN'],
                        lambda activity, deadline: record(op, 'draining', activity=safe_activity(activity),
                                                         deadline=time.time() + max(0, deadline - time.monotonic())))
                record(op, 'saving_previous', 'intent')
                r.atomic_write(folder(op) / 'previous.env', before)
                if manifest:
                    BUNDLES.mkdir(mode=0o700, exist_ok=True)
                    path = Path(candidate['CANARY_BUNDLE_PATH'])
                    data = (STATE / 'uploads' / original['bundle_id'] / 'bundle.sops.json').read_bytes()
                    check(digest(data) == manifest['bundle_sha256'], 'invalid_bundle')
                    if path.exists():
                        check(digest(path.read_bytes()) == manifest['bundle_sha256'], 'invalid_bundle')
                    else:
                        loader_context(config)[0].publish_ciphertext(path, data)
                record(op, 'stopping', 'intent')
                stopping = True
                r.run(['systemctl', 'stop', 'canary.service'], timeout=90)
                record(op, 'stopping')
                record(op, 'installing', 'intent')
                with control():
                    r.atomic_write(r.CONFIG, r.serialize_environment(candidate))
                record(op, 'installing')
                record(op, 'starting', 'intent')
                remove_hold(op)
                owns_hold = False
                r.start_candidate()
                pinned = r.pin_candidate()
                record(op, 'starting', container_id=pinned['container_id'])
                token = loader_context(candidate)[1]['env']['CANARY_OPS_TOKEN']
                record(op, 'verifying_local', 'intent')
                version = plan['source_sha']
                r.wait_candidate(candidate, token, version)
                check(r.candidate_identity() == pinned, 'candidate_restarted')
                observed = observe(candidate, config_snapshot()[1])
                check(observed['match'] == 'match', 'drift_detected')
                verify_secrets(candidate, pinned['container_id'])
                record(op, 'verifying_local', checks={'readiness': True, 'configuration': True, 'secret_delivery': True})
                record(op, 'verifying_public', 'intent')
                evidence = r.verify_public(candidate, token, version)
                check(r.candidate_identity() == pinned, 'candidate_restarted')
                record(op, 'verifying_public', checks=evidence)
                record(op, 'resuming', 'intent')
                check(r.candidate_identity() == pinned, 'candidate_restarted')
                resume_attempted = True
                try:
                    r.api('/api/ops/resume', candidate, token, 'POST')
                except OSError:
                    pass  # Reconcile the observed admission; do not repeat resume.
                check(r.api('/api/ops/deployment-status', candidate, token).get('draining') is False, 'resume_failed')
                record(op, 'resuming', admission_open=True)
            with database(op) as db:
                all_events = [json.loads(row[0]) for row in db.execute('SELECT payload FROM events ORDER BY seq')]
            check_results = {item['phase']: item['checks'] for item in all_events if 'checks' in item}
            receipt = {'before_revision': plan['baseline'], 'after_revision': config_snapshot()[1],
                       'image': candidate['CANARY_IMAGE'], 'source_sha': plan_version(candidate),
                       'bundle_sha256': candidate['CANARY_BUNDLE_SHA256'], 'changes': list(changes),
                       'secret_changes': secrets, 'checks': {**checks, **check_results}, 'admission_open': True,
                       'transport': request['transport'], 'actor': request['actor'],
                       'recovery_verification': plan['recovery_verification'], 'completed_at': time.time(),
                       'duration_seconds': time.time() - all_events[0]['at']}
            atomic(folder(op) / 'receipt.json', receipt)
            record(op, 'complete', receipt=receipt)
        except BaseException:
            if resume_attempted:
                record(op, 'needs_inspection', error='request_outcome_unknown')
            else:
                if stopping and not owns_hold and not r.MAINTENANCE.exists():
                    create_hold(op)
                    owns_hold = True
                if stopping:
                    r.run(['systemctl', 'stop', 'canary.service'], timeout=90)
            raise


def plan_version(config, timeout: float = 5):
    rows = json.loads(release().run(['docker', 'image', 'inspect', config['CANARY_IMAGE']], timeout=timeout))
    values = dict(value.split('=', 1) for value in rows[0]['Config'].get('Env', []) if '=' in value)
    version = values.get('CANARY_VERSION', '')
    check(re.fullmatch('[0-9a-f]{40}', version), 'drift_detected')
    return version


def observe(config, baseline):
    r = release()
    deadline = time.monotonic() + 10
    def remaining():
        check(time.monotonic() < deadline, 'observation_stale')
        return max(0.01, deadline - time.monotonic())
    pinned = r.candidate_identity(timeout=remaining())
    inspected = json.loads(r.run(['docker', 'inspect', pinned['container_id']], timeout=remaining()))[0]
    values = dict(value.split('=', 1) for value in inspected['Config']['Env'] if '=' in value)
    matches = inspected['Config']['Image'] == config['CANARY_IMAGE']
    definitions = schema()
    matches = matches and all(values.get(key) == config.get(key, rule.get('default', '')) for key, rule in definitions.items())
    matches = matches and values.get('CANARY_LOADER_SHA256') == config['CANARY_LOADER_SHA256']
    mounts = inspected.get('Mounts', [])
    matches = matches and any(m['Destination'] == '/run/secrets/runtime.json' and
                             m['Source'] == '/run/canary/secrets/' + config['CANARY_BUNDLE_SHA256'] + '/runtime.json' for m in mounts)
    request = urllib.request.Request('http://127.0.0.1:8000/api/version', headers={'Host': config['CANARY_HEALTH_HOST']})
    with urllib.request.urlopen(request, timeout=remaining()) as response:
        version = json.load(response)
    matches = matches and version.get('git_sha') == plan_version(config, timeout=remaining())
    remaining()
    return {'observed_at': time.time(), 'revision': baseline, 'match': 'match' if matches else 'drift',
            'source_sha': version.get('git_sha'), 'container_id': pinned['container_id']}


def probe():
    if not PROBE_LOCK.acquire(blocking=False):
        return
    stream = None
    try:
        stream = (STATE / 'probe.lock').open('a')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        previous = read(STATE / 'observation.json', {})
        if time.time() - previous.get('checked_at', 0) < 15:
            return
        try:
            config, revision = config_snapshot()
            observation = observe(config, revision)
            observation['checked_at'] = time.time()
        except Exception:
            observation = {**previous, 'checked_at': time.time(), 'match': 'unknown'}
        atomic(STATE / 'observation.json', observation)
        # Reconcile dead operations without retrying their side effects.
        for name in ('preview', 'applying'):
            op = active(name)
            if op:
                try:
                    state = release().run(['systemctl', 'show', 'canary-config-' + op, '--property=ActiveState', '--value'], timeout=2).strip()
                    if state in {b'inactive', b'failed'} or read(folder(op) / 'boot.json') != boot_id():
                        record(op, 'needs_inspection', error='operation_interrupted')
                except Exception:
                    pass
    finally:
        if stream:
            stream.close()
        PROBE_LOCK.release()


def status(op=None, *, background=True):
    initialize()
    # Probe has its own slot; callers never wait for Docker or systemd.
    if background:
        threading.Thread(target=probe, daemon=True).start()
    config, revision = config_snapshot()
    observation = read(STATE / 'observation.json', {'match': 'unknown'})
    observation['stale'] = time.time() - observation.get('observed_at', 0) > 30 or observation.get('revision') != revision or observation['match'] == 'unknown'
    definitions = schema()
    bundle = read(Path(config['CANARY_BUNDLE_PATH']), {})
    latest = op or read(STATE / 'latest.json')
    return {'checked_at': time.time(), 'revision': revision, 'image': config['CANARY_IMAGE'],
            'bundle_sha256': config['CANARY_BUNDLE_SHA256'], 'loader_sha256': config['CANARY_LOADER_SHA256'],
            'observation': observation, 'schema': definitions,
            'values': {key: config.get(key, rule.get('default', '')) for key, rule in definitions.items()},
            'secret_names': sorted(bundle.get('env', {}).keys()),
            'operation': operation(latest) if latest else None, 'maintenance_hold': release().MAINTENANCE.exists()}


def stage_bundle(request):
    check(set(request) == {'action', 'bundle', 'manifest', 'signature'}, 'invalid_request')
    manifest = request['manifest']
    check(len(canonical(manifest)) <= 4096, 'upload_too_large')
    raw = base64.b64decode(request['bundle'], validate=True)
    signature = base64.b64decode(request['signature'], validate=True)
    check(len(raw) <= 2 * 1024 * 1024 and len(signature) <= 16384, 'upload_too_large')
    config, _ = config_snapshot()
    manifest_check(manifest, config, digest(raw))
    with control():
        check(len(list((STATE / 'uploads').iterdir())) < 32, 'rejected_busy')
        upload_id = str(uuid.uuid4())
        upload = STATE / 'uploads' / upload_id
        upload.mkdir(mode=0o700)
    r = release()
    try:
        r.atomic_write(upload / 'bundle.sops.json', raw)
        r.atomic_write(upload / 'signature', signature)
        atomic(upload / 'manifest.json', manifest)
        signed_bundle(upload_id, config)
    except BaseException:
        for path in upload.iterdir():
            path.unlink()
        upload.rmdir()
        raise
    return {'bundle_id': upload_id}


def export_encrypted_configuration():
    """Operator SSH only. Never export decrypted values or arbitrary host files."""
    with control():
        config, revision = config_snapshot()
        with os.fdopen(os.open(config['CANARY_BUNDLE_PATH'], os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            info = os.fstat(stream.fileno())
            check(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077, 'unsafe_permissions')
            raw = stream.read(2 * 1024 * 1024 + 1)
        check(len(raw) <= 2 * 1024 * 1024, 'upload_too_large')
        check(digest(raw) == config['CANARY_BUNDLE_SHA256'], 'invalid_bundle_digest')
        stored = json.loads(raw)
        check(digest((BASE / 'canary_secrets.py').read_bytes()) == config['CANARY_LOADER_SHA256'], 'host_loader_update_required')
        loader = release().load_module('export_schema_loader', BASE / 'canary_secrets.py')
        loader.ciphertext_recipients(stored)
        definitions = schema()
        return {'revision': revision, 'bundle_sha256': config['CANARY_BUNDLE_SHA256'],
                'loader_sha256': config['CANARY_LOADER_SHA256'],
                'ciphertext': base64.b64encode(raw).decode(), 'schema': definitions,
                'host_recipient': release().run([loader.trusted_tool('age-keygen'), '-y', str(IDENTITY)], timeout=5).decode().strip(),
                'values': {key: config.get(key, rule.get('default', '')) for key, rule in definitions.items()},
                'secret_schema': {'allowed': sorted(loader.ALLOWED), 'required': sorted(loader.REQUIRED),
                                  'mirrored': dict(loader.MIRRORED)}}


def handle(request, transport='backoffice', actor='ops_token', *, background=True):
    initialize()
    check(isinstance(request, dict), 'invalid_request')
    action = request.get('action')
    if action == 'config_export':
        check(transport == 'ssh', 'ssh_only')
        check(set(request) == {'action'}, 'invalid_request')
        return export_encrypted_configuration()
    if action in {'config_plan', 'config_apply'}:
        return submit(request, transport, actor)
    if action == 'config_status':
        check(not set(request) - {'action', 'operation_id'}, 'invalid_request')
        return status(request.get('operation_id'), background=background)
    if action == 'config_events':
        check(set(request) == {'action', 'operation_id', 'after'}, 'invalid_request')
        return events(request['operation_id'], request['after'])
    if action == 'config_stage_bundle':
        return stage_bundle(request)
    raise RuntimeError('invalid_request')


def worker(op):
    request = read(folder(op) / 'request.json')
    check(request is not None, 'invalid_request')
    # A fixed UUID systemd unit and this per-operation lock prohibit re-execution.
    with (folder(op) / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        check(operation(op)['phase'] in {'accepted', 'launch_unconfirmed'}, 'invalid_request')
        try:
            (make_plan if request['action'] == 'config_plan' else apply)(op, request)
        except BaseException as error:
            current = operation(op)
            if current['phase'] != 'needs_inspection':
                code = str(error) if isinstance(error, RuntimeError) and str(error) in CODES else 'configuration_failed'
                preflight_rejection = current['phase'] == 'accepted' or (current['phase'] == 'preflight' and current.get('kind') == 'intent') or code == 'authorization_used'
                phase = 'rejected_busy' if isinstance(error, BlockingIOError) else 'rejected' if preflight_rejection else 'failed'
                record(op, phase, error=code)
            final = operation(op)
            atomic(folder(op) / 'receipt.json', {
                'phase': final['phase'], 'failed_phase': current['phase'],
                'error': final.get('error', 'configuration_failed'),
                'hold_present': release().MAINTENANCE.exists(),
                'running_observation': read(STATE / 'observation.json', {'match': 'unknown'}),
                'admission': 'unknown', 'transport': request['transport'], 'actor': request['actor'],
                'next_action': 'Inspect this operation and systemd over operator SSH before recovery; do not repeat an uncertain apply.',
            })


def main():
    os.umask(0o077)
    check(os.geteuid() == 0, 'unsafe_permissions')
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker')
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError()))
    initialize()
    if args.probe:
        probe()
    elif args.worker:
        worker(identifier(args.worker))
    else:
        # Install this exact no-argument invocation as the operator forced command.
        check(not os.environ.get('SSH_ORIGINAL_COMMAND'), 'invalid_request')
        raw = sys.stdin.buffer.read(3 * 1024 * 1024 + 1)
        check(len(raw) <= 3 * 1024 * 1024, 'upload_too_large')
        request = json.loads(raw)
        if isinstance(request, dict) and request.get('action') == 'config_status':
            # The forced-command process exits after its reply. A daemon thread
            # would die with it, so let systemd own this bounded background probe.
            try:
                release().run(['systemd-run', '--unit=canary-config-probe', '--collect',
                               '--property=RuntimeMaxSec=15', '--property=UMask=0077',
                               '--property=LimitCORE=0', '/usr/bin/python3',
                               str(BASE / 'config_controller.py'), '--probe'], timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass  # Existing probe or unavailable host observation stays explicit in the cache.
        print(json.dumps({'ok': True, 'result': handle(request, 'ssh', 'operator_ssh', background=False)}))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        code = str(error) if isinstance(error, RuntimeError) and str(error) in CODES else 'configuration_failed'
        print(json.dumps({'ok': False, 'code': code}))
        raise SystemExit(1) from None
