# syntax=docker/dockerfile:1.7
#
# Derived Hermes Agent image (NousResearch upstream + local extras).
#
# Upstream docs:
#   https://hermes-agent.nousresearch.com/docs/user-guide/docker
# Official pattern: FROM nousresearch/hermes-agent → install as root → keep
# default ENTRYPOINT ["/init", "/opt/hermes/docker/main-wrapper.sh"] (s6-overlay).
#
# Size notes:
#   Upstream `nousresearch/hermes-agent` is ~2.6GB — that is the hard floor for
#   any derived image. Our layers previously added ~0.5GB mostly from optional
#   local STT/TTS stacks (faster-whisper / piper-tts). Those are OFF by default;
#   enable via build args when needed.
#
# Build (slim default):
#   docker build -t hermes-agent:meson .
#
# Build (full extras):
#   docker build \
#     --build-arg INSTALL_FASTER_WHISPER=1 \
#     --build-arg INSTALL_PIPER_TTS=1 \
#     --build-arg INSTALL_AGENT_UTILS=1 \
#     --build-arg INSTALL_OPS_TOOLS=1 \
#     -t hermes-agent:meson .
#
# Run (prefer compose):
#   docker compose up -d --build

ARG HERMES_BASE_IMAGE=nousresearch/hermes-agent:latest
FROM ${HERMES_BASE_IMAGE}

# ARGs after FROM must be re-declared to be usable in this stage.
ARG HERMES_BASE_IMAGE=nousresearch/hermes-agent:latest
# Optional / heavy — default OFF to keep the derived layer small.
ARG INSTALL_OPS_TOOLS=0
ARG INSTALL_AGENT_UTILS=0
ARG INSTALL_FASTER_WHISPER=0
ARG INSTALL_PIPER_TTS=0
# Lightweight extras used by local skills/scripts — default ON.
ARG INSTALL_EDGE_TTS=1
ARG INSTALL_DDGS=1
ARG FASTER_WHISPER_VERSION=1.2.1
ARG SOUNDFILE_VERSION=0.13.1

LABEL org.opencontainers.image.title="hermes-agent-meson" \
      org.opencontainers.image.description="Custom Hermes Agent image with optional TTS/STT extras and agent tooling" \
      org.opencontainers.image.source="https://github.com/NousResearch/hermes-agent" \
      org.opencontainers.image.base.name="${HERMES_BASE_IMAGE}"

# Documented runtime knobs (inherited / used by compose & s6 stage2 hook)
# HERMES_HOME=/opt/data          data volume (do not change unless you remount)
# HERMES_UID / HERMES_GID        remap internal hermes user to host owner
# HERMES_DASHBOARD=1             enable supervised dashboard alongside gateway
# TZ                             container timezone
# GATEWAY_HEALTH_URL             dashboard→gateway HTTP probe (multi-container)
# API_SERVER_*                   OpenAI-compatible API + /health on :8642
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# s6-overlay's /init must start as root so cont-init can usermod/chown volumes.
# Privilege drop happens via s6-setuidgid → hermes (UID 10000 by default).
# Do NOT switch to USER hermes here — that breaks HERMES_UID remapping.
USER root

# Only packages NOT already provided by the upstream image.
# Intentionally omitted (already present or harmful to reinstall):
#   curl git ffmpeg gcc python3 python3-dev libffi-dev procps openssh-client
#   docker-cli ripgrep ca-certificates nodejs/npm (Node 22 lives in /usr/local)
#   tini (upstream /usr/bin/tini → /init), piper apt (GTK gaming tool ≠ piper-tts)
#   build-essential (wheels via uv — not needed at runtime)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    NEED_APT=0; \
    if [ "${INSTALL_AGENT_UTILS}" = "1" ] \
       || [ "${INSTALL_OPS_TOOLS}" = "1" ] \
       || [ "${INSTALL_FASTER_WHISPER}" = "1" ]; then \
        NEED_APT=1; \
    fi; \
    if [ "${NEED_APT}" = "1" ]; then \
        apt-get update; \
    fi; \
    if [ "${INSTALL_AGENT_UTILS}" = "1" ]; then \
        apt-get install -y --no-install-recommends \
            unzip \
            jq \
            yq \
            wget \
            gnupg \
            sqlite3 \
            postgresql-client \
            imagemagick \
            poppler-utils \
            dnsutils \
            netcat-traditional \
        ; \
    fi; \
    if [ "${INSTALL_OPS_TOOLS}" = "1" ]; then \
        apt-get install -y --no-install-recommends \
            htop \
            vim-tiny \
        ; \
    fi; \
    # libsndfile1: runtime lib for soundfile (local STT). iputils-ping is tiny
    # and already satisfied on many bases; install only when STT stack is on.
    if [ "${INSTALL_FASTER_WHISPER}" = "1" ]; then \
        apt-get install -y --no-install-recommends \
            libsndfile1 \
        ; \
    fi; \
    rm -rf /var/lib/apt/lists/*

# Hermes seals /opt/hermes at runtime (HERMES_DISABLE_LAZY_INSTALLS=1).
# Bake selected Python extras into the image venv so they survive restarts.
#   ddgs / edge-tts : search + cloud TTS (english-learning-pack) — default ON
#   piper-tts       : local TTS (~100MB w/ onnxruntime) — default OFF
#   faster-whisper  : local STT (~265MB+ w/ ctranslate2/av) — default OFF
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eux; \
    PKGS=""; \
    if [ "${INSTALL_DDGS}" = "1" ]; then PKGS="${PKGS} ddgs"; fi; \
    if [ "${INSTALL_EDGE_TTS}" = "1" ]; then PKGS="${PKGS} edge-tts"; fi; \
    if [ "${INSTALL_PIPER_TTS}" = "1" ]; then PKGS="${PKGS} piper-tts"; fi; \
    if [ "${INSTALL_FASTER_WHISPER}" = "1" ]; then \
        PKGS="${PKGS} faster-whisper==${FASTER_WHISPER_VERSION} soundfile==${SOUNDFILE_VERSION}"; \
    fi; \
    if [ -n "${PKGS}" ]; then \
        uv pip install --python /opt/hermes/.venv/bin/python ${PKGS}; \
    fi; \
    find /opt/hermes/.venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Optional local overlays (also bind-mountable via compose for live edits).
# Skills/scripts normally live under $HERMES_HOME (/opt/data) on the volume;
# these copies seed /opt/hermes-custom for reference or first-boot sync.
COPY --chown=root:root skills /opt/hermes-custom/skills
COPY --chown=root:root scripts /opt/hermes-custom/scripts
RUN find /opt/hermes-custom -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true \
    && chmod -R a+rX /opt/hermes-custom \
    && find /opt/hermes-custom/scripts -type f -name '*.sh' -exec chmod a+x {} +

WORKDIR /opt/data
VOLUME ["/opt/data"]

# Healthchecks are service-specific (gateway vs dashboard) — defined in
# docker-compose.yaml. A single image HEALTHCHECK would false-fail the
# dashboard container which does not run `gateway`.

# Keep upstream ENTRYPOINT (/init + main-wrapper). Pass CMD via compose / docker run.
# Example: docker run … hermes-agent:meson gateway run
USER root
