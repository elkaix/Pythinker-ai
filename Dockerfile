# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Stage 1: webui-builder — produces pythinker/web/dist/
#
# Pinned to BUILDPLATFORM because WebUI output is platform-agnostic JS, so
# multi-arch image builds reuse the same dist without QEMU-emulating Bun on
# arm64 (saves ~5-10 min per arm64 leg).
#
# We invoke vite directly (skipping the package.json "build" script chain)
# because that chain runs `tsc -p tsconfig.build.json` (a type-check covered
# already by .github/workflows/ci.yml) and `python ../scripts/webui_hash.py`
# (a freshness marker that only matters when shipping pre-built dist via a
# wheel — irrelevant when we just built it here).
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM oven/bun:1-debian AS webui-builder

WORKDIR /build
COPY webui/ webui/
WORKDIR /build/webui
RUN bun install --frozen-lockfile
RUN bunx vite build

# ---------------------------------------------------------------------------
# Stage 2: app — main Pythinker runtime (Python + WhatsApp bridge + WebUI)
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS app

# Install Node.js 20 for the WhatsApp bridge, plus bubblewrap for the
# shell-tool sandbox and openssh-client/git for npm git: dependencies.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git bubblewrap openssh-client && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer). hatch_build.py is the
# wheel-time freshness hook declared in pyproject.toml's
# [tool.hatch.build.targets.wheel.hooks.custom]; it must be present even
# during the stub install or hatchling errors.
COPY pyproject.toml README.md LICENSE hatch_build.py ./
RUN mkdir -p pythinker bridge && touch pythinker/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf pythinker bridge

# Copy the full source, then the pre-built WebUI dist from the builder
# stage, then install. The dist copy must come BEFORE the install so the
# wheel ships with the bundle baked in.
COPY pythinker/ pythinker/
COPY bridge/ bridge/
COPY --from=webui-builder /build/pythinker/web/dist/ /app/pythinker/web/dist/
RUN uv pip install --system --no-cache .

# Build the WhatsApp bridge
WORKDIR /app/bridge
RUN git config --global --add url."https://github.com/".insteadOf ssh://git@github.com/ && \
    git config --global --add url."https://github.com/".insteadOf git@github.com: && \
    npm install && npm run build
WORKDIR /app

# Create non-root user and config directory
RUN useradd -m -u 1000 -s /bin/bash pythinker && \
    mkdir -p /home/pythinker/.pythinker && \
    chown -R pythinker:pythinker /home/pythinker /app

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

USER pythinker
ENV HOME=/home/pythinker

# Gateway health endpoint (18790) and WebUI/WebSocket channel (8765)
EXPOSE 18790 8765

ENTRYPOINT ["entrypoint.sh"]
CMD ["status"]

# ---------------------------------------------------------------------------
# Stage 3: browser-runtime — sandboxed Chromium + CDP for the browser tool
# (built only when `docker compose --profile browser up`).
# ---------------------------------------------------------------------------
FROM debian:trixie-slim AS browser-runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji \
        ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash --uid 1100 sandbox

USER sandbox
WORKDIR /home/sandbox

EXPOSE 9222
EXPOSE 6080

COPY --chown=sandbox:sandbox docker/browser-entrypoint.sh /home/sandbox/entrypoint.sh
RUN chmod +x /home/sandbox/entrypoint.sh

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:9222/json/version || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/home/sandbox/entrypoint.sh"]
