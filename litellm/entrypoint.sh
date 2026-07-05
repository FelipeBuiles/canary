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
#   4. exec uvicorn in the foreground as PID 1. When uvicorn exits, the
#      container exits — the backgrounded litellm process is reaped with it.
#
# Provider keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, REVE_API_KEY,
# FAL_KEY, VERTEXAI_PROJECT, etc.) and LITELLM_MASTER_KEY/LITELLM_SALT_KEY must
# be set as Fly secrets on canary-web. They flow into the proxy's environment.

set -e

# 1. GCP service-account credentials for Vertex AI.
if [ -n "$GCP_CREDENTIALS_B64" ]; then
  printf '%s' "$GCP_CREDENTIALS_B64" | base64 -d > /app/gcp-credentials.json
  chmod 600 /app/gcp-credentials.json
fi

# 2. Start LiteLLM proxy in the background.
#    --num_workers 1 keeps memory bounded; the proxy is not the throughput
#    bottleneck for this product (one region, low concurrency).
PYTHONPATH=/app:/app/litellm_handlers /app/.venv-litellm/bin/litellm \
  --host 127.0.0.1 \
  --port 4000 \
  --num_workers 1 \
  --config /app/config.yaml &

LITELLM_PID=$!

# 3. Wait for the proxy to become ready (max ~60s — litellm loads ~870MB of
#    provider SDKs at boot, so cold starts are not instant). Use Python for
#    the poll — `python:3.12-slim` doesn't ship curl.
echo "[entrypoint] waiting for litellm proxy at 127.0.0.1:4000..."
READY=0
for i in $(seq 1 60); do
  if /app/.venv-litellm/bin/python -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:4000/health/liveliness', timeout=2).read()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    echo "[entrypoint] litellm proxy ready (after ${i}s)"
    READY=1
    break
  fi
  # Bail early if the proxy died during boot (OOM, bad config, etc.) so we
  # don't paper over a real failure with a 60s timeout.
  if ! kill -0 "$LITELLM_PID" 2>/dev/null; then
    echo "[entrypoint] litellm proxy exited during boot — aborting" >&2
    exit 1
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  echo "[entrypoint] litellm proxy did not become ready within 60s — aborting" >&2
  exit 1
fi

# 4. exec uvicorn as PID 1. --proxy-headers trusts X-Forwarded-* from Fly's
#    TLS proxy so secure cookies and client-IP detection work. When uvicorn
#    receives SIGTERM (Fly deploy / stop), the container exits cleanly.
exec /app/novel_to_comic/.venv/bin/pipeline serve \
  --host 0.0.0.0 \
  --port 8000 \
  --projects-dir /projects \
  --proxy-headers
