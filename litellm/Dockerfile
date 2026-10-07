FROM node:24.21.0-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
WORKDIR /app

# Same resolution as production, without inheriting a second dependency tree
# from the upstream gateway image. Never install into the application venv.
COPY litellm/pyproject.toml litellm/uv.lock /app/gateway/
RUN UV_PROJECT_ENVIRONMENT=/app/.venv \
    uv sync --project /app/gateway --locked --no-dev --no-install-project

# Prisma's generated client and CLI engines must exist before startup.
# Node is shared with the reviewed frontend runtime; npm is build-only.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ENV PRISMA_BINARY_CACHE_DIR=/opt/prisma/binaries \
    PRISMA_CLI_PATH=/opt/prisma/binaries/node_modules/.bin/prisma \
    PRISMA_CLI_QUERY_ENGINE_TYPE=binary
RUN PATH="/app/.venv/bin:$PATH" HOME=/opt/prisma XDG_CACHE_HOME=/opt/prisma/.cache \
    /app/.venv/bin/python -c 'from importlib.util import find_spec; from pathlib import Path; import subprocess, sys; schema = Path(find_spec("litellm").origin).parent / "proxy/schema.prisma"; assert schema.is_file(), schema; subprocess.run([sys.executable, "-m", "prisma", "generate", "--schema", str(schema)], check=True)' \
    && chmod -R a+rX /opt/prisma \
    && test -x /opt/prisma/binaries/node_modules/.bin/prisma \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm
ENV PRISMA_OFFLINE_MODE=true

COPY litellm/patch_http_errors.py litellm/patch_anthropic_refusals.py \
    litellm/canary_metrics.py litellm/canary_metrics_callback.py /app/
RUN /app/.venv/bin/python /app/patch_http_errors.py \
    && /app/.venv/bin/python /app/patch_anthropic_refusals.py

COPY litellm/config.yaml /app/config.yaml
COPY litellm_handlers/__init__.py litellm_handlers/provider_wire.py litellm_handlers/fal_provider.py litellm_handlers/openai_image_stream.py litellm_handlers/vertex_multimodal.py /app/litellm_handlers/
COPY litellm_handlers/image_previews.py /app/litellm_handlers/
COPY scripts/gateway_state.py /app/gateway_state.py
# The refresh command supplies a digest of the Dockerfile, lockfiles, patches,
# and startup helper. Direct builds remain untracked until refreshed once.
ARG CANARY_GATEWAY_BUILD_SHA256=untracked
LABEL com.canary.gateway.build-sha256=$CANARY_GATEWAY_BUILD_SHA256
ENV CANARY_GATEWAY_BUILD_SHA256=$CANARY_GATEWAY_BUILD_SHA256
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app:/app/litellm_handlers
# Price and gate every route from the bundled map plus config model_info, never
# a copy fetched at boot (see litellm/config.yaml).
ENV LITELLM_LOCAL_MODEL_COST_MAP=True
EXPOSE 4000
ENTRYPOINT ["/app/.venv/bin/python", "/app/gateway_state.py"]
CMD ["--host", "0.0.0.0", "--port", "4000", "--config", "/app/config.yaml"]
