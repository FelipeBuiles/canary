#!/usr/bin/env python3
"""Root-owned host maintenance agent; fixed JSON actions over a private Unix socket."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import socketserver
import subprocess
import time
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

BASE = Path('/usr/local/lib/canary')
STATE = Path('/var/lib/canary-host')
SOCKET = Path('/run/canary-host/control.sock')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
RECOVERY_ENABLED = Path('/etc/systemd/system/multi-user.target.wants/canary-host-recover.service')
HOLD = Path('/etc/canary/maintenance')
ACTIVE = {'queued', 'checking', 'draining', 'updating', 'rebooting', 'verifying'}
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
       'HOME': '/root', 'LC_ALL': 'C', 'DEBIAN_FRONTEND': 'noninteractive', 'NEEDRESTART_MODE': 'l'}


def run(args, timeout=120):
    return subprocess.run(args, check=True, capture_output=True, timeout=timeout, env=ENV).stdout.decode()


def read(name, default=None):
    path = STATE / name
    return json.loads(path.read_text()) if path.exists() else default


def write(name, value):
    path = STATE / name
    temporary = STATE / ('.' + uuid.uuid4().hex)
    with temporary.open('x') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def lock(path, *, report_busy=False):
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if report_busy:
                operation('failed', error='deployment_in_progress_try_again_after_release')
            raise
        yield


def worker_unit_active():
    try:
        run(['systemctl', 'is-active', '--quiet', 'canary-host-maintenance'], timeout=5)
        return True
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 3:  # systemctl positively reports an inactive/failed unit.
            return False
        raise


def operation(phase, **values):
    current = read('operation.json', {})
    current.update(phase=phase, updated_at=time.time(), **values)
    write('operation.json', current)


def simulation():
    output = run(['apt-get', '-s', '--with-new-pkgs', '--no-remove', 'upgrade'])
    packages = [line for line in output.splitlines() if line.startswith(('Inst ', 'Conf ', 'Remv '))]
    if any(line.startswith('Remv ') for line in packages):
        raise RuntimeError('package_removal_refused')
    return {'packages': packages, 'digest': hashlib.sha256('\n'.join(packages).encode()).hexdigest()}


def status():
    services = {}
    for unit in ('canary', 'docker', 'nginx', 'apt-daily.timer', 'apt-daily-upgrade.timer'):
        try:
            services[unit] = run(['systemctl', 'is-active', unit], timeout=5).strip()
        except subprocess.SubprocessError as exc:
            services[unit] = (getattr(exc, 'stdout', None) or b'').decode().strip() or 'unknown'
    readiness = None
    try:
        release = release_module()
        config = release.parse_environment(release.private_read(release.CONFIG))
        request = urllib.request.Request('http://127.0.0.1:8000/api/health/ready',
                                         headers={'Host': config['CANARY_HEALTH_HOST']})
        with urllib.request.urlopen(request, timeout=3) as response:
            health = json.load(response)
        readiness = {key: health.get(key) for key in ('status', 'checks')}
    except (OSError, ValueError, KeyError, RuntimeError):
        pass
    disk = shutil.disk_usage('/var/lib/docker')
    try:
        containers = [json.loads(line) for line in run([
            'docker', 'ps', '-a', '--filter', 'label=com.docker.compose.project=canary',
            '--format', '{{json .}}'], timeout=5).splitlines()]
        containers = [{key: row.get(key) for key in ('Names', 'Image', 'State', 'Status')} for row in containers]
    except (subprocess.SubprocessError, ValueError):
        containers = None
    reboot = Path('/run/reboot-required')
    reboot_packages = Path('/run/reboot-required.pkgs')
    return {'checked_at': time.time(), 'services': services, 'readiness': readiness, 'containers': containers,
            'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
            'load': os.getloadavg(), 'disk_free_bytes': disk.free, 'disk_total_bytes': disk.total,
            'reboot_required': reboot.exists(),
            'reboot_packages': reboot_packages.read_text().splitlines() if reboot_packages.exists() else [],
            'maintenance_hold': HOLD.exists(), 'plan': read('plan.json'), 'operation': read('operation.json')}


def submit(request):
    action = request.get('action')
    if action not in {'check', 'update', 'reboot'} or set(request) - {'action', 'request_id', 'plan_digest'}:
        raise ValueError('invalid_action')
    uuid.UUID(request['request_id'])
    with lock(STATE / 'control.lock'):
        previous = read('operation.json', {})
        if previous.get('request_id') == request['request_id']:
            return previous
        # 'rebooting' has no live worker by design; the recovery unit settles it.
        if previous.get('phase') in ACTIVE - {'rebooting'} and not worker_unit_active():
            # The worker died (SIGKILL, RuntimeMaxSec, host crash); any hold it made stays in force.
            operation('failed', error='worker_exited_inspect_host_before_retry')
            previous = read('operation.json', {})
        if previous.get('phase') in ACTIVE:
            raise RuntimeError('maintenance_already_running')
        if HOLD.exists():
            raise RuntimeError('existing_maintenance_hold_requires_operator')
        if action == 'update':
            plan = read('plan.json', {})
            if not plan or plan.get('digest') != request.get('plan_digest') or time.time() - plan['checked_at'] > 1800:
                raise RuntimeError('refresh_update_preview_required')
        write('operation.json', {**request, 'phase': 'queued', 'updated_at': time.time()})
        try:
            # The fixed unit survives the request, the app stopping, and browser disconnects.
            run(['systemd-run', '--unit=canary-host-maintenance', '--collect',
                 '--property=RuntimeMaxSec=7200', '--property=UMask=0077', '--property=LimitCORE=0',
                 '/usr/bin/python3', str(BASE / 'host_agent.py'), '--worker'])
        except BaseException:
            operation('failed', error='worker_launch_failed_inspect_host_before_retry')
            raise
        return read('operation.json')


def release_module():
    spec = importlib.util.spec_from_file_location('canary_host_release', BASE / 'release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def context(release):
    config = release.parse_environment(release.private_read(release.CONFIG))
    loader = release.load_module('canary_secrets', BASE / 'canary_secrets.py')
    if hashlib.sha256((BASE / 'canary_secrets.py').read_bytes()).hexdigest() != config['CANARY_LOADER_SHA256']:
        raise RuntimeError('host_loader_mismatch')
    bundle = loader.decrypt(Path(config['CANARY_BUNDLE_PATH']), Path('/etc/canary/keys/age.txt'), config['CANARY_BUNDLE_SHA256'])
    return config, bundle['env']['CANARY_OPS_TOKEN']


def restore(release, config, token, version):
    operation('verifying')
    # The same hold fences CI and boot startup until this worker owns recovery.
    HOLD.unlink()
    run(['systemctl', 'reset-failed', 'canary.service'])
    run(['systemctl', 'start', 'canary.service'])
    release.wait_candidate(config, token, version)
    release.run(['python3', str(BASE / 'verify_deployment.py'), '--resume'], env={
        **release.SYSTEM_ENV, 'CANARY_OPS_TOKEN': token, 'EXPECTED_CANARY_VERSION': version,
        'SCENEWRIGHT_APP_URL': config['SCENEWRIGHT_APP_URL']}, timeout=180)
    if release.api('/api/ops/deployment-status', config, token).get('draining') is not False:
        raise RuntimeError('resume_failed')
    operation('complete')


def worker(*, recover=False):
    current = read('operation.json', {})
    if recover and (current.get('phase') != 'rebooting' or current.get('boot_id') == BOOT_ID.read_text().strip()):
        return
    if not recover and current.get('phase') != 'queued':
        raise RuntimeError('no_queued_operation')
    release = release_module()
    release.RUNTIME.mkdir(mode=0o700, exist_ok=True)
    owns_hold = recover
    stopping_started = recover
    config = token = None
    # Failure fencing and stopping must finish before releasing CI's lock.
    # A busy lock at boot must not overwrite the recorded 'rebooting' operation.
    with lock(release.RUNTIME / 'worker.lock', report_busy=not recover):
        try:
            action = current['action']
            if recover:
                config, token = context(release)
                restore(release, config, token, current['version'])
                return
            if HOLD.exists():
                raise RuntimeError('existing_maintenance_hold')
            if action in {'check', 'update'}:
                operation('checking')
                run(['apt-get', '-o', 'APT::Update::Error-Mode=any', 'update'], timeout=600)
                plan = {**simulation(), 'checked_at': time.time()}
                write('plan.json', plan)
                if action == 'check':
                    operation('complete')
                    return
                if plan['digest'] != current.get('plan_digest'):
                    raise RuntimeError('updates_changed_review_new_preview')
            if action == 'reboot' and not RECOVERY_ENABLED.exists():
                raise RuntimeError('boot_recovery_not_enabled')
            config, token = context(release)
            run(['systemctl', 'is-active', '--quiet', 'canary.service'])
            version = release.api('/api/version', config)['git_sha']
            if not release.re.fullmatch(r'[0-9a-f]{40}', version):
                raise RuntimeError('unknown_application_version')
            operation('draining', version=version)
            # Exclusive create: never claim or clear an unrelated operator hold.
            with HOLD.open('x'):
                pass
            owns_hold = True
            release.drain(config, token)
            stopping_started = True  # An ambiguous stop failure must stay fenced.
            run(['systemctl', 'stop', 'canary.service'], timeout=90)
            if action == 'reboot':
                operation('rebooting', boot_id=BOOT_ID.read_text().strip())
                run(['systemctl', 'reboot'])
                return
            operation('updating')
            run(['apt-get', '-o', 'Dpkg::Options::=--force-confdef', '-o', 'Dpkg::Options::=--force-confold',
                 '--with-new-pkgs', '--no-remove', '-y', 'upgrade'], timeout=2400)
            run(['systemctl', 'restart', 'docker.service', 'nginx.service'], timeout=120)
            write('plan.json', {**simulation(), 'checked_at': time.time()})
            restore(release, config, token, version)
        except BaseException as exc:
            resumed = False
            if owns_hold and not stopping_started and config and token:
                # Canary was never stopped (drain failed or timed out): reopen admission
                # and release our own hold rather than leaving an idle, paused app.
                try:
                    if release.api('/api/ops/resume', config, token, 'POST').get('draining') is False:
                        HOLD.unlink(missing_ok=True)
                        owns_hold, resumed = False, True
                except Exception:  # noqa: BLE001 — stay fenced when resume is uncertain.
                    print('drain_recovery_uncertain_maintenance_hold_retained', flush=True)
            if owns_hold:
                HOLD.touch(mode=0o600)
                if stopping_started:
                    try:
                        run(['systemctl', 'stop', 'canary.service'], timeout=90)
                    except subprocess.SubprocessError:
                        pass
            code = 'drain_failed_generation_resumed' if resumed else str(exc) if isinstance(exc, RuntimeError) and str(exc) in {
                'updates_changed_review_new_preview', 'existing_maintenance_hold',
                'boot_recovery_not_enabled', 'unknown_application_version', 'host_loader_mismatch',
            } else 'maintenance_failed_inspect_host_journal'
            operation('failed', error=code)
            raise


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(20)
        try:
            line = self.rfile.readline(4097)
            if len(line) > 4096:
                raise ValueError('request_too_large')
            request = json.loads(line)
            if not isinstance(request, dict):
                raise TypeError('invalid_request')
            if request == {'action': 'status'}:
                result = status()
            else:
                result = submit(request)
            response = {'ok': True, 'result': result}
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.SubprocessError):
            response = {'ok': False, 'error': 'Host request failed; refresh status and inspect the host journal.'}
        self.wfile.write(json.dumps(response).encode() + b'\n')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('root_required')
    STATE.mkdir(mode=0o700, exist_ok=True)
    if args.worker or args.recover:
        try:
            worker(recover=args.recover)
        except BaseException:  # noqa: BLE001 — redact credential-bearing subprocess errors.
            if read('operation.json', {}).get('phase') == 'queued':
                operation('failed', error='worker_could_not_start_inspect_host_before_retry')
            # Do not print subprocess objects or decrypted configuration.
            raise SystemExit('host_maintenance_failed_inspect_operation_state') from None
    else:
        SOCKET.unlink(missing_ok=True)
        with socketserver.UnixStreamServer(str(SOCKET), Handler) as server:
            SOCKET.chmod(0o600)
            server.serve_forever()


if __name__ == '__main__':
    main()
