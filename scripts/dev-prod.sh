#!/usr/bin/env bash
# scripts/dev-prod.sh — boot the merged prod-parity container locally.
#
# Wraps `docker compose --profile prod` so the VITE_* build args get wired in
# automatically from your existing env files. Without this, Vite inlines empty
# values into the JS bundle and the frontend can't reach Supabase (no login,
# no auth, broken app).
#
# Vars are resolved from (first match wins):
#   1. Your shell environment (export VAR=... before invoking this script)
#   2. web/.env.local
#   3. web/.env   — frontend settings
#   4. .env       — backend and shared PostHog settings
#
# VITE_SUPABASE_URL is derived from SUPABASE_URL if not set explicitly, since
# they're the same value (both point to your Supabase project). That kills the
# only real duplication in the env model.
#
# Usage:
#   ./scripts/dev-prod.sh              # default: up --build canary-prod (foreground)
#   ./scripts/dev-prod.sh up -d        # detached
#   ./scripts/dev-prod.sh down         # stop + remove containers
#   ./scripts/dev-prod.sh logs -f      # tail logs
#   ./scripts/dev-prod.sh build        # build only
#   ./scripts/dev-prod.sh ps           # show status
#
# Any args after the script name are forwarded to docker compose with
# `--profile prod` injected, so you retain full compose flexibility.

set -euo pipefail

# Resolve repo root from this script's location so it works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

source "$SCRIPT_DIR/dev_environment.sh"
report_posthog_configuration
# An empty optional BuildKit secret keeps source-map upload disabled.
export POSTHOG_API_KEY="${POSTHOG_API_KEY-}"

# ─── Derive VITE_SUPABASE_URL from SUPABASE_URL when possible ───────────────
#
# These are the same value in every deployment: the public Supabase project
# URL. Frontend (browser) and backend (server) both hit it. Deriving saves you
# maintaining the value in two files.
if [ -z "${VITE_SUPABASE_URL:-}" ] && [ -n "${SUPABASE_URL:-}" ]; then
  VITE_SUPABASE_URL="$SUPABASE_URL"
fi

# ─── Validate required vars ────────────────────────────────────────────────
#
# These two are the only Vite vars the bundle genuinely needs at build time.
# VITE_POSTHOG_PROJECT_TOKEN is optional (frontend no-ops when unset); VITE_CANARY_ENV
# defaults to the local CANARY_ENV label (development).

_missing=""
if [ -z "${VITE_SUPABASE_URL:-}" ]; then
  _missing="$_missing
  VITE_SUPABASE_URL   (or SUPABASE_URL to derive it from)"
fi
if [ -z "${VITE_SUPABASE_PUBLISHABLE_KEY:-}" ]; then
  _missing="$_missing
  VITE_SUPABASE_PUBLISHABLE_KEY"
fi
if [ -n "$_missing" ]; then
  echo "[dev-prod] missing required build vars:$_missing" >&2
  echo "[dev-prod] set them in web/.env, or export them before running this script." >&2
  echo "[dev-prod] VITE_SUPABASE_PUBLISHABLE_KEY is the *anon/publishable* key (role:anon" >&2
  echo "[dev-prod] in its JWT payload), NOT the service_role key — service_role bypasses" >&2
  echo "[dev-prod] RLS and must never ship to the browser. See web/.env.example." >&2
  exit 1
fi

# ─── Echo the resolved build args (publishable key masked) ─────────────────
#
# Reassuring when you're unsure which env file a value came from. The key is
# logged as <first 20 chars>…<last 4> — enough to confirm it's the right key
# without leaking the full token into your terminal scrollback.

_mask() {
  local k="$1"
  if [ "${#k}" -le 24 ]; then
    echo "***"
  else
    echo "${k:0:20}…${k: -4}"
  fi
}

echo "[dev-prod] resolved build args:"
echo "[dev-prod]   VITE_SUPABASE_URL          = $VITE_SUPABASE_URL"
echo "[dev-prod]   VITE_SUPABASE_PUBLISHABLE  = $(_mask "$VITE_SUPABASE_PUBLISHABLE_KEY")"
if [ -n "${VITE_POSTHOG_PROJECT_TOKEN:-}" ]; then
  echo "[dev-prod]   VITE_POSTHOG_PROJECT_TOKEN            = (set)"
else
  echo "[dev-prod]   VITE_POSTHOG_PROJECT_TOKEN            = (unset — frontend PostHog no-ops)"
fi
echo "[dev-prod]   VITE_CANARY_ENV            = ${VITE_CANARY_ENV:-production}"

# Export so docker compose's build-args interpolation picks them up.
export VITE_SUPABASE_URL VITE_SUPABASE_PUBLISHABLE_KEY VITE_CANARY_ENV
export VITE_POSTHOG_PROJECT_TOKEN VITE_POSTHOG_HOST  # may be empty — Dockerfile handles that

# ─── Default subcommand: up --build canary-prod ────────────────────────────
if [ "$#" -eq 0 ]; then
  set -- up --build canary-prod
fi

echo "[dev-prod] running: docker compose --profile prod $*"
exec docker compose --profile prod "$@"
