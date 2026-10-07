#!/usr/bin/env bash
# Refresh only the local gateway; reuse the launcher's environment precedence.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  exec python3 "$SCRIPT_DIR/gateway_refresh.py" --help
fi
source "$SCRIPT_DIR/dev_environment.sh"
GATEWAY_PYTHON="$REPO_ROOT/novel_to_comic/.venv/bin/python"
if [ ! -x "$GATEWAY_PYTHON" ]; then
  echo "[gateway] Backend Python environment is missing; install the project dependencies first." >&2
  exit 1
fi
exec "$GATEWAY_PYTHON" "$SCRIPT_DIR/gateway_refresh.py" "$@"
