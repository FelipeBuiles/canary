#!/usr/bin/env python3
"""Independent Scenewright watchdog. Run outside the application Machine.

Defaults to a durable, local incident queue; webhook delivery is opt-in. Never
submits jobs, changes credits, or restarts the application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SAFE_EVIDENCE = frozenset('status age_seconds idle_seconds count threshold attempts restart_count free_bytes total_bytes used_percent phase state reason_code provider saved_output settlement_state hold_state last_progress_at expires_at started_at updated_at restart_budget window_seconds'.split())
# Each allowed kind has monitor-owned guidance: upstream text is never forwarded.
GUIDANCE = {
    'indeterminate_action': 'Inspect the durable request journal and affected project. Preserve its original action key; reconcile acceptance before any customer-authorized retry.',
    'interrupted_job': 'Inspect saved output and the original job and ledger. Do not requeue interrupted paid work or release its hold without reconciliation.',
    'stalled_job': 'Compare progress with worker and provider deadlines. Preserve output and holds; a long request alone does not prove failure.',
    'stalled_stage': 'Inspect the stage progress timestamp, saved artifacts and original calls before cancellation or an explicitly authorized resume.',
    'credit_reconciliation': 'Inspect the original usage call and ledger job. Reconcile idempotently; release only the specific hold whose liabilities are proved settled or absent.',
    'ambiguous_provider_call': 'Inspect the original provider operation, saved output and ledger. Never automatically resubmit an ambiguous paid image request.',
    'saved_output_recovery': 'Preserve the saved page and its pending or unfinished provenance. Recover saved evidence and reconcile the original usage before new spend.',
    'repeated_failure': 'Inspect the affected jobs and dependencies; fix their shared cause before allowing more paid attempts.',
    'restart_budget_exhausted': 'Inspect Fly events, release and durable recovery state. Fix the crash cause before explicitly resetting the restart budget.',
    'gateway_recovery_exhausted': 'Inspect LiteLLM configuration and readiness. Repair the gateway before a controlled restart; do not retry paid work.',
    'evidence_unavailable': 'Restore the named evidence source. Keep existing incidents and holds open; missing evidence is not proof of success.',
    'stale_job': 'Inspect job progress and saved artifacts; reconcile interrupted work before authorizing a new run.',
    'started_expired_hold': 'Inspect the paid-action journal and provider evidence; settle saved output or reconcile the hold explicitly. Do not release it blindly.',
    'ambiguous_submission': 'Inspect provider and saved Draw evidence. Do not resubmit an ambiguous paid request.',
    'ambiguous_settlement': 'Reconcile the action against saved output and the credit ledger before allowing another charge.',
    'repeated_failures': 'Inspect affected jobs and readiness; fix the shared cause before reopening admission.',
    'storage_pressure': 'Preserve artwork and journals. Increase storage or remove only verified disposable files.',
    'crash_loop': 'Inspect supervisor events and release health; correct the cause before explicitly resetting the restart budget.',
    'availability': 'Inspect Machine status and supervisor events. Verify maintenance intent before starting a stopped Machine.',
    'dependency_readiness': 'Inspect dependency health; restore the dependency before reopening admission. Do not repeatedly restart the application.',
    'monitor_snapshot': 'Check the monitor credential and diagnostic endpoint; internal incident resolution is paused.',
    'maintenance_overdue': 'Inspect the maintenance work and explicitly extend the deadline or finish maintenance and reopen admission.',
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_request(request, *, timeout):
    # Never forward an operations credential or incident body to a redirect.
    return urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)


def clean_observation(raw: dict) -> dict:
    """Persist structured operational metadata only, never upstream free text."""
    kind = str(raw.get('kind', 'monitor_snapshot'))
    if kind not in GUIDANCE:
        kind = 'monitor_snapshot'
    result = {'key': str(raw['key'])[:180], 'kind': kind,
              'severity': raw.get('severity') if raw.get('severity') in ('warning', 'critical') else 'warning',
              'safe_action': GUIDANCE[kind], 'diagnostic_url': '/api/ops/exceptions', 'runbook': 'docs/ops/crash-recovery.md', 'evidence': {}}
    for key in ('job_id', 'action_id', 'project_id'):
        value = raw.get(key)
        if isinstance(value, str) and len(value) <= 100 and all(c.isalnum() or c in '-_.' for c in value):
            result[key] = value
    for key, value in raw.get('evidence', {}).items():
        if key in SAFE_EVIDENCE and isinstance(value, (bool, int, float)):
            result['evidence'][key] = value
        elif key in SAFE_EVIDENCE and isinstance(value, str) and len(value) <= 100 and all(c.isalnum() or c in '-_.:+ /' for c in value):
            result['evidence'][key] = value
    credit = raw.get('credit_state')
    if isinstance(credit, str) and len(credit) <= 60 and all(c.isalnum() or c in '-_' for c in credit):
        result['credit_state'] = credit
    elif isinstance(credit, dict):
        result['credit_state'] = {k: v for k, v in credit.items() if k in ('hold_state', 'settlement_state', 'state') and isinstance(v, str) and len(v) <= 40 and all(c.isalnum() or c in '-_' for c in v)}
    return result


class Monitor:
    def __init__(self, database: str, base_url: str, token: str = '', *, outage_seconds: float = 60,
                 readiness_seconds: float = 300, timeout: float = 10, clock=time.time):
        self.base_url, self.token = base_url.rstrip('/'), token
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError('Use an origin URL without credentials, query, or fragment')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ValueError('Remote monitoring requires HTTPS')
        self.outage_seconds, self.readiness_seconds, self.timeout, self.clock = outage_seconds, readiness_seconds, timeout, clock
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS incidents (key TEXT PRIMARY KEY, source TEXT NOT NULL, status TEXT NOT NULL,
          first_seen REAL NOT NULL, last_seen REAL NOT NULL, resolved_at REAL, version INTEGER NOT NULL,
          fingerprint TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, incident_key TEXT NOT NULL, version INTEGER NOT NULL,
          event TEXT NOT NULL, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
          delivered_at REAL, last_error TEXT, next_attempt REAL NOT NULL DEFAULT 0,
          UNIQUE(incident_key, version));
        ''')

    def state(self, key, value=None):
        if value is not None:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, str(value)))
            self.db.commit()
            return value
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def request(self, path):
        headers = {'Accept': 'application/json'}
        if self.token and path == '/api/ops/exceptions':
            headers['X-Canary-Ops-Token'] = self.token
        try:
            with open_request(urllib.request.Request(self.base_url + path, headers=headers), timeout=self.timeout) as response:
                return response.status, json.loads(response.read(2_000_001))
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except (OSError, ValueError):
            return 0, None

    def condition(self, key, failing, threshold):
        if not failing:
            self.state(key, '')
            return False
        first = self.state(key)
        if not first:
            first = self.state(key, self.clock())
        return self.clock() - float(first) >= threshold

    def observe(self, observations, source, *, complete=True, release='unknown', resolve_keys=None):
        now, seen = self.clock(), set()
        with self.db:
            for raw in observations:
                payload = clean_observation(raw)
                payload['diagnostic_url'] = self.base_url + '/api/ops/exceptions'
                payload['runbook'] = 'https://github.com/FelipeBuiles/canary/blob/main/docs/ops/crash-recovery.md'
                # Source namespaces prevent endpoint observations resolving external incidents.
                key = source + ':' + payload['key']
                payload['key'] = key
                payload['release'] = release[:100] if isinstance(release, str) and all(c.isalnum() or c in '-_.' for c in release) else 'unknown'
                seen.add(key)
                # Age/progress/count jitter does not create a notification every poll.
                meaningful = {k: v for k, v in payload.items() if k != 'evidence'}
                meaningful['evidence'] = {k: v for k, v in payload['evidence'].items() if k in ('state', 'phase', 'reason_code', 'settlement_state', 'hold_state', 'saved_output')}
                fingerprint = hashlib.sha256(json.dumps(meaningful, sort_keys=True).encode()).hexdigest()
                previous = self.db.execute('SELECT * FROM incidents WHERE key=?', (key,)).fetchone()
                if previous and previous['status'] == 'operator_resolved' and previous['fingerprint'] == fingerprint:
                    self.db.execute('UPDATE incidents SET last_seen=?,payload=? WHERE key=?', (now, json.dumps(payload, sort_keys=True), key))
                    continue
                changed = previous is None or previous['status'] != 'open' or previous['fingerprint'] != fingerprint
                version = (previous['version'] if previous else 0) + int(changed)
                first = previous['first_seen'] if previous else now
                encoded = json.dumps(payload, sort_keys=True)
                self.db.execute('INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?)',
                                (key, source, 'open', first, now, None, version, fingerprint, encoded))
                if changed:
                    event = 'opened' if previous is None else 'reopened' if previous['status'] != 'open' else 'updated'
                    self.enqueue(key, version, event, payload, first, now)
            if complete or resolve_keys is not None:
                for row in self.db.execute("SELECT * FROM incidents WHERE source=? AND status='open'", (source,)).fetchall():
                    if row['key'] not in seen and (complete or row['key'].removeprefix(source + ':') in resolve_keys):
                        version = row['version'] + 1
                        self.db.execute("UPDATE incidents SET status='resolved',resolved_at=?,version=? WHERE key=?", (now, version, row['key']))
                        self.enqueue(row['key'], version, 'resolved', json.loads(row['payload']), row['first_seen'], now)

    def resolve(self, key, reason):
        if reason not in ('reconciled', 'customer_contacted', 'expected_stop'):
            raise ValueError('Invalid resolution reason')
        row = self.db.execute('SELECT * FROM incidents WHERE key=?', (key,)).fetchone()
        if row is None:
            raise ValueError('Unknown incident key')
        if row['status'] != 'open':
            return
        with self.db:
            self.db.execute("UPDATE incidents SET status='operator_resolved',resolved_at=?,version=version+1 WHERE key=?", (self.clock(), key))
            self.enqueue(key, row['version'] + 1, 'operator_resolved', dict(json.loads(row['payload']), resolution_reason=reason), row['first_seen'], self.clock())

    def enqueue(self, key, version, event, payload, first, now):
        notice = dict(payload, event=event, first_seen=first, last_seen=now, version=version)
        self.db.execute('INSERT INTO outbox (incident_key,version,event,payload) VALUES (?,?,?,?)',
                        (key, version, event, json.dumps(notice, sort_keys=True)))

    def poll(self):
        external = []
        until = float(self.state('maintenance_until') or 0)
        maintenance = until > self.clock()
        if until and not maintenance:
            external.append({'key': 'maintenance', 'kind': 'maintenance_overdue', 'severity': 'warning'})
        status, _ = self.request('/api/health')
        outage = status != 200
        if self.condition('outage_since', outage and not maintenance, self.outage_seconds):
            external.append({'key': 'availability', 'kind': 'availability', 'severity': 'critical', 'evidence': {'status': status}})
        ready, _ = self.request('/api/health/ready') if not outage else (0, None)
        if self.condition('readiness_since', not outage and ready != 200 and not maintenance, self.readiness_seconds):
            external.append({'key': 'readiness', 'kind': 'dependency_readiness', 'severity': 'critical', 'evidence': {'status': ready}})
        snapshot_status, snapshot = self.request('/api/ops/exceptions') if not outage else (0, None)
        valid = snapshot_status == 200 and isinstance(snapshot, dict) and isinstance(snapshot.get('observations'), list) and all(isinstance(o, dict) and isinstance(o.get('key'), str) and isinstance(o.get('evidence', {}), dict) for o in snapshot['observations'])
        if valid:
            self.state('last_release', snapshot.get('release', 'unknown'))
            self.observe(snapshot['observations'], 'application', complete=snapshot.get('complete') is True, release=snapshot.get('release', 'unknown'))
        if self.condition('snapshot_since', not valid and not outage and not maintenance, self.readiness_seconds):
            external.append({'key': 'snapshot', 'kind': 'monitor_snapshot', 'severity': 'warning', 'evidence': {'status': snapshot_status}})
        recovered = set()
        if status == 200:
            recovered.add('availability')
        if ready == 200:
            recovered.add('readiness')
        if valid:
            recovered.add('snapshot')
        if not until:
            recovered.add('maintenance')
        self.observe(external, 'external', complete=False, resolve_keys=recovered,
                     release=self.state('last_release') or 'unknown')

    def deliver(self, webhook):
        if not webhook:
            return
        if urllib.parse.urlsplit(webhook).scheme != 'https':
            raise ValueError('Notification webhooks must use HTTPS')
        for row in self.db.execute('SELECT * FROM outbox WHERE delivered_at IS NULL AND next_attempt<=? ORDER BY id LIMIT 20', (self.clock(),)).fetchall():
            try:
                request = urllib.request.Request(webhook, row['payload'].encode(), {'Content-Type': 'application/json', 'Idempotency-Key': f"{row['incident_key']}:{row['version']}"})
                with open_request(request, timeout=self.timeout) as response:
                    if not 200 <= response.status < 300:
                        raise OSError('delivery rejected')
                with self.db:
                    self.db.execute('UPDATE outbox SET delivered_at=?,last_error=NULL,attempts=attempts+1 WHERE id=?', (self.clock(), row['id']))
            except (OSError, ValueError):
                with self.db:
                    self.db.execute('UPDATE outbox SET last_error=?,attempts=attempts+1,next_attempt=? WHERE id=?', ('delivery_failed', self.clock() + min(3600, 30 * 2 ** min(row['attempts'], 7)), row['id']))

    def queue(self):
        return {'incidents': [dict(row, payload=json.loads(row['payload'])) for row in self.db.execute('SELECT * FROM incidents ORDER BY first_seen')],
                'delivery': [dict(row) for row in self.db.execute('SELECT id,incident_key,version,event,attempts,delivered_at,last_error,next_attempt FROM outbox ORDER BY id')]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default='operations.sqlite3')
    parser.add_argument('--url', default=os.getenv('SCENEWRIGHT_MONITOR_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--interval', type=float, default=30)
    parser.add_argument('--outage-seconds', type=float, default=60)
    parser.add_argument('--readiness-seconds', type=float, default=300)
    parser.add_argument('--resolve', help='Resolve an incident after reconciliation; does not change customer work or credits')
    parser.add_argument('--reason', choices=('reconciled', 'customer_contacted', 'expected_stop'))
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--queue', action='store_true')
    parser.add_argument('--maintenance-seconds', type=float)
    parser.add_argument('--end-maintenance', action='store_true')
    args = parser.parse_args()
    if args.interval <= 0 or args.outage_seconds < 0 or args.readiness_seconds < 0 or (args.maintenance_seconds is not None and not 0 < args.maintenance_seconds <= 86400):
        parser.error('Use positive intervals, nonnegative thresholds, and maintenance between 0 and 86400 seconds')
    monitor = Monitor(args.database, args.url, os.getenv('SCENEWRIGHT_OPS_TOKEN', ''), outage_seconds=args.outage_seconds, readiness_seconds=args.readiness_seconds)
    if args.maintenance_seconds is not None:
        monitor.state('maintenance_until', time.time() + args.maintenance_seconds)
        return
    if args.end_maintenance:
        monitor.state('maintenance_until', 0)
        return
    if args.resolve:
        if not args.reason:
            parser.error('--resolve requires --reason')
        monitor.resolve(args.resolve, args.reason)
        return
    if args.queue:
        print(json.dumps(monitor.queue(), indent=2))
        return
    while True:
        monitor.poll()
        monitor.deliver(os.getenv('SCENEWRIGHT_ALERT_WEBHOOK', ''))
        if args.once:
            print(json.dumps(monitor.queue(), indent=2))
            break
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
