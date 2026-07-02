#!/bin/sh
# LiteLLM gateway entrypoint: materialize GCP service-account credentials from a
# base64-encoded Fly secret, then start the proxy.
#
# Set via: fly secrets set -a litellm-gw GCP_CREDENTIALS_B64="$(base64 < litellm/gcp-credentials.json)"
set -e

if [ -n "$GCP_CREDENTIALS_B64" ]; then
  printf '%s' "$GCP_CREDENTIALS_B64" | base64 -d > /app/gcp-credentials.json
  chmod 600 /app/gcp-credentials.json
fi

exec litellm --port 4000 --config /app/config.yaml
