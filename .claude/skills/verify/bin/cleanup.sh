#!/usr/bin/env bash
# Close only the browser session this skill opened. Never touches the user's servers
# (8000/5173/4010/4000), Docker, or tmp/verify evidence.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PW="$REPO_ROOT/node_modules/.bin/playwright-cli"
for s in canary-verify canary-verify-public canary-verify-neg; do
  "$PW" -s="$s" close >/dev/null 2>&1 || true
  "$PW" -s="$s" delete-data >/dev/null 2>&1 || true
done
echo "closed playwright sessions canary-verify{,-public,-neg}; evidence kept under $REPO_ROOT/tmp/verify/"
