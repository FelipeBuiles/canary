"""Executed inside a pinned container; stdin is private expected bundle data.

Output consists only of booleans. Exceptions deliberately produce no traceback.
"""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


def verify(expected):
    spec = importlib.util.spec_from_file_location('runtime_loader', '/app/canary_secrets.py')
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    supervisor = loader.runtime_environment(Path('/proc'))
    if set(supervisor) & loader.ALLOWED != set(expected['env']):
        return False
    source = Path('/app/entrypoint.sh').read_text()
    scopes = {}
    for name in ('GATEWAY_ONLY_SECRETS', 'WEB_ONLY_SECRETS'):
        match = re.search(name + r'=\((.*?)\)', source, re.S)
        if not match:
            return False
        scopes[name] = set(match[1].split())
    processes = {}
    for cmdline in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args = cmdline.read_bytes().split(b'\0')
            if b'/app/novel_to_comic/.venv/bin/pipeline' in args and b'serve' in args:
                processes['web'] = cmdline.parent
            if b'/app/.venv-litellm/bin/litellm' in args and b'--port' in args:
                processes['gateway'] = cmdline.parent
        except OSError:
            continue
    if set(processes) != {'web', 'gateway'}:
        return False
    for process, directory in processes.items():
        values = dict(os.fsdecode(item).split('=', 1) for item in (directory / 'environ').read_bytes().split(b'\0') if b'=' in item)
        excluded = scopes['GATEWAY_ONLY_SECRETS' if process == 'web' else 'WEB_ONLY_SECRETS']
        if any(values.get(name) != value or supervisor.get(name) != value for name, value in expected['public'].items()):
            return False
        for name, value in expected['env'].items():
            if supervisor.get(name) != value:
                return False
            if (name in excluded and name in values) or (name not in excluded and values.get(name) != value):
                return False
    for name, value in expected['files'].items():
        if name != 'google-adc.json' or Path('/run/credentials/google-adc.json').read_text() != value:
            return False
    return True


if __name__ == '__main__':
    try:
        print(json.dumps({'matched': verify(json.load(sys.stdin))}))
    except BaseException:  # Never print values or exceptions at this secret-bearing boundary.
        print('{"matched":false}')
