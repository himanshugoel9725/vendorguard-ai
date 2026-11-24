# syntax=docker/dockerfile:1
# VendorGuard AI API image: multi-stage (uv builds the environment), non-root, health-checked.
# Build:  docker build -t vendorguard-ai .      Run: see docker-compose.yml (profile "api").
# No secret is baked in: keys come from the environment at run time (compose reads .env).

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.10.0

FROM ${UV_IMAGE} AS uv

# ---------- builder: resolve the locked dependencies into /opt/venv ----------
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /build
# Dependencies first (cached until pyproject.toml or uv.lock change).
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
# Then the project itself, installed (not editable) into the same environment.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---------- runtime ----------
FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VENDORGUARD_CONFIG=/app/config/settings.yaml \
    VG_API__HOST=0.0.0.0 \
    VG_PATHS__RUNS_DIR=/data/runs \
    VG_PATHS__STATE_DIR=/data/state \
    VG_MEMORY__SQLITE_PATH=/data/state/memory.db \
    VG_CACHE__SQLITE_PATH=/data/state/cache.db
# A fixed non-root user; /data is the only writable place (mount a volume there).
RUN useradd --system --uid 10001 --user-group --home-dir /app --shell /usr/sbin/nologin vg \
    && mkdir -p /app /data/runs /data/state \
    && chown -R vg:vg /data
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=root:root config ./config
COPY --chown=root:root prompts ./prompts
USER vg
EXPOSE 8000
VOLUME ["/data"]
# /health needs no key. The port is read from the same variable the app uses.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('VG_API__PORT', '8000'), timeout=3)"]
# The API refuses to start without VG_API__AUTH_KEY (>= 16 random characters).
CMD ["python", "-m", "vendorguard.api.app"]
