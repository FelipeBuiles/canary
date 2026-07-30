# check=skip=SecretsUsedInArgOrEnv
# Stage 1: Build React frontend
#
# VITE_* vars are inlined into the JS bundle at build time (the browser talks
# to Supabase directly for auth), so they must be present HERE, not at runtime.
# They flow in as build args (publishable/anon values and public Sentry DSN only
# — safe to expose in the image; RLS gates access). Pass via
# `docker build --build-arg VITE_...=...`
# or Fly's `fly deploy --build-arg`.
FROM node:22-slim AS frontend
WORKDIR /build
ARG CANARY_VERSION=unknown
ARG CANARY_BUILD_TIMESTAMP=unknown
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ARG VITE_SENTRY_DSN
ARG VITE_SENTRY_TRACES_SAMPLE_RATE=0
ARG VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE=0
ARG VITE_CANARY_ENV=production
RUN if [ -z "$VITE_SUPABASE_URL" ]; then \
      echo "VITE_SUPABASE_URL build argument is required" >&2; exit 1; \
    fi \
    && if [ -z "$VITE_SUPABASE_PUBLISHABLE_KEY" ]; then \
      echo "VITE_SUPABASE_PUBLISHABLE_KEY build argument is required" >&2; exit 1; \
    fi \
    && case "$VITE_SUPABASE_URL" in https://*.supabase.co|http://localhost:*|http://127.0.0.1:*) ;; *) echo "VITE_SUPABASE_URL must be a Supabase HTTPS URL or a local development URL" >&2; exit 1 ;; esac
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Export the build args into the shell environment so Vite inlines them into
# the bundle. Supabase URL/key are required and validated before compilation;
# optional values such as VITE_SENTRY_DSN may remain empty.
RUN export VITE_SUPABASE_URL="$VITE_SUPABASE_URL" \
    VITE_SUPABASE_PUBLISHABLE_KEY="$VITE_SUPABASE_PUBLISHABLE_KEY" \
    VITE_SENTRY_DSN="$VITE_SENTRY_DSN" \
    VITE_SENTRY_TRACES_SAMPLE_RATE="$VITE_SENTRY_TRACES_SAMPLE_RATE" \
    VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE="$VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE" \
    VITE_CANARY_ENV="$VITE_CANARY_ENV" \
    VITE_CANARY_VERSION="$CANARY_VERSION" \
    VITE_CANARY_BUILD_TIMESTAMP="$CANARY_BUILD_TIMESTAMP" \
    && npm run build

# Stage 2: Python backend + co-located LiteLLM proxy
#
# One container runs two processes:
#   1. LiteLLM proxy on 127.0.0.1:4000 (holds all provider API keys; the only
#      process that egresses to OpenAI/Anthropic/Vertex/Reve/fal).
#   2. uvicorn web app on 0.0.0.0:8000 (talks to the proxy over loopback).
#
# Collapsing the previous two-Fly-app split into one machine keeps provider
# keys off the public path (the proxy is bound to loopback, never exposed)
# while letting the whole box scale to zero on idle and trimming ~$10-15/mo
# of idle compute. See docs/deploy.md for the architecture rationale.
FROM python:3.12-slim
WORKDIR /app
ARG CANARY_VERSION=unknown
ARG CANARY_BUILD_TIMESTAMP=unknown
ENV CANARY_VERSION="$CANARY_VERSION" \
    CANARY_BUILD_TIMESTAMP="$CANARY_BUILD_TIMESTAMP"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies (layer-cached separately from source)
# --no-install-project skips building the package itself (src/ not present yet)
COPY novel_to_comic/pyproject.toml novel_to_comic/uv.lock ./novel_to_comic/
RUN cd novel_to_comic && uv sync --extra web --frozen --no-dev --no-install-project

# Install Playwright Chromium and the matching system dependencies. Keep this
# delegated to Playwright so upgrades cannot silently omit a newly required
# shared library (the hand-maintained list previously missed libasound.so.2).
# Retries handle transient Debian mirror and browser-download failures.
RUN set -eu; \
    for i in 1 2 3; do \
      if /app/novel_to_comic/.venv/bin/playwright install --with-deps chromium; then \
        break; \
      fi; \
      if [ "$i" -eq 3 ]; then \
        exit 1; \
      fi; \
      echo "Playwright install failed, retrying..."; \
      rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /var/cache/apt/archives/lock; \
      sleep 5; \
    done; \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb

# Copy application source and install the project itself
COPY novel_to_comic/ ./novel_to_comic/
RUN cd novel_to_comic && uv sync --extra web --frozen --no-dev

# ─── LiteLLM proxy (loopback subprocess) ────────────────────────────────────
# The proxy has its own dependency tree (transitively large, occasionally
# conflicting with the web app's pinned versions). Install it in an isolated
# venv so the two never contend on resolution, mirroring the previous
# two-image split but inside one container.
#
# `[proxy]` pulls the proxy-server extras (uvicorn, fastapi, gunicorn,
# websockets, anthropic, …) that the docker.litellm.ai prebuilt image ships
# with. Without it the proxy boots then immediately ModuleNotFoundError-exits.
#
# Vertex AI support is NOT in [proxy] (the Google provider deps are optional in
# litellm 1.83.14). Without google-cloud-aiplatform + google-auth the proxy
# boots cleanly but every vertex_ai/* model group 500s at request time with
# "ModuleNotFoundError: No module named 'google'" — which silently breaks the
# whole pipeline (extract/panel/prompt/image stages all route to Vertex). The
# prebuilt docker.litellm.ai image ships these; we add them explicitly to match.
RUN python -m venv /app/.venv-litellm \
    && /app/.venv-litellm/bin/pip install --no-cache-dir 'litellm[proxy]==1.83.14' \
    && /app/.venv-litellm/bin/pip install --no-cache-dir \
        'google-cloud-aiplatform>=1.133' \
        'google-auth>=2.49' \
        'google-genai==1.75.0'

# LiteLLM config + custom handlers (vertex-multimodal / reve / fal-queue).
# PYTHONPATH makes the handlers importable; config.yaml's custom_provider_map
# registers them with the proxy at boot.
COPY litellm/config.yaml /app/config.yaml
COPY litellm_handlers/ /app/litellm_handlers/

# Copy the merged entrypoint (materializes GCP creds → starts litellm in the
# background → execs uvicorn in the foreground as PID 1).
COPY litellm/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Copy built frontend so FastAPI can serve it as static files
COPY --from=frontend /build/dist ./web/dist

ENV PYTHONPATH=/app:/app/litellm_handlers

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
