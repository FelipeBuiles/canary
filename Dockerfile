# Stage 1: Build React frontend
FROM node:22-slim AS frontend
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm install
COPY web/ ./
RUN npm run build

# Stage 2: Python backend
FROM python:3.12-slim
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies (layer-cached separately from source)
# --no-install-project skips building the package itself (src/ not present yet)
COPY novel_to_comic/pyproject.toml novel_to_comic/uv.lock ./novel_to_comic/
RUN cd novel_to_comic && uv sync --extra web --frozen --no-dev --no-install-project

# Install Playwright Chromium and its system deps
# Retries handle transient Debian mirror hash mismatches
RUN for i in 1 2 3; do \
      rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /var/cache/apt/archives/lock \
      && apt-get update -o Acquire::Check-Valid-Until=false \
      && break || { echo "apt-get update failed, retrying..."; sleep 5; } \
    done \
 && for i in 1 2 3; do \
      apt-get install -y --no-install-recommends \
      at-spi2-common libatk-bridge2.0-0t64 libatk1.0-0t64 libatspi2.0-0t64 \
      libcairo2 libcups2t64 libdrm2 libgbm1 libglib2.0-0t64 \
      libnspr4 libnss3 libpango-1.0-0 libwayland-server0 \
      libx11-6 libx11-xcb1 libxau6 libxcb1 libxcomposite1 \
      libxdamage1 libxdmcp6 libxext6 libxfixes3 libxfont2 libxi6 \
      libxkbcommon0 libxml2 libxmu6 libxpm4 libxrandr2 \
      libxrender1 libxshmfence1 libxt6t64 xvfb \
      && break || { echo "apt-get install failed, retrying..."; sleep 5; rm -rf /var/cache/apt/archives/*.deb; } \
    done \
 && /app/novel_to_comic/.venv/bin/playwright install chromium

# Copy application source and install the project itself
COPY novel_to_comic/ ./novel_to_comic/
RUN cd novel_to_comic && uv sync --extra web --frozen --no-dev

# Copy built frontend so FastAPI can serve it as static files
COPY --from=frontend /build/dist ./web/dist

EXPOSE 8000

ENTRYPOINT ["/app/novel_to_comic/.venv/bin/pipeline"]
# --proxy-headers: trust X-Forwarded-* from Fly's TLS proxy so secure cookies
# and client-IP detection work. Safe behind a reverse proxy; the image is the
# production/behind-proxy artifact (local dev runs `pipeline serve` directly).
CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--projects-dir", "/projects", "--proxy-headers"]
