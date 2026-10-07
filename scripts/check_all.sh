#!/usr/bin/env bash
# Run the complete local test and build gate from any working directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK_NODE_VERSION="$(cat "$REPO_ROOT/.nvmrc")"

# Git GUI clients may inherit a different Node than the interactive shell.
if [[ "$(node --version 2>/dev/null || true)" != "v$CHECK_NODE_VERSION" ]]; then
  CHECK_NODE_BIN="${NVM_DIR:-$HOME/.nvm}/versions/node/v$CHECK_NODE_VERSION/bin"
  if [[ -x "$CHECK_NODE_BIN/node" ]]; then
    export PATH="$CHECK_NODE_BIN:$PATH"
  fi
fi
if [[ "$(node --version 2>/dev/null || true)" != "v$CHECK_NODE_VERSION" ]]; then
  echo "FAIL/BLOCKED: Node $CHECK_NODE_VERSION is required; run nvm install and nvm use." >&2
  exit 1
fi

# Match CI without depending on local auth settings or uploading sourcemaps.
export VITE_SUPABASE_URL=https://ci.supabase.co
export VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_ci
export POSTHOG_API_KEY=
export POSTHOG_PROJECT_ID=

exec python3 "$SCRIPT_DIR/check_release.py" local "$@"
