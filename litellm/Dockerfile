FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
WORKDIR /app

# Same resolution as production, without inheriting a second dependency tree
# from the upstream gateway image. Never install into the application venv.
COPY litellm/pyproject.toml litellm/uv.lock /app/gateway/
RUN UV_PROJECT_ENVIRONMENT=/app/.venv \
    uv sync --project /app/gateway --locked --no-dev --no-install-project

COPY litellm/patch_http_errors.py litellm/patch_anthropic_refusals.py /app/
RUN /app/.venv/bin/python /app/patch_http_errors.py \
    && /app/.venv/bin/python /app/patch_anthropic_refusals.py

COPY litellm/config.yaml /app/config.yaml
COPY litellm_handlers/ /app/litellm_handlers/
ENV PYTHONPATH=/app:/app/litellm_handlers
EXPOSE 4000
ENTRYPOINT ["/app/.venv/bin/litellm"]
CMD ["--host", "0.0.0.0", "--port", "4000", "--config", "/app/config.yaml"]
