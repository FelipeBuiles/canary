#!/usr/bin/env bash
# Sign the canary-verify browser session in as the test account through the real /login form.
# Reads CANARY_VERIFY_EMAIL / CANARY_VERIFY_PASSWORD from the environment or the repo .env.
# The password never reaches stdout: all playwright-cli output is redacted.
# Usage: signin.sh <evidence-dir>
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
FRONTEND="${CANARY_VERIFY_FRONTEND:-http://127.0.0.1:5173}"
OUT="${1:?usage: signin.sh <evidence-dir>}"
PW="$REPO_ROOT/node_modules/.bin/playwright-cli"
export PLAYWRIGHT_CLI_SESSION=canary-verify

read_key() {
  local key="$1"
  if [ -n "${!key:-}" ]; then printf '%s' "${!key}"; return; fi
  sed -n "s/^$key=//p" "$REPO_ROOT/.env" 2>/dev/null | head -1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}
EMAIL="$(read_key CANARY_VERIFY_EMAIL)"
PASS="$(read_key CANARY_VERIFY_PASSWORD)"
[ -n "$EMAIL" ] && [ -n "$PASS" ] || { echo "CANARY_VERIFY_EMAIL/PASSWORD not set" >&2; exit 2; }

redact() { EMAIL="$EMAIL" PASS="$PASS" perl -pe 's/\Q$ENV{PASS}\E/<password>/g; s/\Q$ENV{EMAIL}\E/<email>/g'; }
pw() { "$PW" "$@" 2>&1 | redact; }

mkdir -p "$OUT"
pw open "$FRONTEND/login" >/dev/null
pw run-code "async page => {
  await page.getByRole('form', { name: 'Sign in' }).waitFor();
}" >/dev/null
# Values are JSON-quoted into the code string; anything playwright-cli echoes back is redacted.
pw run-code "async page => {
  const form = page.getByRole('form', { name: 'Sign in' });
  await form.getByLabel('Email').fill($(EMAIL="$EMAIL" "$REPO_ROOT/novel_to_comic/.venv/bin/python" -I -c 'import json,os;print(json.dumps(os.environ["EMAIL"]))'));
  await form.getByLabel('Password').fill($(PASS="$PASS" "$REPO_ROOT/novel_to_comic/.venv/bin/python" -I -c 'import json,os;print(json.dumps(os.environ["PASS"]))'));
  await form.locator('button[type=submit]').click();
  await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 });
}" | tail -5
pw screenshot --filename="$OUT/after-signin.png" >/dev/null
url="$(pw eval 'location.pathname' | tail -1)"
echo "signed in; landed on $url; screenshot $OUT/after-signin.png"
