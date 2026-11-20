#!/usr/bin/env bash
# Read-only: is the user's running Canary stack worth driving? Starts nothing, stops nothing.
# Exit 0 = drivable, 1 = not drivable (reason printed). Never prints credentials.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
BACKEND="${CANARY_VERIFY_BACKEND:-http://127.0.0.1:8000}"
FRONTEND="${CANARY_VERIFY_FRONTEND:-http://127.0.0.1:5173}"
PY="$REPO_ROOT/novel_to_comic/.venv/bin/python"
fail=0

say()  { printf '%-8s %s\n' "$1" "$2"; }
bad()  { say "FAIL" "$1"; fail=1; }

# 1. Backend health: right contract, a known model mode, queue ok.
health="$(curl -sS --max-time 5 "$BACKEND/api/health/ready" 2>/dev/null)"
if [ -z "$health" ]; then
  bad "backend $BACKEND not answering. Ask the user to start ./scripts/dev.sh --mock (never start it yourself)."
else
  printf '%s' "$health" | "$PY" -I -B -c '
import json, sys
p = json.load(sys.stdin)
mode = p.get("model_mode"); contract = p.get("pipeline_contract"); checks = p.get("checks") or {}
status = p.get("status")
def say(tag, msg): print(f"{tag:<8} {msg}")
say("ok" if status == "ok" else "FAIL", f"backend status={status} contract={contract} model_mode={mode}")
say("info", "checks=" + json.dumps(checks, sort_keys=True))
if contract != "eight-stage-v2":
    say("FAIL", "pipeline_contract is not eight-stage-v2: backend is stale; ask the user to restart it"); sys.exit(1)
if checks.get("generation_queue") != "ok":
    say("FAIL", "generation_queue not ok"); sys.exit(1)
if mode != "mock":
    say("WARN", f"model_mode={mode}: PAID routing. Read-only journeys only; never run a stage, draw, redraw or estimate-then-confirm.")
sys.exit(0 if status == "ok" else 1)
' || fail=1
fi

# 2. Who owns the ports (so we never drive some unrelated server).
for port in 8000 5173 4010; do
  owner="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -Fc 2>/dev/null | sed -n 's/^c//p' | head -1)"
  say "info" "port $port listener: ${owner:-none}"
done

# 3. Frontend serves the SPA shell and proxies /api to the backend.
if curl -sS --max-time 5 "$FRONTEND/" 2>/dev/null | grep -q 'id="root"'; then
  say "ok" "frontend $FRONTEND serves the SPA"
else
  bad "frontend $FRONTEND not serving the SPA"
fi
cfg="$(curl -sS --max-time 5 "$FRONTEND/api/public-config" 2>/dev/null)"
if [ -z "$cfg" ]; then
  bad "frontend /api proxy to backend failed"
elif printf '%s' "$cfg" | grep -q '"turnstile_site_key":"[^"]'; then
  say "WARN" "Turnstile is configured: scripted password sign-in will be blocked; use the saved-state path in SKILL.md"
else
  say "ok" "no Turnstile key: scripted sign-in allowed"
fi

# 4. Test-account credentials present (values never printed).
for key in CANARY_VERIFY_EMAIL CANARY_VERIFY_PASSWORD; do
  if [ -n "${!key:-}" ] || grep -q "^$key=." "$REPO_ROOT/.env" 2>/dev/null; then
    say "ok" "$key set"
  else
    say "WARN" "$key missing: signed-in journeys cannot run (public journeys still can)"
  fi
done

# 5. Harness.
if [ -x "$REPO_ROOT/node_modules/.bin/playwright-cli" ]; then
  say "ok" "playwright-cli $("$REPO_ROOT/node_modules/.bin/playwright-cli" --version 2>/dev/null | tail -1)"
else
  bad "playwright-cli missing: run npm install at the repo root"
fi

say "info" "Supabase behind this stack is PRODUCTION: create nothing you do not need, only as the test account"
exit "$fail"
