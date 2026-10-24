"""Provider-free host maintenance safety, API authorization, and transport checks."""
import importlib.util
import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.server import host_maintenance
from novel_to_comic.server.routers import backoffice


@pytest.fixture
def host(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'deploy/lightsail/host_agent.py'
    spec = importlib.util.spec_from_file_location('host_agent_test', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, 'STATE', tmp_path)
    monkeypatch.setattr(m, 'HOLD', tmp_path / 'maintenance')
    monkeypatch.setattr(m, 'BOOT_ID', tmp_path / 'boot-id')
    m.BOOT_ID.write_text('current-boot')
    monkeypatch.setattr(m, 'RECOVERY_ENABLED', tmp_path / 'recovery-enabled')
    runtime = tmp_path / 'release'
    events = []

    def run(args, **kwargs):
        events.append(args)
        return ''

    release = SimpleNamespace(
        RUNTIME=runtime, re=__import__('re'), SYSTEM_ENV={},
        api=lambda *args: {'git_sha': 'a' * 40, 'draining': False},
        drain=lambda *args: events.append(['drain']),
        wait_candidate=lambda *args: events.append(['ready']),
        run=run,
    )
    monkeypatch.setattr(m, 'run', run)
    monkeypatch.setattr(m, 'release_module', lambda: release)
    monkeypatch.setattr(m, 'context', lambda _: ({'SCENEWRIGHT_APP_URL': 'https://scenewright.ink'}, 'secret'))
    monkeypatch.setattr(m, 'simulation', lambda: {'digest': 'b' * 64, 'packages': ['Inst openssl [old] (new)']})
    return m, events, release


def request(action, **kwargs):
    return {'action': action, 'request_id': str(uuid.uuid4()), **kwargs}


def test_preview_does_not_drain_or_stop(host):
    m, events, _ = host
    m.submit(request('check'))
    m.worker()
    assert m.read('operation.json')['phase'] == 'complete'
    assert m.read('plan.json')['digest'] == 'b' * 64
    assert not m.HOLD.exists()
    assert not any('stop' in args or 'drain' in args for args in events)


def test_update_drains_stops_updates_and_verifies_before_resume(host):
    m, events, _ = host
    m.write('plan.json', {**m.simulation(), 'checked_at': m.time.time()})
    m.submit(request('update', plan_digest='b' * 64))
    m.worker()
    drain = events.index(['drain'])
    stop = events.index(['systemctl', 'stop', 'canary.service'])
    upgrade = next(i for i, args in enumerate(events) if '-y' in args)
    restart = events.index(['systemctl', 'restart', 'docker.service', 'nginx.service'])
    ready = events.index(['ready'])
    resume = next(i for i, args in enumerate(events) if '--resume' in args)
    assert drain < stop < upgrade < restart < ready < resume
    assert m.read('operation.json')['phase'] == 'complete'
    assert not m.HOLD.exists()


def test_changed_preview_refuses_spend_and_outage(host, monkeypatch):
    m, events, _ = host
    m.write('plan.json', {**m.simulation(), 'checked_at': m.time.time()})
    m.submit(request('update', plan_digest='b' * 64))
    monkeypatch.setattr(m, 'simulation', lambda: {'digest': 'c' * 64, 'packages': ['Inst other']})
    with pytest.raises(RuntimeError, match='updates_changed'):
        m.worker()
    assert m.read('operation.json')['error'] == 'updates_changed_review_new_preview'
    assert ['drain'] not in events
    assert not m.HOLD.exists()


@pytest.mark.parametrize('failure', ['drain', 'upgrade', 'ready', 'resume'])
def test_failure_keeps_maintenance_closed(host, monkeypatch, failure):
    m, events, release = host
    m.write('plan.json', {**m.simulation(), 'checked_at': m.time.time()})
    m.submit(request('update', plan_digest='b' * 64))
    original = m.run

    def fail(*args):
        raise RuntimeError('injected_failure')

    def run(args, **kwargs):
        if (failure == 'upgrade' and '-y' in args) or (failure == 'resume' and '--resume' in args):
            raise subprocess.CalledProcessError(1, args, output='sensitive')
        return original(args, **kwargs)

    monkeypatch.setattr(m, 'run', run)
    release.run = run
    if failure == 'drain':
        release.drain = fail
    if failure == 'ready':
        release.wait_candidate = fail
    with pytest.raises((RuntimeError, subprocess.SubprocessError)):
        m.worker()
    assert m.HOLD.exists()
    assert m.read('operation.json')['phase'] == 'failed'
    assert 'sensitive' not in json.dumps(m.read('operation.json'))
    if failure == 'drain':
        assert ['systemctl', 'stop', 'canary.service'] not in events
    else:
        assert events[-1] == ['systemctl', 'stop', 'canary.service']


def test_admission_is_idempotent_and_serialized(host):
    m, events, _ = host
    body = request('check')
    first = m.submit(body)
    assert m.submit(body) == first
    assert len(events) == 1
    with pytest.raises(RuntimeError, match='already_running'):
        m.submit(request('check'))


def test_shared_release_lock_blocks_maintenance(host):
    m, events, release = host
    m.submit(request('check'))
    release.RUNTIME.mkdir()
    with m.lock(release.RUNTIME / 'worker.lock'), pytest.raises(BlockingIOError):
        m.worker()
    assert ['drain'] not in events
    assert not m.HOLD.exists()
    assert m.read('operation.json')['phase'] == 'failed'
    assert m.read('operation.json')['error'] == 'deployment_in_progress_try_again_after_release'


def test_hold_and_stale_plan_refused(host):
    m, _, _ = host
    m.HOLD.touch()
    with pytest.raises(RuntimeError, match='existing_maintenance'):
        m.submit(request('reboot'))
    m.HOLD.unlink()
    m.write('plan.json', {**m.simulation(), 'checked_at': 0})
    with pytest.raises(RuntimeError, match='refresh_update_preview'):
        m.submit(request('update', plan_digest='b' * 64))


def test_recovery_only_after_requested_reboot_on_new_boot(host, monkeypatch):
    m, events, _ = host
    m.write('operation.json', {'phase': 'rebooting', 'action': 'reboot', 'version': 'a' * 40, 'boot_id': 'previous'})
    m.HOLD.touch()
    m.worker(recover=True)
    assert m.read('operation.json')['phase'] == 'complete'
    assert any('--resume' in args for args in events)
    assert not m.HOLD.exists()
    events.clear()
    m.worker(recover=True)
    assert not events


def test_reboot_requires_enabled_recovery_before_reboot(host):
    m, events, _ = host
    m.submit(request('reboot'))
    with pytest.raises(RuntimeError, match='boot_recovery_not_enabled'):
        m.worker()
    assert ['systemctl', 'reboot'] not in events
    assert not m.HOLD.exists()
    assert ['drain'] not in events


def test_api_requires_ops_token_and_rejects_arbitrary_actions(monkeypatch):
    monkeypatch.setenv('CANARY_OPS_TOKEN', 'operator')
    calls = []
    monkeypatch.setattr(host_maintenance, 'host_request', lambda value: calls.append(value) or {'ok': True})
    app = FastAPI()
    app.include_router(backoffice.router, prefix='/ops')
    with TestClient(app) as client:
        assert client.get('/ops/host').status_code == 401
        assert client.post('/ops/host', json=request('reboot')).status_code == 401
        assert not calls
        headers = {'X-Canary-Ops-Token': 'operator'}
        assert client.get('/ops/host', headers=headers).status_code == 200
        assert client.post('/ops/host', headers=headers, json=request('shell')).status_code == 422
        assert client.post('/ops/host', headers=headers, json={**request('check'), 'command': 'id'}).status_code == 422
        assert client.post('/ops/host', headers=headers, json=request('check')).status_code == 202
        assert calls == [{'action': 'status'}, calls[-1]]
        assert calls[-1]['action'] == 'check'


def test_uninstalled_agent_returns_actionable_unavailable(monkeypatch):
    monkeypatch.setattr(host_maintenance, 'SOCKET_PATH', '/nonexistent-canary-test-socket')
    with pytest.raises(Exception) as caught:
        host_maintenance.host_request({'action': 'status'})
    assert caught.value.status_code == 503
    assert 'private socket mount' in caught.value.detail


def test_failed_verification_keeps_release_lock_until_owner_is_stopped(host, monkeypatch):
    m, events, release = host
    m.write('plan.json', {**m.simulation(), 'checked_at': m.time.time()})
    m.submit(request('update', plan_digest='b' * 64))
    original = m.run
    verification_started = False
    cleanup_checked = False

    def ready(*args):
        nonlocal verification_started
        verification_started = True
        raise RuntimeError('failed_readiness')

    def run(args, **kwargs):
        nonlocal cleanup_checked
        if verification_started and args == ['systemctl', 'stop', 'canary.service']:
            assert m.HOLD.exists()
            with pytest.raises(BlockingIOError), m.lock(release.RUNTIME / 'worker.lock'):
                pytest.fail('Concurrent deployment acquired lock during failure cleanup')
            cleanup_checked = True
        return original(args, **kwargs)

    release.wait_candidate = ready
    monkeypatch.setattr(m, 'run', run)
    with pytest.raises(RuntimeError, match='failed_readiness'):
        m.worker()
    assert cleanup_checked
    with m.lock(release.RUNTIME / 'worker.lock'):
        assert m.HOLD.exists()


def test_requested_reboot_records_boot_before_submission_and_waits_for_next_boot(host):
    m, events, _ = host
    m.RECOVERY_ENABLED.touch()
    m.submit(request('reboot'))
    m.worker()
    record = m.read('operation.json')
    assert record['phase'] == 'rebooting'
    assert record['version'] == 'a' * 40
    assert record['boot_id'] == 'current-boot'
    assert events[-1] == ['systemctl', 'reboot']
    events.clear()
    m.worker(recover=True)
    assert not events
    assert m.HOLD.exists()
    m.BOOT_ID.write_text('next-boot')
    m.worker(recover=True)
    assert m.read('operation.json')['phase'] == 'complete'
    assert not m.HOLD.exists()
