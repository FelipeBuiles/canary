"""Temporary branch-only dependency refresh; remove after validation."""
import json
import pathlib
import re
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'fix/dependency-refresh-2026-09'


def get(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        return json.load(response)


def stable_in_line(name, prefix):
    data = get('https://registry.npmjs.org/' + name)
    versions = [v for v in data['versions'] if v.startswith(prefix) and re.fullmatch(r'\d+\.\d+\.\d+', v)]
    return max(versions, key=lambda v: tuple(map(int, v.split('.'))))


def replace(path, old, new):
    target = ROOT / path
    text = target.read_text()
    if old not in text:
        raise RuntimeError(f'Missing expected source in {path}: {old[:80]}')
    target.write_text(text.replace(old, new))


npm = {
    '@playwright/cli': '0.1.21', '@remotion/cli': '4.0.526',
    '@remotion/eslint-config-flat': '4.0.526', '@remotion/tailwind-v4': '4.0.526',
    'remotion': '4.0.526', '@sentry/react': '10.75.0',
    '@supabase/supabase-js': '2.116.0', '@tanstack/react-query': '5.103.1',
    'react': '19.3.0', 'react-dom': '19.3.0', '@types/react': '19.3.0',
    '@types/react-dom': '19.3.0', 'react-router-dom': '7.18.4',
    'zustand': '5.0.15', 'lucide-react': '1.47.0',
    '@eslint/js': '10.0.1', 'eslint': '10.11.0',
    'eslint-plugin-react-hooks': '7.1.1', 'eslint-plugin-react-refresh': '0.5.7',
    'typescript-eslint': '8.70.0', 'typescript': stable_in_line('typescript', '6.0.'),
    '@types/node': stable_in_line('@types/node', '24.'), '@types/web': '0.0.356',
    'tailwindcss': '4.3.3', '@tailwindcss/vite': '4.3.3',
    '@vitejs/plugin-react': '6.1.1', 'vite': '8.3.0', 'vitest': '5.0.1',
    'jsdom': '30.1.0', '@testing-library/dom': '10.4.2',
    '@testing-library/react': '16.3.3', '@testing-library/user-event': '14.6.7',
    'sharp': '0.35.4', 'globals': '17.12.0', 'prettier': '3.9.8',
    'canvas': '3.2.3', 'mock-match-media': '1.0.3', 'resize-observer-polyfill': '1.5.1',
}
node_releases = get('https://nodejs.org/dist/index.json')
node = next(r['version'][1:] for r in node_releases if r['version'].startswith('v24.') and r['lts'])
(ROOT / '.nvmrc').write_text(node + '\n')
for name in ('package.json', 'web/package.json', 'showcase/video/package.json'):
    path = ROOT / name
    data = json.loads(path.read_text())
    for group in ('dependencies', 'devDependencies'):
        for package, spec in data.get(group, {}).items():
            version = npm[package]
            # Remotion's packages must stay in exact lockstep; TS7 is outside
            # typescript-eslint's peer range, so stay on the supported 6.0 line.
            prefix = '~' if package == 'typescript' else '^' if spec.startswith('^') else ''
            data[group][package] = prefix + version
    data['engines'] = {'node': '>=24.15.0 <25'}
    path.write_text(json.dumps(data, indent=2) + '\n')

python_versions = {
    'click': ('8.5.0', '9'), 'pydantic': ('2.13.5', '3'), 'pyyaml': ('6.0.3', '7'),
    'httpx': ('0.28.1', '0.29'), 'PyJWT[crypto]': ('2.14.0', '3'),
    'supabase': ('2.31.0', '3'), 'boto3': ('1.43.98', '2'), 'stripe': ('15.6.1', '16'),
    'ebooklib': ('0.20', '0.21'), 'Pillow': ('12.3.0', '13'), 'img2pdf': ('0.6.3', '0.7'),
    'playwright': ('1.63.0', '2'), 'rich': ('15.0.0', '16'), 'tenacity': ('9.1.4', '10'),
    'python-dotenv': ('1.2.3', '2'), 'python-multipart': ('0.0.32', '0.1'),
    'pypdf': ('6.19.0', '7'), 'fastapi': ('0.141.1', '0.142'),
    'uvicorn[standard]': ('0.53.0', '0.54'), 'slowapi': ('0.1.10', '0.2'),
    'sentry-sdk[fastapi]': ('2.69.2', '3'), 'pytest': ('9.1.1', '10'),
    'ruff': ('0.16.8', '0.17'), 'opentelemetry-api': ('1.44.0', '2'),
    'opentelemetry-sdk': ('1.44.0', '2'), 'opentelemetry-exporter-otlp-proto-http': ('1.44.0', '2'),
    'setuptools': ('84.0.0', '85'),
}
p = ROOT / 'novel_to_comic/pyproject.toml'
s = p.read_text()
for name, (version, upper) in python_versions.items():
    s, count = re.subn(r'"' + re.escape(name) + r'(?:[<>=!~][^"\n]*)?"', f'"{name}>={version},<{upper}"', s)
    assert count == 1, (name, count)
p.write_text(s)

(ROOT / 'litellm/pyproject.toml').write_text('''[project]
name = "canary-gateway"
version = "0.1.0"
description = "Isolated, shared dependency environment for both Canary gateways"
requires-python = ">=3.12,<3.13"
dependencies = [
  "litellm[proxy]==1.101.0",
  "google-cloud-aiplatform==2.1.3",
  "google-auth==2.58.0",
  "google-genai==2.24.0",
]

[dependency-groups]
dev = ["pytest>=9.1.1,<10"]

[tool.uv]
package = false
''')

replace('Dockerfile', 'FROM node:22-slim AS frontend', f'FROM node:{node}-bookworm-slim AS frontend')
replace('Dockerfile', 'FROM python:3.12-slim', 'FROM python:3.12-slim-bookworm')
replace('Dockerfile', 'ghcr.io/astral-sh/uv:latest', 'ghcr.io/astral-sh/uv:0.12.17')
p = ROOT / 'Dockerfile'
s = p.read_text()
start = s.index('# Vertex AI support is NOT in [proxy]')
end = s.index('\nCOPY litellm/patch_http_errors.py', start)
s = s[:start] + '''# Both local Compose and production resolve this exact independent lockfile.
# Keep the gateway isolated: its Rich/WebSocket constraints differ from the app.
COPY litellm/pyproject.toml litellm/uv.lock /app/gateway/
RUN UV_PROJECT_ENVIRONMENT=/app/.venv-litellm \\
    uv sync --project /app/gateway --locked --no-dev --no-install-project
''' + s[end:]
p.write_text(s)
(ROOT / 'litellm/Dockerfile').write_text('''FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
WORKDIR /app

# Same resolution as production, without inheriting a second dependency tree
# from the upstream gateway image. Never install into the application venv.
COPY litellm/pyproject.toml litellm/uv.lock /app/gateway/
RUN UV_PROJECT_ENVIRONMENT=/app/.venv \\
    uv sync --project /app/gateway --locked --no-dev --no-install-project

COPY litellm/patch_http_errors.py litellm/patch_anthropic_refusals.py /app/
RUN /app/.venv/bin/python /app/patch_http_errors.py \\
    && /app/.venv/bin/python /app/patch_anthropic_refusals.py

COPY litellm/config.yaml /app/config.yaml
COPY litellm_handlers/ /app/litellm_handlers/
ENV PYTHONPATH=/app:/app/litellm_handlers
EXPOSE 4000
ENTRYPOINT ["/app/.venv/bin/litellm"]
CMD ["--host", "0.0.0.0", "--port", "4000", "--config", "/app/config.yaml"]
''')
replace('docker-compose.yml', 'canary-litellm:1.83.14-google-genai-1.75.0', 'canary-litellm:1.101.0-google-genai-2.24.0')
replace('docker-compose.yml', 'langfuse-worker:3.172.0', 'langfuse-worker:3.225.8')
replace('docker-compose.yml', 'langfuse/langfuse:3.172.0', 'langfuse/langfuse:3.225.8')
# Stateful storage stays on its existing major/LTS line; a major change would
# require a separately tested data migration, not just an image replacement.
ops = {}
for repo, prefix, old in (
    ('library/postgres', '17.', 'docker.io/postgres:17'),
    ('library/redis', '7.4.', 'docker.io/redis:7.4'),
    ('clickhouse/clickhouse-server', '26.3.', 'docker.io/clickhouse/clickhouse-server:26.3.9.8'),
):
    url = f'https://hub.docker.com/v2/repositories/{repo}/tags?page_size=100&name={prefix}'
    tags = get(url)['results']
    versions = [t['name'] for t in tags if t['name'].startswith(prefix) and re.fullmatch(r'\d+(\.\d+)+', t['name'])]
    assert versions, repo
    version = max(versions, key=lambda v: tuple(map(int, v.split('.'))))
    new = old.rsplit(':', 1)[0] + ':' + version
    replace('docker-compose.yml', old + '\n', new + '\n')
    ops[repo] = version

# Replace the obsolete duplicate-SDK-string test with a real lock contract.
p = ROOT / 'novel_to_comic/tests/test_launch_safety.py'
s = p.read_text()
s = s.replace('    assert "google-genai==1.75.0" in production\n    assert "google-genai==1.75.0" in local_gateway\n', '''    import tomllib

    gateway = tomllib.loads((root / "litellm/pyproject.toml").read_text())
    lock = tomllib.loads((root / "litellm/uv.lock").read_text())
    versions = {package["name"]: package["version"] for package in lock["package"]}
    assert "google-genai==2.24.0" in gateway["project"]["dependencies"]
    assert versions["google-genai"] == "2.24.0"
    assert versions["litellm"] == "1.101.0"
    for dockerfile in (production, local_gateway):
        assert "COPY litellm/pyproject.toml litellm/uv.lock" in dockerfile
        assert "uv sync --project /app/gateway --locked" in dockerfile
''')
assert s != p.read_text(), 'expected legacy pin assertions'
p.write_text(s)

report = {'node': node, 'npm': npm, 'python': python_versions, 'ops': ops}
pathlib.Path('/tmp/dependency-review').mkdir(exist_ok=True)
pathlib.Path('/tmp/dependency-review/selected.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
