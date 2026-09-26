# check=skip=SecretsUsedInArgOrEnv
# Stage 1: Build React frontend
#
# VITE_* vars are inlined into the JS bundle at build time (the browser talks
# to Supabase directly for auth), so they must be present HERE, not at runtime.
# They flow in as build args (publishable/anon values and public Sentry DSN only
# — safe to expose in the image; RLS gates access). Pass via
# `docker build --build-arg VITE_...=...`
# or Fly's `fly deploy --build-arg`.
FROM node:24.21.0-bookworm-slim AS frontend
# jsdom's real canvas peer needs these when no prebuilt exists (Linux ARM64).
# They stay in the frontend builder; the final Python image copies only dist.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 make g++ pkg-config libcairo2-dev libpango1.0-dev \
    libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build/web
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
COPY novel_to_comic/src/novel_to_comic/lettering/ /build/novel_to_comic/src/novel_to_comic/lettering/
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
#      process that egresses to OpenAI/Anthropic/OpenRouter/fal).
#   2. uvicorn web app on 0.0.0.0:8000 (talks to the proxy over loopback).
#
# Collapsing the previous two-Fly-app split into one machine keeps provider
# keys off the public path (the proxy is bound to loopback, never exposed).
# The Machine stays running; see docs/deploy.md for the architecture rationale.
FROM python:3.12-slim-bookworm
WORKDIR /app
ARG CANARY_VERSION=unknown
ARG CANARY_BUILD_TIMESTAMP=unknown
ENV CANARY_VERSION="$CANARY_VERSION" \
    CANARY_BUILD_TIMESTAMP="$CANARY_BUILD_TIMESTAMP"

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

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

# Generated public editions are supplied separately through CANARY_SHOWCASE_DIR
# (or a mount at this default path), never through the image build context.
RUN mkdir -p /app/showcase/books

# Copy application source and install the project itself
COPY novel_to_comic/ ./novel_to_comic/
RUN cd novel_to_comic && uv sync --extra web --frozen --no-dev
# The local Codex and Claude Code execution adapters are never present in a
# production image. Routing authority remains so stray saved subscription
# selections fail closed.
RUN rm novel_to_comic/src/novel_to_comic/ai/codex_runtime.py \
       novel_to_comic/src/novel_to_comic/ai/claude_runtime.py \
       novel_to_comic/src/novel_to_comic/ai/providers/codex_dev.py \
       novel_to_comic/src/novel_to_comic/codex_complete_page.py \
       novel_to_comic/src/novel_to_comic/server/routers/labs.py \
    && rm -r novel_to_comic/src/novel_to_comic/labs
RUN /app/novel_to_comic/.venv/bin/python -c "from novel_to_comic.server.showcase import books; books()"

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
# Both local Compose and production resolve this exact independent lockfile.
# Keep the gateway isolated: its Rich/WebSocket constraints differ from the app.
COPY litellm/pyproject.toml litellm/uv.lock /app/gateway/
RUN UV_PROJECT_ENVIRONMENT=/app/.venv-litellm \
    uv sync --project /app/gateway --locked --no-dev --no-install-project

# Prisma's generated client and CLI engines must exist before startup.
# Node is shared with the reviewed frontend runtime; npm is build-only.
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ENV PRISMA_BINARY_CACHE_DIR=/opt/prisma/binaries \
    PRISMA_CLI_PATH=/opt/prisma/binaries/node_modules/.bin/prisma \
    PRISMA_CLI_QUERY_ENGINE_TYPE=binary
RUN PATH="/app/.venv-litellm/bin:$PATH" HOME=/opt/prisma XDG_CACHE_HOME=/opt/prisma/.cache \
    /app/.venv-litellm/bin/python -c 'from importlib.util import find_spec; from pathlib import Path; import subprocess, sys; schema = Path(find_spec("litellm").origin).parent / "proxy/schema.prisma"; assert schema.is_file(), schema; subprocess.run([sys.executable, "-m", "prisma", "generate", "--schema", str(schema)], check=True)' \
    && chmod -R a+rX /opt/prisma \
    && test -x /opt/prisma/binaries/node_modules/.bin/prisma \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm
ENV PRISMA_OFFLINE_MODE=true

COPY litellm/patch_http_errors.py /app/patch_http_errors.py
RUN /app/.venv-litellm/bin/python /app/patch_http_errors.py

COPY litellm/patch_anthropic_refusals.py /app/patch_anthropic_refusals.py
RUN /app/.venv-litellm/bin/python /app/patch_anthropic_refusals.py

# LiteLLM config + the single retained custom handler (fal-queue).
# PYTHONPATH makes the handlers importable; config.yaml's custom_provider_map
# registers them with the proxy at boot.
COPY litellm/config.yaml /app/config.yaml
COPY litellm_handlers/__init__.py litellm_handlers/provider_wire.py litellm_handlers/fal_provider.py /app/litellm_handlers/

# Copy the merged entrypoint (materializes GCP creds → starts litellm → waits
# for readiness → supervises litellm and the web process together).
COPY litellm/entrypoint.sh /app/entrypoint.sh
COPY litellm/recovery.py /app/recovery.py
RUN chmod +x /app/entrypoint.sh

# Copy built frontend so FastAPI can serve it as static files
COPY --from=frontend /build/web/dist ./web/dist

ENV PYTHONPATH=/app:/app/litellm_handlers

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
