#!/bin/bash
# Merged container entrypoint — runs LiteLLM proxy and the uvicorn web app as
# two processes in one container.
#
#   1. Materialize GCP service-account credentials from a base64-encoded
#      secret (Fly can't bind-mount files; the secret is the runtime source).
#   2. Start the LiteLLM proxy on 127.0.0.1:4000 in the background. It holds
#      all provider API keys; only the web app talks to it, over loopback.
#   3. Wait for the proxy's /health/liveliness endpoint to respond so uvicorn
#      doesn't boot before its AI backend is ready (avoids first-request 500s).
#   4. Run uvicorn alongside a small process supervisor. If LiteLLM exits after
#      boot, restart it instead of leaving a healthy-looking web app with a
#      permanently dead image gateway.
#
# Provider keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, REVE_API_KEY,
# FAL_KEY, VERTEXAI_PROJECT, etc.) and LITELLM_MASTER_KEY/LITELLM_SALT_KEY must
# be set as Fly secrets on canary-web. They flow into the proxy's environment.

set -e

# 1. GCP service-account credentials for Vertex AI.
if [ -n "$GCP_CREDENTIALS_B64" ]; then
  printf '%s' "$GCP_CREDENTIALS_B64" | base64 -d > /app/gcp-credentials.json
  chmod 600 /app/gcp-credentials.json
  # Point the Google SDK at the file we just materialized. LiteLLM's vertex_ai
  # provider loads ADC via google.auth, which honors this env var. Without it
  # the file sits unread and every Vertex request 500s with
  # "Your default credentials were not found".
  export GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-credentials.json
fi

# Fail fast with a clear message if Vertex is in use but unreachable — otherwise
# the LiteLLM proxy boots fine and every extract/panel/image request 500s with
# a wall of "ModuleNotFoundError: No module named 'google'" tracebacks. The
# config.yaml routes most text + image stages to vertex_ai/*, so a missing
# service-account file or a missing google-cloud-aiplatform install breaks the
# whole pipeline at the first LLM call.
if [ -n "$VERTEXAI_PROJECT" ]; then
  if [ ! -f /app/gcp-credentials.json ]; then
    echo "[entrypoint] VERTEXAI_PROJECT is set ($VERTEXAI_PROJECT) but no GCP" >&2
    echo "[entrypoint] credentials were provided. Set GCP_CREDENTIALS_B64 to the" >&2
    echo "[entrypoint] base64 of a service-account JSON. Without it, every Vertex" >&2
    echo "[entrypoint] model group (extract/panel/prompt/image) 500s at request time." >&2
    exit 1
  fi
  if ! /app/.venv-litellm/bin/python -c "import google.auth, google.cloud.aiplatform" 2>/dev/null; then
    echo "[entrypoint] Vertex AI is configured but the LiteLLM venv is missing the" >&2
    echo "[entrypoint] Google deps (google-cloud-aiplatform / google-auth). Vertex" >&2
    echo "[entrypoint] model groups will 500. Rebuild the image so the Dockerfile's" >&2
    echo "[entrypoint] google-cloud-aiplatform install line runs." >&2
    exit 1
  fi
fi

# 2. Start LiteLLM proxy in the background.
#    --num_workers 1 keeps memory bounded; the proxy is not the throughput
#    bottleneck for this product (one region, low concurrency).
start_litellm() {
  PYTHONPATH=/app:/app/litellm_handlers /app/.venv-litellm/bin/litellm \
    --host 127.0.0.1 \
    --port 4000 \
    --num_workers 1 \
    --config /app/config.yaml &
  LITELLM_PID=$!
  echo "[entrypoint] litellm proxy started (pid=${LITELLM_PID})"
}

# 3. Wait for the proxy to become ready (max ~60s — litellm loads ~870MB of
#    provider SDKs at boot, so cold starts are not instant). Use Python for
#    the poll — `python:3.12-slim` doesn't ship curl.
LITELLM_READY_TIMEOUT_SECONDS="${LITELLM_READY_TIMEOUT_SECONDS:-60}"
wait_for_litellm() {
  echo "[entrypoint] waiting for litellm proxy at 127.0.0.1:4000..."
  for i in $(seq 1 "$LITELLM_READY_TIMEOUT_SECONDS"); do
    if /app/.venv-litellm/bin/python -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=2).read()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "[entrypoint] litellm proxy ready (after ${i}s)"
    return 0
  fi
  # Bail early if the proxy died during boot (OOM, bad config, etc.) so we
  # don't paper over a real failure with the full startup timeout.
  if ! kill -0 "$LITELLM_PID" 2>/dev/null; then
    echo "[entrypoint] litellm proxy exited during boot — aborting" >&2
    return 1
  fi
  sleep 1
done
echo "[entrypoint] litellm proxy did not become ready within ${LITELLM_READY_TIMEOUT_SECONDS}s — aborting" >&2
return 1
}

start_litellm
if ! wait_for_litellm; then
  exit 1
fi

# 4. Run uvicorn alongside LiteLLM. --proxy-headers trusts X-Forwarded-* from
#    Fly's TLS proxy so secure cookies and client-IP detection work.
/app/novel_to_comic/.venv/bin/pipeline serve \
  --host 0.0.0.0 \
  --port 8000 \
  --projects-dir /projects \
  --proxy-headers &
APP_PID=$!

# Bash's `jobs -pr` is available in the production image and lets this script
# detect an exited child without relying on a non-portable `wait -n` feature.
job_is_running() {
  local candidate
  for candidate in $(jobs -pr); do
    if [ "$candidate" = "$1" ]; then
      return 0
    fi
  done
  return 1
}

LITELLM_RESTART_LIMIT="${LITELLM_RESTART_LIMIT:-3}"
LITELLM_RESTART_WINDOW_SECONDS="${LITELLM_RESTART_WINDOW_SECONDS:-300}"
LITELLM_RESTART_COUNT=0
LITELLM_RESTART_WINDOW_STARTED_AT="$(date +%s)"

# Ensure Fly SIGTERM and normal app exits reap both children.
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [ -n "${APP_PID:-}" ]; then
    kill "$APP_PID" 2>/dev/null || true
  fi
  if [ -n "${LITELLM_PID:-}" ]; then
    kill "$LITELLM_PID" 2>/dev/null || true
  fi
  if [ -n "${APP_PID:-}" ]; then
    wait "$APP_PID" 2>/dev/null || true
  fi
  if [ -n "${LITELLM_PID:-}" ]; then
    wait "$LITELLM_PID" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' INT TERM

while :; do
  # A web-process exit is the container's exit condition.
  if ! job_is_running "$APP_PID"; then
    set +e
    wait "$APP_PID"
    APP_STATUS=$?
    set -e
    exit "$APP_STATUS"
  fi

  # LiteLLM is independently restartable. Give it a bounded restart budget so
  # a bad image/config cannot create an invisible infinite crash loop.
  if ! job_is_running "$LITELLM_PID"; then
    set +e
    wait "$LITELLM_PID"
    LITELLM_STATUS=$?
    set -e
    NOW="$(date +%s)"
    if [ "$((NOW - LITELLM_RESTART_WINDOW_STARTED_AT))" -ge "$LITELLM_RESTART_WINDOW_SECONDS" ]; then
      LITELLM_RESTART_COUNT=0
      LITELLM_RESTART_WINDOW_STARTED_AT="$NOW"
    fi
    LITELLM_RESTART_COUNT=$((LITELLM_RESTART_COUNT + 1))
    if [ "$LITELLM_RESTART_COUNT" -gt "$LITELLM_RESTART_LIMIT" ]; then
      echo "[entrypoint] litellm proxy exited ${LITELLM_RESTART_COUNT} times in ${LITELLM_RESTART_WINDOW_SECONDS}s — stopping" >&2
      exit 1
    fi
    echo "[entrypoint] litellm proxy exited (status=${LITELLM_STATUS}); restarting (${LITELLM_RESTART_COUNT}/${LITELLM_RESTART_LIMIT})" >&2
    start_litellm
    if ! wait_for_litellm; then
      exit 1
    fi
  fi
  sleep 1
done
