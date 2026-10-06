"""Provider-free release transaction and CI firewall lifecycle regressions."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(relative):
    spec = importlib.util.spec_from_file_location('release_test', ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def host(tmp_path, monkeypatch):
    m = load('deploy/lightsail/release.py')
    for name, filename in [('BASE', 'lib'), ('CONFIG', 'deployment.env'),
                           ('MAINTENANCE', 'maintenance'), ('ENABLED', 'ci-enabled'), ('RUNTIME', 'run')]:
        monkeypatch.setattr(m, name, tmp_path / filename)
    m.BASE.mkdir()
    m.RUNTIME.mkdir()
    m.ENABLED.touch()
    loader = b'reviewed loader'
    (m.BASE / 'canary_secrets.py').write_bytes(loader)
    digest = hashlib.sha256(loader).hexdigest()
    config = {'CANARY_IMAGE': 'previous@sha256:' + '0' * 64, 'CANARY_LOADER_SHA256': digest,
              'CANARY_BUNDLE_SHA256': 'b' * 64, 'CANARY_BUNDLE_PATH': '/safe/bundle',
              'SCENEWRIGHT_APP_URL': 'https://scenewright.ink', 'CANARY_HEALTH_HOST': 'scenewright.ink'}
    m.CONFIG.write_text('\n'.join(f'{k}={v}' for k, v in config.items()) + '\n')
    monkeypatch.setattr(m, 'private_read', lambda path: path.read_bytes())
    monkeypatch.setattr(m, 'load_module', lambda *args: SimpleNamespace(
        decrypt=lambda *args: {'env': {'CANARY_OPS_TOKEN': 'test-only'}},
        require_tmpfs=lambda *args: None, require_no_swap=lambda *args: None))
    monkeypatch.setattr(m.shutil, 'disk_usage', lambda path: SimpleNamespace(free=10 * 1024 ** 3))
    request = {'image': m.REPOSITORY + '@sha256:' + 'a' * 64, 'version': 'c' * 40,
               'loader_sha256': digest, 'pull_token': 'short-lived-test-token'}
    events = []
    state = {'verified': False, 'fail': None, 'bad_version': False}

    def run(argv, **kwargs):
        events.append(tuple(argv))
        if state['fail'] and state['fail'](argv):
            raise RuntimeError('simulated_failure')
        if argv[:3] == ['docker', 'image', 'inspect']:
            version = 'bad' if state['bad_version'] else request['version']
            return json.dumps([{'Config': {'Env': ['CANARY_VERSION=' + version]}}]).encode()
        if argv[:2] == ['docker', 'run']:
            return (digest + '  /app/canary_secrets.py\n').encode()
        if '--resume' in argv:
            state['verified'] = True
        return b''

    def api(path, config, token=None, method='GET'):
        events.append((method, path))
        if path == '/api/ops/deployment-status':
            return {'draining': not state['verified'], 'safe_to_deploy': True}
        if path == '/api/version':
            return {'git_sha': request['version']}
        return {'status': 'ok'}

    monkeypatch.setattr(m, 'run', run)
    monkeypatch.setattr(m, 'api', api)
    return m, request, events, state


@pytest.mark.parametrize('field,value', [('image', 'registry.depot.dev/js338b6zll:latest'),
                                       ('image', 'evil.example/app@sha256:' + 'a' * 64),
                                       ('version', 'main; touch /tmp/pwn'),
                                       ('pull_token', 'token\ncommand'), ('loader_sha256', 'bad')])
def test_reject_unpinned_or_injected_request(host, field, value):
    m, request, _, _ = host
    with pytest.raises(RuntimeError):
        m.validate_request({**request, field: value})


@pytest.mark.parametrize('gate', ['maintenance', 'not_enabled', 'loader', 'image'])
def test_bad_candidate_leaves_live_release_untouched(host, gate):
    m, request, events, state = host
    old = m.CONFIG.read_bytes()
    if gate == 'maintenance':
        m.MAINTENANCE.touch()
    elif gate == 'not_enabled':
        m.ENABLED.unlink()
    elif gate == 'loader':
        request['loader_sha256'] = 'f' * 64
    else:
        state['bad_version'] = True
    with pytest.raises(RuntimeError):
        m.activate(request)
    assert m.CONFIG.read_bytes() == old
    assert ('POST', '/api/ops/drain') not in events
    assert ('systemctl', 'stop', 'canary.service') not in events


def test_successful_release_orders_drain_replace_verify_resume(host):
    m, request, events, _ = host
    old = m.CONFIG.read_bytes()
    m.activate(request)
    pull = next(i for i, e in enumerate(events) if e[:2] == ('docker', 'pull'))
    drain = events.index(('POST', '/api/ops/drain'))
    stop = events.index(('systemctl', 'stop', 'canary.service'))
    start = events.index(('systemctl', 'start', 'canary.service'))
    verify = next(i for i, e in enumerate(events) if '--resume' in e)
    assert pull < drain < stop < start < verify
    assert m.parse_environment(m.CONFIG.read_bytes())['CANARY_IMAGE'] == request['image']
    assert next((m.CONFIG.parent / 'releases').glob('*.env')).read_bytes() == old
    assert not m.MAINTENANCE.exists()
    assert not list(m.RUNTIME.glob('registry-*'))


def test_failed_drain_never_stops_old_process(host, monkeypatch):
    m, request, events, _ = host
    def fail(*args):
        raise RuntimeError('drain_failed')
    monkeypatch.setattr(m, 'drain', fail)
    with pytest.raises(RuntimeError):
        m.activate(request)
    assert ('systemctl', 'stop', 'canary.service') not in events
    assert not any('--resume' in e for e in events)


def test_low_disk_fails_before_pull_or_drain(host, monkeypatch):
    m, request, events, _ = host
    monkeypatch.setattr(m.shutil, 'disk_usage', lambda path: SimpleNamespace(free=1024))
    with pytest.raises(RuntimeError, match='insufficient_image_disk_space'):
        m.activate(request)
    assert not any(e[:2] == ('docker', 'pull') for e in events)
    assert ('POST', '/api/ops/drain') not in events


@pytest.mark.parametrize('failure', ['start', 'verify'])
def test_failed_replacement_is_stopped_and_held_for_operator(host, failure):
    m, request, events, state = host
    state['fail'] = lambda argv: ('--resume' in argv if failure == 'verify' else
                                 argv == ['systemctl', 'start', 'canary.service'])
    with pytest.raises(RuntimeError):
        m.activate(request)
    assert m.MAINTENANCE.exists()
    assert events[-1] == ('systemctl', 'stop', 'canary.service')
    assert not state['verified']
    assert len(list((m.CONFIG.parent / 'releases').glob('*.env'))) == 1


def test_dispatch_runs_detached_from_ssh_under_systemd(host, monkeypatch):
    m, request, events, _ = host
    monkeypatch.setattr(m.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())))
    monkeypatch.delenv('SSH_ORIGINAL_COMMAND', raising=False)
    m.dispatch()
    command = events[0]
    assert command[0] == 'systemd-run' and '--wait' in command and '--collect' in command
    assert '--pipe' not in command
    assert not list(m.RUNTIME.glob('request-*'))


@pytest.mark.parametrize('fail_at', [None, 'ssh', 'open-instance-public-ports'])
def test_ci_removes_only_its_temporary_ssh_rule(fail_at):
    m = load('scripts/deploy_lightsail.py')
    events = []
    env = dict(LIGHTSAIL_HOST='52.203.15.28', LIGHTSAIL_SSH_KNOWN_HOSTS='pinned-key',
               LIGHTSAIL_SSH_PRIVATE_KEY='test-key', CANARY_RELEASE_IMAGE='image',
               CANARY_RELEASE_VERSION='version', CANARY_LOADER_SHA256='loader')
    def run(argv, **kwargs):
        events.append(argv)
        if fail_at and fail_at in argv:
            raise RuntimeError('simulated transport failure')
        if 'get-instance-port-states' in argv:
            return SimpleNamespace(stdout=b'{"portStates": []}')
        if argv[0] == 'ssh':
            assert 'StrictHostKeyChecking=yes' in argv
            request = json.loads(kwargs['input'])
            assert request['pull_token'] == 'read-only-token'
            return SimpleNamespace(stdout=b'release_verified_and_resumed\n')
        return SimpleNamespace(stdout=b'read-only-token')
    if fail_at:
        with pytest.raises(RuntimeError):
            m.deploy(env, run, lambda: '8.8.4.4')
    else:
        m.deploy(env, run, lambda: '8.8.4.4')
    assert 'close-instance-public-ports' in events[-1]
    rule = json.loads(events[-1][-1])
    assert rule == {'fromPort': 22, 'toPort': 22, 'protocol': 'tcp', 'cidrs': ['8.8.4.4/32']}


def test_ci_preserves_preexisting_operator_rule():
    m = load('scripts/deploy_lightsail.py')
    events = []
    env = dict(LIGHTSAIL_HOST='52.203.15.28', LIGHTSAIL_SSH_KNOWN_HOSTS='pinned-key',
               LIGHTSAIL_SSH_PRIVATE_KEY='test-key', CANARY_RELEASE_IMAGE='image',
               CANARY_RELEASE_VERSION='version', CANARY_LOADER_SHA256='loader')
    def run(argv, **kwargs):
        events.append(argv)
        if 'get-instance-port-states' in argv:
            rule = {'fromPort': 22, 'toPort': 22, 'protocol': 'tcp', 'cidrs': ['8.8.4.4/32']}
            return SimpleNamespace(stdout=json.dumps({'portStates': [rule]}).encode())
        return SimpleNamespace(stdout=b'release_verified_and_resumed' if argv[0] == 'ssh' else b'token')
    m.deploy(env, run, lambda: '8.8.4.4')
    assert not any('open-instance-public-ports' in e or 'close-instance-public-ports' in e for e in events)
