"""Local-only watchdog exercise: no provider or notification traffic."""
import importlib.util
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location('operations_monitor', Path(__file__).resolve().parents[2] / 'scripts/monitor_operations.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Monitor = module.Monitor


@pytest.fixture
def monitor(tmp_path):
    now = [1000.0]
    instance = Monitor(str(tmp_path / 'monitor.sqlite3'), 'https://unused.invalid', clock=lambda: now[0])
    instance.now = now
    return instance


def observation(**changes):
    return dict({'key': 'job-123', 'kind': 'stale_job', 'severity': 'warning', 'job_id': 'job-123', 'credit_state': 'started', 'evidence': {'age_seconds': 100}}, **changes)


def test_deduplicates_across_restart_and_escalates_resolves(monitor):
    monitor.observe([observation()], 'application', release='release-123')
    monitor.now[0] += 30
    monitor.observe([observation(evidence={'age_seconds': 130})], 'application', release='release-123')
    assert len(monitor.queue()['delivery']) == 1
    database = monitor.db.execute('PRAGMA database_list').fetchone()[2]
    restarted = Monitor(database, 'https://unused.invalid', clock=monitor.clock)
    restarted.observe([observation(evidence={'age_seconds': 160})], 'application', release='release-123')
    assert len(restarted.queue()['delivery']) == 1
    restarted.observe([observation(severity='critical')], 'application', release='release-123')
    assert len(restarted.queue()['delivery']) == 2
    restarted.observe([], 'application', complete=False)
    assert restarted.queue()['incidents'][0]['status'] == 'open'
    restarted.observe([], 'external')
    assert restarted.queue()['incidents'][0]['status'] == 'open'
    restarted.observe([], 'application')
    assert restarted.queue()['incidents'][0]['status'] == 'resolved'
    assert len(restarted.queue()['delivery']) == 3
    assert restarted.queue()['incidents'][0]['first_seen'] == 1000


def test_redaction_and_monitor_owned_action(monitor):
    monitor.observe([observation(evidence={'prompt': 'secret manuscript', 'error': 'credential=secret', 'age_seconds': 100}, safe_action='Send secret manuscript', credit_state={'state': 'held', 'prompt': 'secret'})], 'application')
    encoded = json.dumps(monitor.queue())
    assert 'secret' not in encoded
    payload = monitor.queue()['incidents'][0]['payload']
    assert payload['job_id'] == 'job-123'
    assert payload['credit_state'] == {'state': 'held'}
    assert payload['safe_action']
    assert payload['diagnostic_url']


def test_operator_resolution_does_not_change_source_and_reopens_on_change(monitor):
    monitor.observe([observation()], 'application')
    monitor.resolve('application:job-123', 'reconciled')
    monitor.observe([observation(evidence={'age_seconds': 9999})], 'application')
    assert monitor.queue()['incidents'][0]['status'] == 'operator_resolved'
    assert len(monitor.queue()['delivery']) == 2
    monitor.observe([observation(credit_state='settlement_failed')], 'application')
    assert monitor.queue()['incidents'][0]['status'] == 'open'
    assert len(monitor.queue()['delivery']) == 3


def test_delivery_is_opt_in_and_failure_is_visible_without_secret(monitor):
    monitor.observe([observation()], 'application')
    with patch.object(module, 'open_request', side_effect=OSError('secret webhook token')) as request:
        monitor.deliver('')
        request.assert_not_called()
        monitor.deliver('https://example.invalid/hook')
    entry = monitor.queue()['delivery'][0]
    assert entry['attempts'] == 1
    assert entry['last_error'] == 'delivery_failed'
    assert entry['next_attempt'] > monitor.clock()
    assert 'secret' not in json.dumps(monitor.queue())


def test_external_http_fault_injection(monitor):
    """Real local HTTP: stalled readiness, outage, maintenance, then recovery."""
    scenario = {'health': 200, 'ready': 200, 'observations': [observation()]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/api/health':
                status, body = scenario['health'], {}
            elif self.path == '/api/health/ready':
                status, body = scenario['ready'], {}
            else:
                assert self.headers.get('X-Canary-Ops-Token') == 'local-only'
                status, body = 200, {'release': 'local-test', 'observations': scenario['observations'], 'complete': True}
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monitor.base_url = 'http://127.0.0.1:' + str(server.server_port)
    monitor.token = 'local-only'
    try:
        monitor.poll()
        scenario['ready'] = 503
        monitor.poll()
        monitor.now[0] += 301
        monitor.poll()
        assert 'external:readiness' in [r['key'] for r in monitor.queue()['incidents'] if r['status'] == 'open']
        scenario['health'] = 503
        monitor.poll()
        monitor.now[0] += 61
        monitor.poll()
        queue = monitor.queue()
        assert 'external:availability' in [r['key'] for r in queue['incidents'] if r['status'] == 'open']
        assert next(r for r in queue['incidents'] if r['source'] == 'application')['status'] == 'open'
        assert next(r for r in queue['incidents'] if r['key'] == 'external:readiness')['status'] == 'open'
        assert next(r for r in queue['incidents'] if r['key'] == 'external:availability')['payload']['release'] == 'local-test'
        notice_count = len(queue['delivery'])
        monitor.poll()
        assert len(monitor.queue()['delivery']) == notice_count
        monitor.state('maintenance_until', monitor.clock() + 120)
        monitor.poll()
        assert next(r for r in monitor.queue()['incidents'] if r['key'] == 'external:availability')['status'] == 'open'
        monitor.now[0] += 121
        monitor.poll()
        assert 'external:maintenance' in [r['key'] for r in monitor.queue()['incidents'] if r['status'] == 'open']
        monitor.state('maintenance_until', 0)
        scenario.update(health=200, ready=200, observations=[])
        monitor.poll()
        assert all(r['status'] == 'resolved' for r in monitor.queue()['incidents'])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    # A genuinely dead HTTP process still generates an external incident.
    monitor.poll()
    monitor.now[0] += 61
    monitor.poll()
    assert next(r for r in monitor.queue()['incidents'] if r['key'] == 'external:availability')['status'] == 'open'


def test_snapshot_kinds_have_specific_monitor_guidance(monitor, tmp_path):
    import ast
    import inspect
    from novel_to_comic.server import operations
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from novel_to_comic.server.admission import Admission
    class Database:
        def __init__(self, tables): self.tables = tables
        def table(self, name):
            rows = self.tables.get(name, [])
            class Query:
                def select(self, *_): return self
                def order(self, *_): return self
                def eq(self, *_): return self
                def range(self, *_): return self
                def execute(self): return SimpleNamespace(data=rows)
            return Query()
    def app_at(root):
        return SimpleNamespace(state=SimpleNamespace(projects_dir=root,
            admission=Admission(root), generation_jobs={}, running_tasks={}, style_tasks={}))
    NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)
    calls = ast.walk(ast.parse(inspect.getsource(operations)))
    kinds = {node.args[0].value for node in calls if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'add'
             and node.args and isinstance(node.args[0], ast.Constant)}
    assert kinds <= module.GUIDANCE.keys()
    snapshot = operations.exception_snapshot(app_at(tmp_path), now=NOW, db=Database({
        'credit_ledger': [dict(id='hold', status='reserved', job_id='job',
            reservation_started_at='2026-01-01T00:00:00Z', reservation_expires_at='2026-01-01T00:00:00Z')]}))
    monitor.observe(snapshot['observations'], 'application', release=snapshot['release'])
    held = next(row['payload'] for row in monitor.queue()['incidents'] if row['payload']['kind'] == 'credit_reconciliation')
    assert held['action_id'] == 'hold'
    assert held['credit_state'] == 'reserved'
    assert 'original usage call' in held['safe_action']
    assert held['diagnostic_url'].startswith('https://')
    assert held['runbook'].startswith('https://')


def test_probe_auth_is_scoped_and_redirects_are_refused(monitor):
    monitor.token = 'private-token'
    requests = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, count): return b'{}'
    def opened(request, **kwargs):
        requests.append(request)
        return Response()
    with patch.object(module, 'open_request', side_effect=opened):
        monitor.request('/api/health')
        monitor.request('/api/health/ready')
        monitor.request('/api/ops/exceptions')
    assert all('X-canary-ops-token' not in request.headers for request in requests[:2])
    assert requests[-1].headers['X-canary-ops-token'] == 'private-token'
    assert module.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid') is None
    with pytest.raises(ValueError):
        Monitor(':memory:', 'http://public.example')
