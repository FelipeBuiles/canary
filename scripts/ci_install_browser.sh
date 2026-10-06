#!/usr/bin/env bash
set -euo pipefail

# Snapshots include the browser's system libraries. A lockfile upgrade remains
# safe before the image is rebuilt: install new dependencies on a mismatch.
version=$(uv run python -c 'from importlib.metadata import version; print(version("playwright"))')
if [[ -f /opt/canary-playwright-version ]] && [[ $(cat /opt/canary-playwright-version) == "$version" ]]; then
  uv run playwright install chromium
else
  uv run playwright install --with-deps chromium
fi
