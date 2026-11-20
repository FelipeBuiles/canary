#!/usr/bin/env bash
# GET an API path from inside a playwright-cli session's page, with that session's
# Supabase bearer token when it is signed in. Prints the HTTP status, then the body.
# Usage: api.sh <session> </api/path> [out-file]
#   api.sh canary-verify /api/projects "$EV/projects.json"
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PW="$REPO_ROOT/node_modules/.bin/playwright-cli"
SESSION="${1:?session}"; API_PATH="${2:?/api/path}"; OUT="${3:-}"
case "$API_PATH" in /api/*) ;; *) echo "path must start with /api/" >&2; exit 2;; esac

raw="$("$PW" -s="$SESSION" run-code "async page => page.evaluate(async (path) => {
  const key = Object.keys(localStorage).find(k => k.endsWith('-auth-token'));
  const token = key ? JSON.parse(localStorage.getItem(key))?.access_token : null;
  const r = await fetch(path, { headers: token ? { Authorization: 'Bearer ' + token } : {} });
  return JSON.stringify({ status: r.status, signedIn: Boolean(token), body: await r.text() });
}, '$API_PATH')" 2>&1)"
json="$(printf '%s\n' "$raw" | sed -n '/^### Result/{n;p;}')"
[ -n "$json" ] || { printf '%s\n' "$raw" >&2; exit 1; }
"$REPO_ROOT/novel_to_comic/.venv/bin/python" -I -c '
import json, sys
outer = json.loads(sys.argv[1]); outer = json.loads(outer) if isinstance(outer, str) else outer
status, signed_in = outer["status"], outer["signedIn"]
print(f"HTTP {status} signed_in={signed_in}", file=sys.stderr)
body = outer["body"]
if sys.argv[2]:
    open(sys.argv[2], "w").write(body)
    print(f"saved {sys.argv[2]} ({len(body)} bytes)", file=sys.stderr)
else:
    print(body)
sys.exit(0 if 200 <= outer["status"] < 300 else 1)
' "$json" "$OUT"
