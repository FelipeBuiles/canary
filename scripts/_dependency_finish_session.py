"""One-time branch-local compatibility edits; removed before merge."""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
assert subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip() == 'fix/dependency-refresh-2026-09'
if '[tool.ruff]' in (ROOT / 'novel_to_comic/pyproject.toml').read_text():
    raise SystemExit('Compatibility fixes already applied')

def replace(path, old, new):
    target = ROOT / path
    source = target.read_text()
    assert source.count(old) == 1, (path, source.count(old))
    target.write_text(source.replace(old, new))

replace('novel_to_comic/tests/test_labs_gate.py',
        'return any(r.path.startswith("/api/labs") for r in app.routes)',
        '# Included routers are lazy in newer FastAPI; inspect the public schema.\n    return any(path.startswith("/api/labs") for path in app.openapi()["paths"])')
replace('novel_to_comic/tests/test_cast_asset_routes.py', '''        (path, method)
        for route in app.routes
        for path in [route.path]
        for method in (getattr(route, "methods", None) or ())''', '''        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}''')
replace('novel_to_comic/tests/test_complete_page_draw.py',
        '    assert finalized["langfuse_input"]["prompt"] == prepared.prompt',
        '    from novel_to_comic.ai.client import _truncate_for_log\n\n    # Telemetry is bounded; the full frozen prompt is asserted on the wire above.\n    assert finalized["langfuse_input"]["prompt"] == _truncate_for_log(prepared.prompt)')
replace('novel_to_comic/src/novel_to_comic/cast_instructions.py',
        'from pydantic import Field\n', '')
replace('novel_to_comic/tests/test_lettering_translation.py',
        'from .test_hybrid_lettering import book, save, update',
        'from .test_hybrid_lettering import book as book, save, update')
p = ROOT / 'novel_to_comic/pyproject.toml'
p.write_text(p.read_text() + '''
[tool.ruff]
target-version = "py312"

[tool.ruff.lint]
# Preserve the pre-upgrade lint gate rather than silently adopting Ruff's
# expanded defaults. Broader style/security rules need a separate migration.
select = ["E4", "E7", "E9", "F"]
''')
p = ROOT / 'web/src/__tests__/castCorrectionRecovery.test.tsx'
s = p.read_text()
old = '  view = mount(client);'
assert s.count(old) == 2
start, _, end = s.rpartition(old)
p.write_text(start + '  mount(client);' + end)
replace('web/src/components/lettering/LetteringCanvas.tsx',
        '  const selectedElement = state.elements.find(e => e.id === selected && !e.hidden);',
        '''  const selectedElement = state.elements.find(e => e.id === selected && !e.hidden);
  // Geometry is pure render data; pointer handlers read refs only on events.
  const resizeHandle = selectedElement ? resizeHandlePosition(selectedElement, state.canvas_aspect_ratio) : null;''')
replace('web/src/components/lettering/LetteringCanvas.tsx',
        'const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));',
        '''const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));
function resizeHandlePosition(element: LetteringElement, aspect: number) {
  const box = elementRect(element), angle = element.rotation * Math.PI / 180;
  const dx = box.width / 2 * element.scale, dy = box.height / 2 * element.scale;
  return {
    x: box.x + box.width / 2 + dx * Math.cos(angle) - dy / aspect * Math.sin(angle),
    y: box.y + box.height / 2 + dx * aspect * Math.sin(angle) + dy * Math.cos(angle),
  };
}''')
replace('web/src/components/lettering/LetteringCanvas.tsx', '''          {selectedElement && !panMode && (() => {
            const box = elementRect(selectedElement), angle = selectedElement.rotation * Math.PI / 180;
            const dx = box.width / 2 * selectedElement.scale, dy = box.height / 2 * selectedElement.scale;
            const rx = box.x + box.width / 2 + dx * Math.cos(angle) - dy / state.canvas_aspect_ratio * Math.sin(angle);
            const ry = box.y + box.height / 2 + dx * state.canvas_aspect_ratio * Math.sin(angle) + dy * Math.cos(angle);
            return <>''', '          {selectedElement && resizeHandle && !panMode && <>')
replace('web/src/components/lettering/LetteringCanvas.tsx',
        'style={{ left: `${rx * 100}%`, top: `${ry * 100}%` }}',
        'style={{ left: `${resizeHandle.x * 100}%`, top: `${resizeHandle.y * 100}%` }}')
replace('web/src/components/lettering/LetteringCanvas.tsx',
        '            </>;\n          })()}', '          </>}')
replace('web/src/pages/BackofficePage.tsx',
        '  const [loading, setLoading] = useState(false);',
        '  const [loading, setLoading] = useState(Boolean(connection.token));')
replace('web/src/pages/BackofficePage.tsx', '''    if (!connection.token) {
      setSnapshot(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setConnectionError(null);''', '''    if (!connection.token) return;
    let cancelled = false;''')
replace('web/src/pages/BackofficePage.tsx',
        '    setConnection(nextConnection);',
        '    setConnection(nextConnection);\n    setLoading(Boolean(nextConnection.token));')
replace('web/src/pages/BackofficePage.tsx',
        '    clearOperatorToken();',
        '    clearOperatorToken();\n    setLoading(false);')
replace('web/src/__tests__/sentry.test.ts',
        '    const event = { request: { headers: {',
        '    const event = { type: undefined, request: { headers: {')
replace('web/src/__tests__/sentry.test.ts',
        '    expect(await beforeSend(event, {})).toEqual({ request: { headers: {',
        '    expect(await beforeSend(event, {})).toEqual({ type: undefined, request: { headers: {')
replace('web/src/__tests__/sentry.test.ts',
        '    expect(await beforeSend({}, {})).toEqual({});',
        '    expect(await beforeSend({ type: undefined }, {})).toEqual({ type: undefined });')
p = ROOT / 'web/package.json'
data = json.loads(p.read_text())
data['scripts']['audit:production'] = 'npm audit --omit=dev --audit-level=high'
p.write_text(json.dumps(data, indent=2) + '\n')
(ROOT / 'web/scripts/audit-production.mjs').unlink()
replace('docker-compose.yml', 'image: cgr.dev/chainguard/minio\n',
        'image: cgr.dev/chainguard/minio@sha256:e7728e37a015dcd2f2b146abc4aedc0096769ac72cb64cc9ed36b7f4183361e1\n')
print('Applied reviewed compatibility fixes')
